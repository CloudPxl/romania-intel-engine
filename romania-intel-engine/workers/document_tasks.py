"""The actual in-process task runner: two asyncio.Queue()s
(fast_text_queue, heavy_ocr_queue), bounded worker-pool coroutines consuming
each, routing logic (digital-text PDFs parsed instantly via pdfplumber/fitz,
scanned ones rendered + OCR'd in page batches), a per-document hard timeout
that can actually stop the work, and the call into document_extractions.py to
persist results.

See workers/__init__.py's module docstring for the Celery-vs-asyncio
decision and the OCR-binary-availability constraint. This module never
imports Celery and never will — it's plain asyncio, same as every other
background job in this codebase.

Three properties are load-bearing and each replaced a real failure mode:

1. **A dedicated thread pool, never the default executor.** The heavy path's
   poppler render and Tesseract calls are minutes-long and CPU-bound. They
   used to run on `run_in_executor(None, ...)` — the same shared default
   executor that scrapers/matrix/infra_scrapers.py deliberately offloads
   CNAIR's 278-page PDF parse onto so orchestrator.run_tick's
   TICK_DEADLINE_SECONDS stays enforceable. A handful of large scans could
   therefore occupy every thread in that pool and stall ingestion, which is
   precisely the starvation that offload exists to prevent. Document work now
   has its own bounded pool, so the worst case is that documents queue behind
   each other rather than that ingestion stops.

2. **Cancellation that reaches the thread.** asyncio.wait_for cancels the
   *await*, not the OS thread behind run_in_executor — so the old timeout
   marked a document "failed" while its thread kept rendering pages, holding
   the full PDF bytes and its pool slot for however long the work really
   took. Worse, the tempfile.TemporaryDirectory the render was writing into
   had already been removed by the unwinding `with` block. Both pipelines now
   take a CancellationToken (a threading.Event the sync code polls at page
   boundaries) which _execute sets when the timeout fires, so the thread
   actually stops and releases its slot and its bytes.

3. **Admission control in bytes, not items.** The queues were unbounded and
   each item holds an entire PDF in memory. A count-bounded queue would not
   have fixed that — 64 slots x 40MB is still 2.5GB on a 512MB box — so
   admission is budgeted against total *resident* bytes (everything queued
   plus everything in flight). Over budget, the upload is rejected with an
   honest Romanian reason written onto its document_extractions row, which is
   what the frontend poller already surfaces, rather than being silently
   dropped or left at "queued" forever.

Lifecycle: api.py's lifespan calls start_workers() once at startup (mirrors
how it already starts the APScheduler job) and stop_workers() on shutdown.
api.py's POST /api/v1/addons/upload-caiet-async route calls enqueue_document()
via asyncio.create_task(...) — the same fire-and-forget dispatch pattern
api.py's /api/v1/system/tick already uses — so the request returns
immediately with {"doc_id", "status": "queued"} while classification,
rendering, and OCR happen entirely off the request thread.
"""

import asyncio
import logging
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

import document_extractions
from scrapers import pdf_table_extractor
from workers import ocr_engine, pdf_preprocessor

logger = logging.getLogger("DocumentTasks")


def _env_int(name: str, default: int) -> int:
    """Tunable without a redeploy, but never fatal: a malformed value falls
    back to the default rather than crashing app startup, since these are
    read at import time inside a web process."""
    try:
        value = int(os.getenv(name, "").strip() or default)
    except ValueError:
        logger.warning(f"[DocumentTasks] {name} is not an integer — using default {default}")
        return default
    return value if value > 0 else default


# Page-rendering (pdf2image) is the expensive, RAM-hungry part of the heavy
# path — each page becomes a full-resolution raster image — so this bounds how
# many documents can be *inside that stage* concurrently, independent of how
# many are merely queued. Kept low deliberately: Render's free tier has 512MB
# total, and a single 100+ page scan rendered at 300dpi already uses a
# meaningful fraction of that on its own.
HEAVY_OCR_MAX_CONCURRENT = _env_int("DOCUMENT_HEAVY_MAX_CONCURRENT", 2)

