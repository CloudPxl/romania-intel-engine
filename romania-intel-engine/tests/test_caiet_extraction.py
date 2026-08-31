"""Tests for addons/caiet_analyzer.py's text extraction boundary.

These guard one specific failure mode that is worse than a crash: the
analyzer used to fall back to `file_bytes.decode("utf-8", errors="ignore")`
whenever a PDF or DOCX failed to parse, feeding near-garbage into
analyze_specification_text(). That scan then found none of its restrictive
patterns and returned "Scazut (Specificatii Deschise)" with no red flags —
telling a bidder a document had been checked and was clean when it had
never actually been read.

The distinction these tests pin down is three-way, not two-way:
  - unparseable file      -> TextExtractionError (never a "clean" verdict)
  - parsed, no text layer -> "" (a scanned doc, routed to the OCR pipeline)
  - parsed with text      -> normal analysis, unchanged

Test PDFs are built on the fly with pymupdf rather than checked in as binary
fixtures, matching tests/test_document_worker.py's convention.

Run with `pytest` from romania-intel-engine/.
"""

import io

import docx
import pymupdf
import pytest

from addons.caiet_analyzer import CaietDeSarciniAnalyzer, TextExtractionError


def _pdf_with_text(*lines: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + i * 30), line)
    data = doc.tobytes()
    doc.close()
    return data


def _pdf_without_text_layer() -> bytes:
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


class TestUnparseableFilesRaise:
    """The core regression: a file we cannot read must never reach the
    analyzer as salvaged binary noise."""

    def test_corrupt_pdf_raises_instead_of_returning_garbage(self):
        corrupt = b"%PDF-1.4\n" + bytes(range(256)) * 40
        with pytest.raises(TextExtractionError):
            CaietDeSarciniAnalyzer.extract_text_from_file(corrupt, "caiet.pdf")

    def test_corrupt_docx_raises_instead_of_returning_garbage(self):
        with pytest.raises(TextExtractionError):
            CaietDeSarciniAnalyzer.extract_text_from_file(b"PK\x03\x04not-a-docx", "caiet.docx")

    def test_corrupt_pdf_never_yields_a_clean_verdict(self):
        """The actual user-facing harm, stated directly: whatever happens on a
        corrupt upload, it must not be an all-clear risk assessment."""
        corrupt = b"%PDF-1.4\n" + bytes(range(256)) * 40
        try:
            text = CaietDeSarciniAnalyzer.extract_text_from_file(corrupt, "caiet.pdf")
        except TextExtractionError:
            return  # correct behaviour
        result = CaietDeSarciniAnalyzer.analyze_specification_text(text, "Test")
        pytest.fail(
            "Corrupt PDF was analyzed instead of rejected, reporting "
            f"{result['bias_risk_level']!r} on a document that was never read."
        )


class TestParsedButEmptyIsNotAnError:
    def test_pdf_without_text_layer_returns_empty_string(self):
        """A scanned document parses fine but has no text. That is the async
        OCR pipeline's job, not an extraction failure — so it must come back
        as "" rather than raising."""
        assert CaietDeSarciniAnalyzer.extract_text_from_file(_pdf_without_text_layer(), "scan.pdf") == ""


class TestReadableFilesStillWork:
    def test_pdf_with_text_is_extracted_and_analyzed(self):
        data = _pdf_with_text(
            "Se solicita autorizatie de producator si experienta similara.",
            "Livrare in maxim 5 zile.",
        )
        text = CaietDeSarciniAnalyzer.extract_text_from_file(data, "real.pdf")
        assert "autorizatie de producator" in text

        result = CaietDeSarciniAnalyzer.analyze_specification_text(text, "Test")
        flagged = {flag["pattern"] for flag in result["detected_red_flags"]}
        assert "autorizatie de producator" in flagged
        assert "experienta similara" in flagged

    def test_multi_page_pdf_keeps_every_page(self):
        doc = pymupdf.open()
        for i in range(3):
            page = doc.new_page()
            page.insert_text((72, 100), f"Pagina {i + 1} continut tehnic.")
        data = doc.tobytes()
        doc.close()

        text = CaietDeSarciniAnalyzer.extract_text_from_file(data, "multi.pdf")
        for i in range(3):
            assert f"Pagina {i + 1}" in text

    def test_docx_is_extracted(self):
        document = docx.Document()
        document.add_paragraph("Cerinta de marca fara sau echivalent.")
        buffer = io.BytesIO()
        document.save(buffer)

        text = CaietDeSarciniAnalyzer.extract_text_from_file(buffer.getvalue(), "real.docx")
        assert "Cerinta de marca" in text

    def test_plain_text_still_decodes_leniently(self):
        """errors="ignore" stays legitimate for a .txt: the bytes really are
        text, so a few undecodable characters shouldn't fail the file."""
        raw = "Cerinta de marca.".encode() + b"\xff\xfe"
        assert "Cerinta de marca." in CaietDeSarciniAnalyzer.extract_text_from_file(raw, "spec.txt")
