"""Tests for workers/pdf_preprocessor.py, workers/ocr_engine.py, and
workers/document_tasks.py — the async document-ingestion pipeline for heavy
PDF attachments (see workers/__init__.py's module docstring for the
Celery-vs-asyncio and OCR-binary-availability context).

No DATABASE_URL needed: document_extractions.py degrades to a no-op the same
way every other db.py-backed module in this codebase does when persistence
isn't configured, so tests that exercise document_tasks' pipeline functions
directly (rather than through the full enqueue -> consumer -> persist path)
never touch Postgres.

Test PDFs are built on the fly with pymupdf (a real text-layer PDF for the
fast-path/routing tests) rather than checked in as binary fixtures — this is
the fastest way to get a genuinely correct digital PDF, and it exercises the
same library (fitz/pymupdf) document_tasks.py itself uses for extraction.

Run with `pytest` from romania-intel-engine/.
"""

import ast
import asyncio
import gc
import inspect
import os
import threading
import time

import pymupdf
import pytest

from workers import document_tasks, ocr_engine, pdf_preprocessor


def _build_digital_pdf(paragraphs) -> bytes:
    """A real, pymupdf-authored PDF with a genuine text layer — one line per
    string in `paragraphs`, top to bottom on a single page."""
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in paragraphs:
        page.insert_text((72, y), line, fontsize=11)
        y += 18
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


CAIET_PARAGRAPHS = [
    "CAIET DE SARCINI",
    "Reabilitare drum comunal DC12 - documentatie tehnica",
    "",
    "CAP. 1 - OBIECTUL CONTRACTULUI",
    "Prezentul caiet de sarcini stabileste conditiile de executie.",
    "",
    "CAP. 2 - CERINTE TEHNICE MINIME",
    "Ofertantul trebuie sa faca dovada experientei similare.",
    "",
    "CAP. 3 - PERSONAL CHEIE",
    "Manager de proiect si responsabil tehnic cu executia.",
    "",
    "CAP. 4 - GARANTII SI PENALITATI",
    "Garantia de buna executie este de 5% din valoarea contractului.",
]


class TestPdfClassification:
    def test_digital_pdf_is_classified_digital(self):
        pdf_bytes = _build_digital_pdf(CAIET_PARAGRAPHS)
        result = pdf_preprocessor.classify_pdf(pdf_bytes)
        assert result["classification"] == "digital"
        assert result["page_count"] == 1
        assert result["chars_found"] > 0

    def test_blank_page_pdf_is_classified_scanned(self):
        # A page with no text layer at all is the closest a hand-built
        # pymupdf PDF can get to a real scanned/rasterized page without an
        # actual scanner image — pdfplumber's extract_text() returns "" on
        # both, which is exactly the signal classify_pdf keys off of.
        doc = pymupdf.open()
        doc.new_page()
        pdf_bytes = doc.tobytes()
        doc.close()
        result = pdf_preprocessor.classify_pdf(pdf_bytes)
        assert result["classification"] == "scanned"

    def test_corrupt_bytes_default_to_scanned_not_a_crash(self):
        result = pdf_preprocessor.classify_pdf(b"not a real pdf at all")
        assert result["classification"] == "scanned"
        assert "error" in result


class TestFastTextPipeline:
    @pytest.mark.asyncio
    async def test_extracts_real_text_and_detects_all_four_sections(self):
        pdf_bytes = _build_digital_pdf(CAIET_PARAGRAPHS)
        result = await document_tasks.run_fast_text_pipeline(pdf_bytes)

        assert result["status"] == "done"
        assert result["ocr_applied"] is False
        assert result["error_message"] is None
        assert "OBIECTUL CONTRACTULUI" in result["raw_text"]
        assert "experientei similare" in result["raw_text"]

        sections = result["sections_json"]
        assert sections["cap_1_obiectul_contractului"]["found"] is True
        assert sections["cap_2_cerinte_tehnice_minime"]["found"] is True
        assert sections["cap_3_personal_cheie"]["found"] is True
        assert sections["cap_4_garantii_penalitati"]["found"] is True

    @pytest.mark.asyncio
    async def test_pdf_with_no_matching_headers_reports_none_found(self):
        pdf_bytes = _build_digital_pdf(["Un document oarecare fara capitole legale."])
        result = await document_tasks.run_fast_text_pipeline(pdf_bytes)
        sections = result["sections_json"]
        assert all(not s["found"] for s in sections.values())


