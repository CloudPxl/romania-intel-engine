"""The actual in-process task runner: two asyncio.Queue()s
(fast_text_queue, heavy_ocr_queue), bounded worker-pool coroutines consuming
each, routing logic (digital-text PDFs parsed instantly via pdfplumber/fitz,
scanned ones rendered + OCR'd), a 180s per-document hard timeout, and the
call into document_extractions.py to persist results.

See workers/__init__.py's module docstring for the Celery-vs-asyncio
decision and the OCR-binary-availability constraint. This module never
imports Celery and never will — it's plain asyncio, same as every other
background job in this codebase.

Lifecycle: api.py's lifespan calls start_workers() once at startup (mirrors
how it already starts the APScheduler job). api.py's
POST /api/v1/addons/upload-caiet-async route calls enqueue_document() via
asyncio.create_task(...) — the same fire-and-forget dispatch pattern
api.py's /api/v1/system/tick already uses — so the request returns
immediately with {"doc_id", "status": "queued"} while classification,
rendering, and OCR happen entirely off the request thread.
"""

import asyncio
import logging
import tempfile
from typing import Any, Dict, List, Optional

import document_extractions
from scrapers import pdf_table_extractor
from workers import ocr_engine, pdf_preprocessor

logger = logging.getLogger("DocumentTasks")

# Page-rendering (pdf2image) is the expensive, RAM-hungry part of the heavy
# path — each page becomes a full-resolution raster image in memory — so
# this bounds how many documents can be *inside that stage* concurrently,
# independent of how many are merely queued. Kept low deliberately: Render's
# free tier has 512MB total, and a single 100+ page scan rendered at 300dpi
# already uses a meaningful fraction of that on its own.
HEAVY_OCR_MAX_CONCURRENT = 4

# Hard ceiling per document, regardless of page count or which stage is
# slow. wait_for cancels the pipeline coroutine if it's exceeded; the
# document is recorded as 'failed' with an honest reason rather than left
# stuck in 'processing' forever.
PER_DOCUMENT_TIMEOUT_SECONDS = 180.0


def _extract_digital_text_and_tables(pdf_bytes: bytes) -> "tuple[str, List[list]]":
    """The fast path's actual parsing. Plain sync function run inside a
    thread executor (see run_fast_text_pipeline) since fitz/pdfplumber are
    synchronous, CPU-bound libraries with no asyncio awareness of their own.
    fitz (PyMuPDF) does the full-document text pull since it's materially
    faster than pdfplumber for plain text on a large digital PDF; pdfplumber
    is kept as-is for pdf_preprocessor.classify_pdf's sampling and for
    scrapers/pdf_table_extractor.py's grid-line table detection, which fitz
    has no equivalent for."""
    import pymupdf as fitz  # `fitz` is pymupdf's legacy import name, now deprecated in favor of this one

    text_parts: List[str] = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                text_parts.append(page.get_text())
    except Exception as e:
        logger.error(f"[DocumentTasks] fitz text extraction failed: {e}")
    text = "\n".join(text_parts)
    tables = pdf_table_extractor.extract_table_rows(pdf_bytes)
    return text, tables


async def run_fast_text_pipeline(pdf_bytes: bytes) -> Dict[str, Any]:
    """Pure extraction for a digital-text PDF — no persistence here, so this
    is shared as-is between the real worker consumer and tests (see
    tests/test_document_worker.py), which can call it directly without a
    database configured."""
    loop = asyncio.get_running_loop()
    text, tables = await loop.run_in_executor(None, _extract_digital_text_and_tables, pdf_bytes)
    sections = ocr_engine.detect_legal_sections(text)
    return {
        "status": "done",
        "raw_text": text,
        "tables_json": tables,
        "ocr_applied": False,
        "sections_json": sections,
        "error_message": None,
    }