# The fast path is far cheaper per document but is not free — fitz holds the
# parsed document tree and pdfplumber's table detection is genuinely slow on a
# large grid — so it gets its own bound rather than being allowed to spawn one
# thread per queued item.
FAST_TEXT_MAX_CONCURRENT = _env_int("DOCUMENT_FAST_MAX_CONCURRENT", 3)

# Threads in this module's own pool. Must be >= the two concurrency limits
# above combined, or a document holding a semaphore would wait on a thread
# that a document *without* the semaphore is occupying.
DOCUMENT_POOL_THREADS = _env_int(
    "DOCUMENT_POOL_THREADS", HEAVY_OCR_MAX_CONCURRENT + FAST_TEXT_MAX_CONCURRENT + 1
)

# Hard ceiling per document, regardless of page count or which stage is slow.
# _execute cancels on this; unlike before, the cancellation reaches the worker
# thread (see the CancellationToken note in this module's docstring), so the
# document is recorded 'failed' with an honest reason *and* stops consuming
# CPU and memory.
PER_DOCUMENT_TIMEOUT_SECONDS = float(os.getenv("PER_DOCUMENT_TIMEOUT_SECONDS", "180") or 180)

# Largest single upload accepted into the pipeline. Above this the document is
# rejected outright rather than admitted and then failed on the timeout, which
# would have burned the full timeout window and a pool slot to reach the same
# outcome.
MAX_DOCUMENT_BYTES = _env_int("MAX_DOCUMENT_BYTES", 40 * 1024 * 1024)

# Total PDF bytes allowed to be resident in the pipeline at once — queued
# plus in flight. This, not a queue item count, is what maps onto the
# container's memory limit.
QUEUE_MAX_RESIDENT_BYTES = _env_int("DOCUMENT_QUEUE_MAX_RESIDENT_BYTES", 96 * 1024 * 1024)

# Secondary guard so a flood of very small PDFs can't build an arbitrarily
# long queue while staying under the byte budget.
QUEUE_MAXSIZE = _env_int("DOCUMENT_QUEUE_MAXSIZE", 64)

# Pages beyond this are not processed. Matches pdf_table_extractor.MAX_PAGES
# and the previous render_pdf_to_images default, so the cap is the same number
# on both paths instead of two independently-drifting limits.
MAX_DOCUMENT_PAGES = _env_int("MAX_DOCUMENT_PAGES", pdf_table_extractor.MAX_PAGES)

# The heavy path renders and OCRs in batches of this many pages, deleting each
# batch's images before rendering the next. Two reasons, both real: it caps
# peak temp-disk use at a batch rather than the whole document, and it gives
# the cancellation token a checkpoint every few pages instead of one opaque
# multi-minute poppler call across the entire PDF.
OCR_PAGE_BATCH = _env_int("DOCUMENT_OCR_PAGE_BATCH", 10)


class DocumentCancelled(Exception):
    """Raised inside a worker thread when its document's deadline passed.

    Its own type so _execute can tell "we stopped this on purpose" apart from
    a genuine parsing failure and report the timeout reason rather than an
    incidental exception message from wherever the work happened to be.
    """


class CancellationToken:
    """A threading.Event the synchronous, thread-bound stages poll.

    asyncio cannot interrupt a running executor thread; the only thing that
    stops one is the code inside it choosing to stop. So the async side sets
    this and the sync side checks it at every page boundary — bounded-latency
    cancellation rather than none at all.
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise DocumentCancelled()


_NULL_TOKEN = CancellationToken()


def _page_count(pdf_bytes: bytes) -> int:
    """Page count via pymupdf rather than poppler's pdfinfo — it's already a
    dependency, needs no system binary, and this has to work on the heavy path
    where we cannot assume poppler is installed until we've actually checked."""
    import pymupdf

    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            return doc.page_count
    except Exception as e:
        logger.warning(f"[DocumentTasks] could not read page count: {e}")
        return 0