class TestSectionHeaderDetection:
    """Directly exercises ocr_engine.detect_legal_sections against
    realistic Romanian text with diacritics and OCR-noise-like corruption
    (dropped spaces, a "1" misread pattern), independent of any PDF
    machinery."""

    def test_clean_diacritic_text_all_found(self):
        text = (
            "CAP. 1 – Obiectul Contractului\n"
            "Se stabilesc conditiile.\n"
            "Cap. 2 – Cerințe Tehnice Minime\n"
            "Se solicită experiență similară.\n"
            "CAP.3-Personal Cheie\n"
            "Manager de proiect.\n"
            "Cap. 4 – Garanții și Penalități\n"
            "Garanția este de 5%.\n"
        )
        sections = ocr_engine.detect_legal_sections(text)
        assert sections["cap_1_obiectul_contractului"]["found"] is True
        assert sections["cap_2_cerinte_tehnice_minime"]["found"] is True
        assert sections["cap_3_personal_cheie"]["found"] is True
        assert sections["cap_4_garantii_penalitati"]["found"] is True
        # Offsets should be strictly increasing since the headers appear in
        # chapter order in this fixture.
        offsets = [sections[k]["match_offset"] for k in sections]
        assert offsets == sorted(offsets)

    def test_ocr_noise_variants_still_match(self):
        # "1" misread as "l", missing spaces around punctuation, and a
        # legacy-cedilla diacritic encoding (ş/ţ instead of ș/ț) — all
        # things real Tesseract output on a noisy scan actually produces.
        text = (
            "CAP.l.OBIECTUL CONTRACTULUI blah\n"
            "cap2 cerintele tehnice minime\n"
            "CAP 3   PERSONALUL CHEIE\n"
            "cap.4:garantiile si penalitatile\n"
        )
        sections = ocr_engine.detect_legal_sections(text)
        assert sections["cap_1_obiectul_contractului"]["found"] is True
        assert sections["cap_2_cerinte_tehnice_minime"]["found"] is True
        assert sections["cap_3_personal_cheie"]["found"] is True
        assert sections["cap_4_garantii_penalitati"]["found"] is True

    def test_absent_headers_report_not_found(self):
        sections = ocr_engine.detect_legal_sections("Un text complet neutru, fara nicio referinta legala.")
        assert all(not s["found"] for s in sections.values())

    def test_empty_text_does_not_raise(self):
        sections = ocr_engine.detect_legal_sections("")
        assert all(not s["found"] for s in sections.values())


class TestTableHeuristic:
    def test_wide_gap_lines_become_rows(self):
        text = "Nr.crt  Denumire lucrare  Valoare RON\n1  Terasamente  150000\n2  Fundatii  320000\n"
        rows = ocr_engine.extract_tables_heuristic(text)
        assert len(rows) == 3
        assert rows[0] == ["Nr.crt", "Denumire lucrare", "Valoare RON"]

    def test_prose_line_without_wide_gaps_is_not_a_row(self):
        rows = ocr_engine.extract_tables_heuristic("Acesta este un paragraf normal de text continuu.")
        assert rows == []


class TestOcrGracefulDegradation:
    """Covers the deployment-constrained path: tesseract/poppler binaries
    absent (true in this sandbox, and true on the current Render deployment
    per workers/__init__.py — confirmed absent here too, but mocked
    explicitly so this test doesn't depend on the sandbox's own state)."""

    def test_check_ocr_binaries_reports_missing(self, monkeypatch):
        monkeypatch.setattr(ocr_engine.shutil, "which", lambda name: None)
        availability = ocr_engine.check_ocr_binaries()
        assert availability == {"tesseract": False, "poppler": False}
        assert ocr_engine.ocr_available() is False

    @pytest.mark.asyncio
    async def test_heavy_pipeline_degrades_cleanly_without_binaries(self, monkeypatch):
        monkeypatch.setattr(ocr_engine.shutil, "which", lambda name: None)
        pdf_bytes = _build_digital_pdf(["irrelevant — never reaches rendering"])

        result = await document_tasks.run_heavy_ocr_pipeline(pdf_bytes)

        assert result["status"] == "failed"
        assert result["ocr_applied"] is False
        assert result["raw_text"] == ""
        assert result["error_message"]  # a specific, honest reason, not silence
        assert "OCR" in result["error_message"]

    @pytest.mark.asyncio
    async def test_render_pdf_to_images_raises_typed_error_without_poppler(self, monkeypatch):
        monkeypatch.setattr(pdf_preprocessor.shutil, "which", lambda name: None)
        with pytest.raises(pdf_preprocessor.PopplerUnavailableError):
            pdf_preprocessor.render_pdf_to_images(b"irrelevant", "/tmp")

    @pytest.mark.skipif(
        not ocr_engine.ocr_available(),
        reason="tesseract/poppler not installed in this sandbox — see workers/__init__.py",
    )
    @pytest.mark.asyncio
    async def test_real_ocr_end_to_end_when_binaries_present(self):
        # Only runs in an environment where someone has actually installed
        # tesseract-ocr(+ron) and poppler-utils — not the case in this
        # sandbox or on the current Render deployment, hence the skipif.
        pdf_bytes = _build_digital_pdf(CAIET_PARAGRAPHS)
        result = await document_tasks.run_heavy_ocr_pipeline(pdf_bytes)
        assert result["ocr_applied"] is True
        assert result["status"] == "done"
        assert len(result["raw_text"]) > 0