async def run_heavy_ocr_pipeline(pdf_bytes: bytes) -> Dict[str, Any]:
    """Pure OCR extraction for a scanned PDF — render -> preprocess -> OCR
    -> section/table detection. No persistence here either, for the same
    testability reason as run_fast_text_pipeline.

    Degrades honestly (status='failed', ocr_applied=False, a specific
    error_message) instead of raising when tesseract/poppler binaries are
    unavailable — expected on the current Render deployment, see
    workers/__init__.py — or when poppler fails partway through rendering.
    """
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
    with tempfile.TemporaryDirectory(prefix="docworker_") as tmpdir:
        try:
            image_paths = await loop.run_in_executor(
                None, pdf_preprocessor.render_pdf_to_images, pdf_bytes, tmpdir
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

        page_texts: List[str] = []
        for image_path in image_paths:
            processed = await loop.run_in_executor(
                None, pdf_preprocessor.preprocess_image_for_ocr, image_path
            )
            page_text = await loop.run_in_executor(None, ocr_engine.ocr_image, processed)
            page_texts.append(page_text or "")
        # image_paths and their preprocessed derivatives live only inside
        # tmpdir, which is removed automatically on this `with` block's exit
        # even if a step above raised or the pipeline is cancelled by the
        # per-document timeout wrapping this whole call.

    text = "\n".join(page_texts)
    return {
        "status": "done",
        "raw_text": text,
        "tables_json": ocr_engine.extract_tables_heuristic(text),
        "ocr_applied": True,
        "sections_json": ocr_engine.detect_legal_sections(text),
        "error_message": None,
    }


class DocumentTaskRunner:
    """Owns the two queues and their consumer coroutines. A module-level
    singleton (get_runner()) is what api.py actually talks to; the class
    itself takes constructor overrides so tests can build an isolated
    instance with a short per_document_timeout instead of waiting out the
    real 180s default."""

    def __init__(
        self,
        heavy_ocr_max_concurrent: int = HEAVY_OCR_MAX_CONCURRENT,
        per_document_timeout: float = PER_DOCUMENT_TIMEOUT_SECONDS,
    ):
        self.fast_text_queue: asyncio.Queue = asyncio.Queue()
        self.heavy_ocr_queue: asyncio.Queue = asyncio.Queue()
        self._heavy_semaphore = asyncio.Semaphore(heavy_ocr_max_concurrent)
        self._heavy_max_concurrent = heavy_ocr_max_concurrent
        self._per_document_timeout = per_document_timeout
        self._consumer_tasks: List[asyncio.Task] = []
        self._started = False

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
            f"[DocumentTaskRunner] started (heavy OCR bounded to "
            f"{self._heavy_max_concurrent} concurrent documents, "
            f"{self._per_document_timeout:.0f}s per-document timeout)"
        )

    async def enqueue(self, doc_id: str, notice_id: Optional[str], filename: str, pdf_bytes: bytes) -> str:
        """Classifies the PDF and routes it onto the right queue. Runs the
        (synchronous, but cheap — see classify_pdf's page-sampling) pdfplumber
        classification in a thread executor so it never blocks this
        coroutine's event loop turn, even though by the time this runs it's
        already off the original request thread (api.py dispatches this via
        asyncio.create_task, not by awaiting it inline)."""
        loop = asyncio.get_running_loop()
        classification = await loop.run_in_executor(None, pdf_preprocessor.classify_pdf, pdf_bytes)
        item = {"doc_id": doc_id, "notice_id": notice_id, "filename": filename, "pdf_bytes": pdf_bytes}
        if classification.get("classification") == "digital":
            await self.fast_text_queue.put(item)
            route = "fast_text"
        else:
            await self.heavy_ocr_queue.put(item)
            route = "heavy_ocr"
        logger.info(f"[DocumentTaskRunner] {doc_id} -> {route} queue ({classification})")
        return route

    async def _consume_fast_text(self) -> None:
        while True:
            item = await self.fast_text_queue.get()
            asyncio.create_task(self._run_fast(item))

    async def _run_fast(self, item: Dict[str, Any]) -> None:
        try:
            await self._execute(item, run_fast_text_pipeline)
        finally:
            self.fast_text_queue.task_done()

    async def _consume_heavy_ocr(self) -> None:
        while True:
            item = await self.heavy_ocr_queue.get()
            # The consumer loop itself dequeues instantly and spawns one
            # task per document; HEAVY_OCR_MAX_CONCURRENT is enforced by the
            # semaphore acquired inside _run_heavy, not by limiting how many
            # tasks exist — extra tasks beyond the limit simply wait on the
            # semaphore, which costs a coroutine frame, not CPU/RAM.
            asyncio.create_task(self._run_heavy(item))

    async def _run_heavy(self, item: Dict[str, Any]) -> None:
        try:
            async with self._heavy_semaphore:
                await self._execute(item, run_heavy_ocr_pipeline)
        finally:
            self.heavy_ocr_queue.task_done()

    async def _execute(self, item: Dict[str, Any], pipeline_fn) -> None:
        doc_id = item["doc_id"]
        await document_extractions.mark_processing(doc_id)
        try:
            result = await asyncio.wait_for(
                pipeline_fn(item["pdf_bytes"]), timeout=self._per_document_timeout
            )
        except asyncio.TimeoutError:
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


async def enqueue_document(doc_id: str, notice_id: Optional[str], filename: str, pdf_bytes: bytes) -> str:
    return await get_runner().enqueue(doc_id, notice_id, filename, pdf_bytes)