def _extract_digital_text_and_tables(
    pdf_bytes: bytes, token: CancellationToken = _NULL_TOKEN
) -> "tuple[str, List[list]]":
    """The fast path's actual parsing. Plain sync function run inside the
    document thread pool (see run_fast_text_pipeline) since fitz/pdfplumber are
    synchronous, CPU-bound libraries with no asyncio awareness of their own.
    fitz (PyMuPDF) does the full-document text pull since it's materially
    faster than pdfplumber for plain text on a large digital PDF; pdfplumber
    is kept as-is for pdf_preprocessor.classify_pdf's sampling and for
    scrapers/pdf_table_extractor.py's grid-line table detection, which fitz
    has no equivalent for.

    Checks `token` between pages: on a 150-page document this is the
    difference between a timeout that stops the work and one that only stops
    waiting for it.
    """
    import pymupdf as fitz  # `fitz` is pymupdf's legacy import name, now deprecated in favor of this one

    text_parts: List[str] = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for index, page in enumerate(doc):
                if index >= MAX_DOCUMENT_PAGES:
                    logger.info(
                        f"[DocumentTasks] stopping text extraction at the "
                        f"{MAX_DOCUMENT_PAGES}-page cap ({doc.page_count} pages present)"
                    )
                    break
                token.check()
                text_parts.append(page.get_text())
    except DocumentCancelled:
        raise
    except Exception as e:
        logger.error(f"[DocumentTasks] fitz text extraction failed: {e}")
    text = "\n".join(text_parts)
    # The table pass is one opaque pdfplumber call, so the only useful
    # checkpoint is before entering it — skipping it entirely on an already
    # expired document beats spending the slowest stage on a result nobody
    # will read.
    token.check()
    tables = pdf_table_extractor.extract_table_rows(pdf_bytes, max_pages=MAX_DOCUMENT_PAGES)
    return text, tables


def _ocr_one_page(image_path: str, token: CancellationToken) -> str:
    """Preprocess + OCR a single rendered page in one pool round-trip.

    Folded into one call because the two stages are always run back to back on
    the same image, and splitting them doubled the executor hand-offs per page
    for no benefit — on a 150-page scan that was 300 round-trips.
    """
    token.check()
    processed = pdf_preprocessor.preprocess_image_for_ocr(image_path)
    token.check()
    return ocr_engine.ocr_image(processed) or ""


async def run_fast_text_pipeline(
    pdf_bytes: bytes, token: Optional[CancellationToken] = None
) -> Dict[str, Any]:
    """Pure extraction for a digital-text PDF — no persistence here, so this
    is shared as-is between the real worker consumer and tests (see
    tests/test_document_worker.py), which can call it directly without a
    database configured.

    `token` is optional so a direct caller (a test, or any future in-process
    use) can invoke this without constructing one; the runner always passes a
    real one.
    """
    token = token or CancellationToken()
    loop = asyncio.get_running_loop()
    text, tables = await loop.run_in_executor(
        _pool(), _extract_digital_text_and_tables, pdf_bytes, token
    )
    sections = ocr_engine.detect_legal_sections(text)
    return {
        "status": "done",
        "raw_text": text,
        "tables_json": tables,
        "ocr_applied": False,
        "sections_json": sections,
        "error_message": None,
    }