class TestPerDocumentTimeout:
    """The 180s default (PER_DOCUMENT_TIMEOUT_SECONDS) would make this test
    itself take 180s to prove — instead this builds a DocumentTaskRunner
    with a much shorter override, matching how the class is designed to be
    constructed (per_document_timeout is a constructor argument specifically
    so this doesn't require monkeypatching a module constant)."""

    @pytest.mark.asyncio
    async def test_timeout_fires_and_records_a_failed_result(self, monkeypatch):
        recorded = {}

        async def fake_mark_processing(doc_id):
            recorded["processing_doc_id"] = doc_id

        async def fake_mark_result(doc_id, **kwargs):
            recorded["result_doc_id"] = doc_id
            recorded["result_kwargs"] = kwargs

        monkeypatch.setattr(document_tasks.document_extractions, "mark_processing", fake_mark_processing)
        monkeypatch.setattr(document_tasks.document_extractions, "mark_result", fake_mark_result)

        async def _slow_pipeline(pdf_bytes, token=None):
            await asyncio.sleep(5)
            return {  # pragma: no cover — should never actually be reached
                "status": "done", "raw_text": "too slow", "tables_json": [],
                "ocr_applied": False, "sections_json": {}, "error_message": None,
            }

        runner = document_tasks.DocumentTaskRunner(per_document_timeout=0.05)
        item = {"doc_id": "doc-timeout-test", "notice_id": None, "filename": "f.pdf", "pdf_bytes": b"x"}

        await runner._execute(item, _slow_pipeline)

        assert recorded["processing_doc_id"] == "doc-timeout-test"
        assert recorded["result_doc_id"] == "doc-timeout-test"
        assert recorded["result_kwargs"]["status"] == "failed"
        assert recorded["result_kwargs"]["ocr_applied"] is False
        assert "depăș" in recorded["result_kwargs"]["error_message"]

    @pytest.mark.asyncio
    async def test_fast_pipeline_well_under_timeout_completes_normally(self, monkeypatch):
        recorded = {}

        async def fake_mark_processing(doc_id):
            pass

        async def fake_mark_result(doc_id, **kwargs):
            recorded["result_kwargs"] = kwargs

        monkeypatch.setattr(document_tasks.document_extractions, "mark_processing", fake_mark_processing)
        monkeypatch.setattr(document_tasks.document_extractions, "mark_result", fake_mark_result)

        pdf_bytes = _build_digital_pdf(CAIET_PARAGRAPHS)
        runner = document_tasks.DocumentTaskRunner(per_document_timeout=30.0)
        item = {"doc_id": "doc-fast-ok", "notice_id": None, "filename": "f.pdf", "pdf_bytes": pdf_bytes}

        await runner._execute(item, document_tasks.run_fast_text_pipeline)

        assert recorded["result_kwargs"]["status"] == "done"
        assert "OBIECTUL CONTRACTULUI" in recorded["result_kwargs"]["raw_text"]


