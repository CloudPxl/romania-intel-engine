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

import asyncio
import shutil

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

        async def _slow_pipeline(pdf_bytes):
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