async def run_heavy_ocr_pipeline(
    pdf_bytes: bytes, token: Optional[CancellationToken] = None
) -> Dict[str, Any]:
    """Pure OCR extraction for a scanned PDF — render -> preprocess -> OCR
    -> section/table detection, in batches of OCR_PAGE_BATCH pages. No
    persistence here either, for the same testability reason as
    run_fast_text_pipeline.

    Batching is what makes this both bounded and interruptible: each batch's
    images are deleted before the next is rendered, so peak temp-disk use is a
    batch rather than the whole document, and every batch boundary is a point
    at which the per-document timeout can actually stop the work.

    Degrades honestly (status='failed', ocr_applied=False, a specific
    error_message) instead of raising when tesseract/poppler binaries are
    unavailable — expected on the current Render deployment, see
    workers/__init__.py — or when poppler fails partway through rendering.
    """
    token = token or CancellationToken()
    availability = ocr_engine.check_ocr_binaries()
    if not (availability["tesseract"] and availability["poppler"]):
        reason = (
            "OCR nu poate rula pe acest mediu: "
            f"tesseract={'prezent' if availability['tesseract'] else 'lipsă'}, "
            f"poppler={'prezent' if availability['poppler'] else 'lipsă'}. "
            "Necesită schimbarea mediului de build Render (Docker/aptfile) pentru a instala "
            "tesseract-ocr + tesseract-ocr-ron + poppler-utils."
        )
        logger.warning(f"[DocumentTasks] OCR binaries unavailable — {reason}")
        return {
            "status": "failed",
            "raw_text": "",
            "tables_json": [],
            "ocr_applied": False,
            "sections_json": {},
            "error_message": reason,
        }

    loop = asyncio.get_running_loop()
    total_pages = await loop.run_in_executor(_pool(), _page_count, pdf_bytes)
    if total_pages <= 0:
        return {
            "status": "failed",
            "raw_text": "",
            "tables_json": [],
            "ocr_applied": False,
            "sections_json": {},
            "error_message": "Documentul nu a putut fi citit ca PDF (0 pagini detectate).",
        }
    last_page = min(total_pages, MAX_DOCUMENT_PAGES)
    truncated = total_pages > last_page

    page_texts: List[str] = []
    with tempfile.TemporaryDirectory(prefix="docworker_") as tmpdir:
        for batch_start in range(1, last_page + 1, OCR_PAGE_BATCH):
            batch_end = min(batch_start + OCR_PAGE_BATCH - 1, last_page)
            try:
                image_paths = await loop.run_in_executor(
                    _pool(),
                    _render_batch,
                    pdf_bytes,
                    tmpdir,
                    batch_start,
                    batch_end,
                    token,
                )
            except pdf_preprocessor.PopplerUnavailableError as e:
                logger.warning(f"[DocumentTasks] poppler rendering failed — {e}")
                return {
                    "status": "failed",
                    "raw_text": "",
                    "tables_json": [],
                    "ocr_applied": False,
                    "sections_json": {},
                    "error_message": str(e),
                }

            for image_path in image_paths:
                page_texts.append(await loop.run_in_executor(_pool(), _ocr_one_page, image_path, token))

            # Free this batch's rasters before rendering the next one. tmpdir
            # itself is still removed by the `with` block on any exit path,
            # including cancellation — this only keeps the *peak* down.
            for image_path in image_paths:
                try:
                    os.unlink(image_path)
                except OSError:
                    pass

    text = "\n".join(page_texts)
    note = None
    if truncated:
        note = (
            f"Document trunchiat: au fost procesate primele {last_page} pagini "
            f"din {total_pages}."
        )
        logger.info(f"[DocumentTasks] {note}")
    return {
        "status": "done",
        "raw_text": text,
        "tables_json": ocr_engine.extract_tables_heuristic(text),
        "ocr_applied": True,
        "sections_json": ocr_engine.detect_legal_sections(text),
        "error_message": note,
    }


def _render_batch(
    pdf_bytes: bytes, tmpdir: str, first_page: int, last_page: int, token: CancellationToken
) -> List[str]:
    token.check()
    return pdf_preprocessor.render_pdf_to_images(
        pdf_bytes, tmpdir, first_page=first_page, last_page=last_page
    )


# ---------------------------------------------------------------------------
# The document thread pool.
#
# Module-level and shared by every runner, because the resource it represents
# (OS threads) is per-process, not per-runner. Created lazily so importing
# this module — which tests and the API both do at import time — doesn't spawn
# anything on its own.
# ---------------------------------------------------------------------------

_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()