class TestEnqueueRouting:
    """Exercises DocumentTaskRunner.enqueue()'s classify-then-route logic in
    isolation from the consumer loops (start() is never called here), which
    is the same split document_tasks.py's own enqueue_document() /
    get_runner() module functions rely on."""

    @pytest.mark.asyncio
    async def test_digital_pdf_routed_to_fast_text_queue(self):
        runner = document_tasks.DocumentTaskRunner()
        pdf_bytes = _build_digital_pdf(CAIET_PARAGRAPHS)

        route = await runner.enqueue("doc-a", None, "caiet.pdf", pdf_bytes)

        assert route == "fast_text"
        assert runner.fast_text_queue.qsize() == 1
        assert runner.heavy_ocr_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_blank_scanned_pdf_routed_to_heavy_ocr_queue(self):
        runner = document_tasks.DocumentTaskRunner()
        doc = pymupdf.open()
        doc.new_page()
        pdf_bytes = doc.tobytes()
        doc.close()

        route = await runner.enqueue("doc-b", "notice-123", "scan.pdf", pdf_bytes)

        assert route == "heavy_ocr"
        assert runner.heavy_ocr_queue.qsize() == 1
        item = await runner.heavy_ocr_queue.get()
        assert item["doc_id"] == "doc-b"
        assert item["notice_id"] == "notice-123"


@pytest.fixture
def captured_extractions(monkeypatch):
    """Replaces document_extractions' two write calls with in-memory capture.

    Every test below that goes through DocumentTaskRunner needs this: the real
    functions degrade to a no-op without DATABASE_URL, which would make an
    assertion about what was *recorded* vacuously pass.
    """
    recorded = {"processing": [], "results": {}}

    async def fake_mark_processing(doc_id):
        recorded["processing"].append(doc_id)

    async def fake_mark_result(doc_id, **kwargs):
        recorded["results"][doc_id] = kwargs

    monkeypatch.setattr(document_tasks.document_extractions, "mark_processing", fake_mark_processing)
    monkeypatch.setattr(document_tasks.document_extractions, "mark_result", fake_mark_result)
    return recorded


class TestCancellationReachesTheWorkerThread:
    """asyncio.wait_for cancels the *await*, never the OS thread behind
    run_in_executor. Before the CancellationToken, a timed-out document was
    marked failed while its thread kept rendering pages — holding the full PDF
    bytes and a pool slot for however long the real work took. These tests pin
    the half that was missing: that the timeout actually reaches the thread.
    """

    @pytest.mark.asyncio
    async def test_timeout_sets_the_token_the_worker_thread_polls(self, captured_extractions):
        observed = {}
        stopped = threading.Event()

        async def _pipeline(pdf_bytes, token=None):
            # Stands in for the real thread-bound stages: a synchronous loop
            # that only stops because it polls the token.
            def _work():
                for _ in range(2000):
                    if token.cancelled:
                        observed["saw_cancel"] = True
                        stopped.set()
                        return "stopped"
                    time.sleep(0.005)
                observed["saw_cancel"] = False
                stopped.set()
                return "ran to completion"

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _work)
            return {  # pragma: no cover — the timeout fires long before this
                "status": "done", "raw_text": "", "tables_json": [],
                "ocr_applied": False, "sections_json": {}, "error_message": None,
            }

        runner = document_tasks.DocumentTaskRunner(per_document_timeout=0.1)
        item = {"doc_id": "doc-cancel", "notice_id": None, "filename": "f.pdf", "pdf_bytes": b"x", "size": 1}

        await runner._execute(item, _pipeline)

        assert captured_extractions["results"]["doc-cancel"]["status"] == "failed"
        # The thread must actually notice, and quickly — a 10s budget on work
        # that would otherwise run for another 10s.
        assert stopped.wait(timeout=10.0), "worker thread never stopped after the timeout"
        assert observed["saw_cancel"] is True

    def test_fast_extraction_checks_the_token_between_pages(self):
        """The fast path's whole parse is one executor call, so its only
        cancellation points are the ones inside it."""
        pdf_bytes = _build_digital_pdf(CAIET_PARAGRAPHS)
        token = document_tasks.CancellationToken()
        token.cancel()
        with pytest.raises(document_tasks.DocumentCancelled):
            document_tasks._extract_digital_text_and_tables(pdf_bytes, token)

    def test_uncancelled_token_extracts_normally(self):
        pdf_bytes = _build_digital_pdf(CAIET_PARAGRAPHS)
        text, _tables = document_tasks._extract_digital_text_and_tables(
            pdf_bytes, document_tasks.CancellationToken()
        )
        assert "OBIECTUL CONTRACTULUI" in text

    @pytest.mark.asyncio
    async def test_shutdown_cancellation_is_not_recorded_as_a_document_failure(
        self, captured_extractions
    ):
        """A CancelledError from stop() means the process is going away, not
        that the document is bad — it must propagate rather than be swallowed
        into a 'failed' row that blames the user's file."""

        async def _pipeline(pdf_bytes, token=None):
            await asyncio.sleep(30)

        runner = document_tasks.DocumentTaskRunner(per_document_timeout=30.0)
        item = {"doc_id": "doc-shutdown", "notice_id": None, "filename": "f.pdf", "pdf_bytes": b"x", "size": 1}

        task = asyncio.ensure_future(runner._execute(item, _pipeline))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert "doc-shutdown" not in captured_extractions["results"]


class TestResidentByteAdmissionControl:
    """The queues hold whole PDFs in memory. A count-bounded queue does not
    bound that — 64 slots x 40MB is 2.5GB on a 512MB box — so admission is
    budgeted in bytes, and a refusal is *recorded* rather than dropped."""

    @pytest.mark.asyncio
    async def test_oversized_document_is_rejected_with_a_readable_reason(self, captured_extractions):
        runner = document_tasks.DocumentTaskRunner(max_document_bytes=1024)

        route = await runner.enqueue("doc-big", None, "huge.pdf", b"x" * 4096)

        assert route == "rejected"
        assert runner.fast_text_queue.qsize() == 0
        assert runner.heavy_ocr_queue.qsize() == 0
        result = captured_extractions["results"]["doc-big"]
        assert result["status"] == "failed"
        assert "depășește" in result["error_message"]

    @pytest.mark.asyncio
    async def test_budget_exhaustion_rejects_rather_than_queueing_unbounded(self, captured_extractions):
        pdf_bytes = _build_digital_pdf(CAIET_PARAGRAPHS)
        # Room for exactly one copy of this document.
        runner = document_tasks.DocumentTaskRunner(max_resident_bytes=len(pdf_bytes))

        first = await runner.enqueue("doc-1", None, "a.pdf", pdf_bytes)
        second = await runner.enqueue("doc-2", None, "b.pdf", pdf_bytes)

        assert first == "fast_text"
        assert second == "rejected"
        assert runner.fast_text_queue.qsize() == 1
        assert "plină" in captured_extractions["results"]["doc-2"]["error_message"]

    @pytest.mark.asyncio
    async def test_finishing_a_document_returns_its_budget(self, captured_extractions):
        pdf_bytes = _build_digital_pdf(CAIET_PARAGRAPHS)
        runner = document_tasks.DocumentTaskRunner(max_resident_bytes=len(pdf_bytes))

        assert await runner.enqueue("doc-1", None, "a.pdf", pdf_bytes) == "fast_text"
        assert runner.stats()["resident_bytes"] == len(pdf_bytes)

        item = await runner.fast_text_queue.get()
        runner._finish(item, runner.fast_text_queue)

        assert runner.stats()["resident_bytes"] == 0
        # The bytes themselves are dropped, not just the accounting — the item
        # dict outlives the task frame that referenced it.
        assert "pdf_bytes" not in item
        assert await runner.enqueue("doc-3", None, "c.pdf", pdf_bytes) == "fast_text"

    @pytest.mark.asyncio
    async def test_a_flood_of_tiny_documents_still_hits_the_item_cap(self, captured_extractions):
        pdf_bytes = _build_digital_pdf(["x"])
        runner = document_tasks.DocumentTaskRunner(queue_maxsize=2, max_resident_bytes=10 * 1024 * 1024)

        routes = [await runner.enqueue(f"doc-{i}", None, "a.pdf", pdf_bytes) for i in range(3)]

        # A one-line PDF falls under MIN_CHARS_PER_PAGE_FOR_DIGITAL and so
        # routes to heavy_ocr; which queue it lands on is beside the point
        # here — that the third is refused once the cap is reached is not.
        assert routes[0] == routes[1] and routes[0] != "rejected"
        assert routes[2] == "rejected"
        # A rejection for the item cap must not leak the byte reservation it
        # took before discovering the queue was full.
        assert runner.stats()["resident_bytes"] == 2 * len(pdf_bytes)