def _pool() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=DOCUMENT_POOL_THREADS, thread_name_prefix="docworker"
                )
                logger.info(f"[DocumentTasks] thread pool up ({DOCUMENT_POOL_THREADS} threads)")
    return _executor


def shutdown_pool(wait: bool = False) -> None:
    """Released on app shutdown. `wait=False` by default deliberately: a
    wedged OCR thread must not be able to hold the process open past its
    shutdown grace period — the token is what stops the work, and anything
    still running is abandoned rather than waited on."""
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=wait, cancel_futures=True)
            _executor = None


class DocumentTaskRunner:
    """Owns the two queues, their consumer coroutines, and the resident-byte
    budget. A module-level singleton (get_runner()) is what api.py actually
    talks to; the class itself takes constructor overrides so tests can build
    an isolated instance with a short per_document_timeout or a tiny byte
    budget instead of waiting out the real 180s default or allocating 96MB."""

    def __init__(
        self,
        heavy_ocr_max_concurrent: int = HEAVY_OCR_MAX_CONCURRENT,
        fast_text_max_concurrent: int = FAST_TEXT_MAX_CONCURRENT,
        per_document_timeout: float = PER_DOCUMENT_TIMEOUT_SECONDS,
        max_document_bytes: int = MAX_DOCUMENT_BYTES,
        max_resident_bytes: int = QUEUE_MAX_RESIDENT_BYTES,
        queue_maxsize: int = QUEUE_MAXSIZE,
    ):
        self.fast_text_queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
        self.heavy_ocr_queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
        self._heavy_semaphore = asyncio.Semaphore(heavy_ocr_max_concurrent)
        self._fast_semaphore = asyncio.Semaphore(fast_text_max_concurrent)
        self._heavy_max_concurrent = heavy_ocr_max_concurrent
        self._fast_max_concurrent = fast_text_max_concurrent
        self._per_document_timeout = per_document_timeout
        self._max_document_bytes = max_document_bytes
        self._max_resident_bytes = max_resident_bytes
        self._resident_bytes = 0
        self._consumer_tasks: List[asyncio.Task] = []
        # Strong references to in-flight per-document tasks. asyncio only
        # holds a weak reference to a running task, so a task whose only
        # reference was the local in the consumer loop could be garbage
        # collected mid-document — the document would then sit at
        # 'processing' forever with nothing having failed.
        self._inflight: set = set()
        self._started = False

    # -- resident-byte admission control ------------------------------------
    #
    # Both helpers are only ever called from the event loop thread, so the
    # read-modify-write needs no lock. enqueue() reserves *before* its first
    # await, which is what makes the check-then-admit atomic.

    def _reserve(self, size: int) -> bool:
        if self._resident_bytes + size > self._max_resident_bytes:
            return False
        self._resident_bytes += size
        return True

    def _release(self, size: int) -> None:
        self._resident_bytes = max(0, self._resident_bytes - size)

    def stats(self) -> Dict[str, Any]:
        """Surfaced on /api/v1/system/status. Counts and byte totals only —
        never filenames or doc ids, since that route is public."""
        return {
            "fast_text_queued": self.fast_text_queue.qsize(),
            "heavy_ocr_queued": self.heavy_ocr_queue.qsize(),
            "in_flight": len(self._inflight),
            "resident_bytes": self._resident_bytes,
            "resident_bytes_limit": self._max_resident_bytes,
            "pool_threads": DOCUMENT_POOL_THREADS,
            "started": self._started,
        }

    def start(self) -> None:
        """Idempotent — api.py's lifespan is the only expected caller, but a
        second call (e.g. a test reusing a runner) is a no-op rather than
        spawning duplicate consumer loops."""
        if self._started:
            return
        self._started = True
        self._consumer_tasks = [
            asyncio.create_task(self._consume_fast_text(), name="fast_text_consumer"),
            asyncio.create_task(self._consume_heavy_ocr(), name="heavy_ocr_consumer"),
        ]
        logger.info(
            f"[DocumentTaskRunner] started (fast={self._fast_max_concurrent}, "
            f"heavy={self._heavy_max_concurrent} concurrent documents, "
            f"{self._per_document_timeout:.0f}s per-document timeout, "
            f"{self._max_resident_bytes // (1024 * 1024)}MB resident budget)"
        )

    async def stop(self) -> None:
        """Cancels the consumer loops and every in-flight document, then
        releases the thread pool. Called from api.py's lifespan shutdown so a
        redeploy doesn't leave OCR threads running against a dying process."""
        for task in self._consumer_tasks:
            task.cancel()
        for task in list(self._inflight):
            task.cancel()
        pending = self._consumer_tasks + list(self._inflight)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._consumer_tasks = []
        self._inflight.clear()
        self._resident_bytes = 0
        self._started = False
        shutdown_pool()

    async def _reject(self, doc_id: str, reason: str) -> str:
        """A refused document is recorded as failed, not dropped. The
        frontend's OCR poller already renders `error_message` on a failed row,
        so this is what turns backpressure into something a user can read
        instead of a document stuck at 'queued' forever."""
        logger.warning(f"[DocumentTaskRunner] {doc_id} rejected: {reason}")
        await document_extractions.mark_result(
            doc_id, status="failed", raw_text="", tables_json=[],
            ocr_applied=False, sections_json={}, error_message=reason,
        )
        return "rejected"

    async def enqueue(self, doc_id: str, notice_id: Optional[str], filename: str, pdf_bytes: bytes) -> str:
        """Admits, classifies, and routes one document. Returns the queue it
        landed on, or "rejected".

        Order matters: the byte budget is reserved *before* the classification
        await, so a burst of simultaneous uploads can't all pass the check and
        then all be admitted. Classification itself (a cheap pdfplumber
        page-sample) runs on the document pool so it never blocks the event
        loop, even though by the time this runs it's already off the request
        thread — api.py dispatches this via asyncio.create_task rather than
        awaiting it inline.
        """
        size = len(pdf_bytes)
        if size > self._max_document_bytes:
            return await self._reject(
                doc_id,
                f"Documentul depășește limita de {self._max_document_bytes // (1024 * 1024)} MB "
                f"({size / (1024 * 1024):.1f} MB). Încărcați doar secțiunile relevante.",
            )
        if not self._reserve(size):
            return await self._reject(
                doc_id,
                "Coada de procesare a documentelor este plină (limita de memorie a fost atinsă). "
                "Reîncercați în câteva minute.",
            )

        try:
            loop = asyncio.get_running_loop()
            classification = await loop.run_in_executor(_pool(), pdf_preprocessor.classify_pdf, pdf_bytes)
            item = {
                "doc_id": doc_id,
                "notice_id": notice_id,
                "filename": filename,
                "pdf_bytes": pdf_bytes,
                "size": size,
            }
            if classification.get("classification") == "digital":
                self.fast_text_queue.put_nowait(item)
                route = "fast_text"
            else:
                self.heavy_ocr_queue.put_nowait(item)
                route = "heavy_ocr"
        except asyncio.QueueFull:
            self._release(size)
            return await self._reject(
                doc_id,
                "Coada de procesare a documentelor este plină. Reîncercați în câteva minute.",
            )
        except Exception as e:
            self._release(size)
            logger.error(f"[DocumentTaskRunner] {doc_id} could not be enqueued: {type(e).__name__}: {e}")
            return await self._reject(doc_id, f"Documentul nu a putut fi preluat pentru procesare: {e}")

        logger.info(f"[DocumentTaskRunner] {doc_id} -> {route} queue ({classification})")
        return route

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _consume_fast_text(self) -> None:
        while True:
            item = await self.fast_text_queue.get()
            self._spawn(self._run_fast(item))

    async def _run_fast(self, item: Dict[str, Any]) -> None:
        try:
            async with self._fast_semaphore:
                await self._execute(item, run_fast_text_pipeline)
        finally:
            self._finish(item, self.fast_text_queue)

    async def _consume_heavy_ocr(self) -> None:
        while True:
            item = await self.heavy_ocr_queue.get()
            # The consumer loop itself dequeues instantly and spawns one task
            # per document; the concurrency limit is enforced by the semaphore
            # acquired inside _run_heavy, not by limiting how many tasks exist
            # — extra tasks beyond the limit simply wait on the semaphore,
            # which costs a coroutine frame, not CPU. Their *bytes* are what
            # the resident budget bounds.
            self._spawn(self._run_heavy(item))

    async def _run_heavy(self, item: Dict[str, Any]) -> None:
        try:
            async with self._heavy_semaphore:
                await self._execute(item, run_heavy_ocr_pipeline)
        finally:
            self._finish(item, self.heavy_ocr_queue)

    def _finish(self, item: Dict[str, Any], queue: asyncio.Queue) -> None:
        """Drops the document's bytes and returns its budget. Popping the key
        matters: the item dict is referenced by this task's frame until the
        task object is discarded, so leaving the bytes on it would keep a full
        PDF alive past the work that needed it."""
        item.pop("pdf_bytes", None)
        self._release(item.get("size", 0))
        queue.task_done()

    async def _execute(self, item: Dict[str, Any], pipeline_fn: Callable) -> None:
        doc_id = item["doc_id"]
        token = CancellationToken()
        await document_extractions.mark_processing(doc_id)
        try:
            result = await asyncio.wait_for(
                pipeline_fn(item["pdf_bytes"], token), timeout=self._per_document_timeout
            )
        except asyncio.TimeoutError:
            # This is the half that used to be missing. wait_for has already
            # stopped awaiting; setting the token is what stops the thread
            # still doing the work, so it releases its pool slot and its copy
            # of the PDF at the next page boundary instead of running to
            # completion for a result that will never be read.
            token.cancel()
            msg = (
                f"Procesarea documentului a depășit limita de "
                f"{self._per_document_timeout:.0f}s și a fost întreruptă."
            )
            logger.error(f"[DocumentTaskRunner] {doc_id}: timed out after {self._per_document_timeout:.0f}s")
            await document_extractions.mark_result(
                doc_id, status="failed", raw_text="", tables_json=[],
                ocr_applied=False, sections_json={}, error_message=msg,
            )
            return
        except asyncio.CancelledError:
            # Shutdown, not a document fault. Stop the thread too, then let
            # the cancellation propagate so stop() can finish.
            token.cancel()
            raise
        except DocumentCancelled:
            # The token fired without wait_for timing out — only reachable on
            # shutdown races. Recorded honestly rather than as a parse error.
            await document_extractions.mark_result(
                doc_id, status="failed", raw_text="", tables_json=[],
                ocr_applied=False, sections_json={},
                error_message="Procesarea a fost întreruptă înainte de finalizare.",
            )
            return
        except Exception as e:
            logger.error(f"[DocumentTaskRunner] {doc_id} failed: {type(e).__name__}: {e}")
            await document_extractions.mark_result(
                doc_id, status="failed", raw_text="", tables_json=[],
                ocr_applied=False, sections_json={}, error_message=str(e),
            )
            return
        await document_extractions.mark_result(doc_id, **result)


_runner: Optional[DocumentTaskRunner] = None


def get_runner() -> DocumentTaskRunner:
    global _runner
    if _runner is None:
        _runner = DocumentTaskRunner()
    return _runner


def start_workers() -> None:
    """Called once from api.py's lifespan startup, same lifecycle point as
    the APScheduler job."""
    get_runner().start()


async def stop_workers() -> None:
    """Called from api.py's lifespan shutdown, opposite start_workers()."""
    if _runner is not None:
        await _runner.stop()


async def enqueue_document(doc_id: str, notice_id: Optional[str], filename: str, pdf_bytes: bytes) -> str:
    return await get_runner().enqueue(doc_id, notice_id, filename, pdf_bytes)