class TestDedicatedThreadPool:
    """Document work must not run on the default executor.
    scrapers/matrix/infra_scrapers.py offloads CNAIR's 278-page PDF parse onto
    that pool specifically so orchestrator.run_tick's TICK_DEADLINE_SECONDS
    stays enforceable; a few wedged OCR threads there would stall ingestion,
    which is the exact starvation the offload exists to prevent."""

    def test_pool_is_separate_from_the_default_executor(self):
        pool = document_tasks._pool()
        assert pool is not None
        assert pool._max_workers == document_tasks.DOCUMENT_POOL_THREADS
        names = []
        list(pool.map(lambda _: names.append(threading.current_thread().name), range(4)))
        assert all(n.startswith("docworker") for n in names), names

    def test_no_stage_falls_back_to_the_default_executor(self):
        """Owning a pool is not the same as using it. `run_in_executor(None,
        ...)` anywhere in this module silently puts that stage back on the
        shared default executor, which is the starvation this whole change
        exists to prevent — and nothing about the resulting behaviour would
        look wrong until ingestion quietly stopped.

        Checked over the AST rather than the source text: this module's own
        docstring discusses `run_in_executor(None, ...)` by name, and a
        substring scan flags that prose as a violation.
        """
        tree = ast.parse(inspect.getsource(document_tasks))
        offenders = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run_in_executor"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value is None
            ):
                offenders.append(node.lineno)
        assert not offenders, f"run_in_executor(None, ...) at lines {offenders}"

    def test_pool_is_large_enough_for_both_concurrency_limits(self):
        # Otherwise a document holding a semaphore waits on a thread occupied
        # by one that hasn't acquired it — a self-inflicted stall.
        assert document_tasks.DOCUMENT_POOL_THREADS >= (
            document_tasks.HEAVY_OCR_MAX_CONCURRENT + document_tasks.FAST_TEXT_MAX_CONCURRENT
        )

    @pytest.mark.asyncio
    async def test_fast_path_concurrency_is_bounded(self, captured_extractions):
        peak = {"now": 0, "max": 0}

        async def _pipeline(pdf_bytes, token=None):
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
            await asyncio.sleep(0.05)
            peak["now"] -= 1
            return {
                "status": "done", "raw_text": "", "tables_json": [],
                "ocr_applied": False, "sections_json": {}, "error_message": None,
            }

        runner = document_tasks.DocumentTaskRunner(fast_text_max_concurrent=2)
        items = [
            {"doc_id": f"d{i}", "notice_id": None, "filename": "f.pdf", "pdf_bytes": b"x", "size": 1}
            for i in range(6)
        ]
        for item in items:
            runner.fast_text_queue.put_nowait(item)

        await asyncio.gather(*(runner._run_fast(item) for item in items))

        assert peak["max"] <= 2, f"fast path ran {peak['max']} documents at once"


class TestPageBatching:
    """The heavy path used to render the whole document in one poppler call:
    150 full-resolution rasters on disk at once, and one opaque multi-minute
    stretch with no point at which a timeout could act."""

    @pytest.mark.asyncio
    async def test_renders_in_batches_and_frees_each_before_the_next(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ocr_engine, "check_ocr_binaries", lambda: {"tesseract": True, "poppler": True})
        monkeypatch.setattr(document_tasks, "_page_count", lambda b: 25)
        monkeypatch.setattr(document_tasks, "OCR_PAGE_BATCH", 10)

        batches = []
        live_files = {"max": 0}

        def fake_render(pdf_bytes, output_dir, dpi=300, max_pages=150, first_page=1, last_page=None):
            batches.append((first_page, last_page))
            paths = []
            for page in range(first_page, (last_page or first_page) + 1):
                path = os.path.join(output_dir, f"p{page}.png")
                with open(path, "wb") as fh:
                    fh.write(b"raster")
                paths.append(path)
            live_files["max"] = max(live_files["max"], len(os.listdir(output_dir)))
            return paths

        monkeypatch.setattr(pdf_preprocessor, "render_pdf_to_images", fake_render)
        monkeypatch.setattr(document_tasks, "_ocr_one_page", lambda path, token: f"text from {path}")

        result = await document_tasks.run_heavy_ocr_pipeline(b"%PDF-fake")

        assert result["status"] == "done"
        assert result["ocr_applied"] is True
        assert batches == [(1, 10), (11, 20), (21, 25)]
        # Peak on-disk rasters is one batch, not the whole document.
        assert live_files["max"] <= 10, live_files["max"]

    @pytest.mark.asyncio
    async def test_document_beyond_the_page_cap_is_truncated_and_says_so(self, monkeypatch):
        monkeypatch.setattr(ocr_engine, "check_ocr_binaries", lambda: {"tesseract": True, "poppler": True})
        monkeypatch.setattr(document_tasks, "_page_count", lambda b: 400)
        monkeypatch.setattr(document_tasks, "MAX_DOCUMENT_PAGES", 20)
        monkeypatch.setattr(document_tasks, "OCR_PAGE_BATCH", 10)
        monkeypatch.setattr(
            pdf_preprocessor,
            "render_pdf_to_images",
            lambda *a, **k: [],
        )

        result = await document_tasks.run_heavy_ocr_pipeline(b"%PDF-fake")

        assert result["status"] == "done"
        # Truncation is stated, not silent — a partial scan reported as a
        # complete one is exactly the kind of quiet wrongness this codebase
        # refuses elsewhere.
        assert "trunchiat" in result["error_message"]
        assert "20" in result["error_message"] and "400" in result["error_message"]

    @pytest.mark.asyncio
    async def test_unreadable_pdf_fails_before_rendering(self, monkeypatch):
        monkeypatch.setattr(ocr_engine, "check_ocr_binaries", lambda: {"tesseract": True, "poppler": True})

        result = await document_tasks.run_heavy_ocr_pipeline(b"not a pdf at all")

        assert result["status"] == "failed"
        assert result["ocr_applied"] is False
        assert "0 pagini" in result["error_message"]


class TestRunnerLifecycle:
    """Drives the real consumer loops rather than calling _run_fast/_run_heavy
    by hand, since those resolve their pipeline from the module namespace —
    which is also why the stub is installed with monkeypatch.setattr on the
    module rather than passed in."""

    @pytest.mark.asyncio
    async def test_in_flight_tasks_are_strongly_referenced(self, captured_extractions, monkeypatch):
        """asyncio holds only a weak reference to a running task; one whose
        sole reference was the consumer loop's local could be collected
        mid-document, leaving the row at 'processing' forever with nothing
        having raised."""
        started = asyncio.Event()

        async def _pipeline(pdf_bytes, token=None):
            started.set()
            await asyncio.sleep(0.2)
            return {
                "status": "done", "raw_text": "ok", "tables_json": [],
                "ocr_applied": False, "sections_json": {}, "error_message": None,
            }

        monkeypatch.setattr(document_tasks, "run_fast_text_pipeline", _pipeline)

        runner = document_tasks.DocumentTaskRunner()
        runner.start()
        pdf_bytes = _build_digital_pdf(CAIET_PARAGRAPHS)
        assert await runner.enqueue("d1", None, "f.pdf", pdf_bytes) == "fast_text"

        await asyncio.wait_for(started.wait(), timeout=5)
        gc.collect()  # the consumer's local is long gone by now
        assert len(runner._inflight) == 1
        assert runner.stats()["in_flight"] == 1

        await asyncio.gather(*runner._inflight)
        assert runner._inflight == set()
        assert captured_extractions["results"]["d1"]["status"] == "done"
        await runner.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_consumers_and_in_flight_work(self, captured_extractions, monkeypatch):
        entered = asyncio.Event()

        async def _pipeline(pdf_bytes, token=None):
            entered.set()
            await asyncio.sleep(30)

        monkeypatch.setattr(document_tasks, "run_heavy_ocr_pipeline", _pipeline)

        doc = pymupdf.open()
        doc.new_page()
        scanned = doc.tobytes()
        doc.close()

        runner = document_tasks.DocumentTaskRunner()
        runner.start()
        assert await runner.enqueue("d1", None, "scan.pdf", scanned) == "heavy_ocr"
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert runner.stats()["in_flight"] == 1
        assert runner.stats()["resident_bytes"] == len(scanned)

        await runner.stop()

        assert runner._inflight == set()
        assert runner._consumer_tasks == []
        assert runner.stats()["started"] is False
        assert runner.stats()["resident_bytes"] == 0

    def test_stats_leaks_no_document_identity(self):
        # /api/v1/system/status is public, same reasoning as the rate-limit
        # block already there exposing a count and never an address.
        stats = document_tasks.DocumentTaskRunner().stats()
        assert set(stats) == {
            "fast_text_queued", "heavy_ocr_queued", "in_flight",
            "resident_bytes", "resident_bytes_limit", "pool_threads", "started",
        }
        assert all(isinstance(v, (int, bool)) for v in stats.values())
