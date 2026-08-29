import io
import logging
from typing import List, Optional

import pdfplumber

logger = logging.getLogger("PdfTableExtractor")

MAX_PAGES = 150


def extract_table_rows(pdf_bytes: bytes, max_pages: int = MAX_PAGES) -> List[list]:
    """Extracts every detected table row across a PDF's pages. Returns an
    empty list (never raises) for scanned/image-only PDFs — pdfplumber's
    line-based detection needs a real text layer, and a document with none
    (confirmed live against CNAIR's 278-page PAAP export) can't be parsed
    this way without OCR, which is out of scope for a free-tier scraper."""
    rows: List[list] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:max_pages]:
                for table in page.extract_tables():
                    rows.extend(table)
    except Exception as e:
        logger.error(f"[PdfTableExtractor] failed to parse PDF: {e}")
        return []
    return rows


def normalize_cell(value: Optional[str]) -> str:
    return " ".join((value or "").split())


def extract_first_page_text(pdf_bytes: bytes) -> str:
    """Raw (non-tabular) text of page 1 — some real values, like a plan's
    approval date, sit in free-flowing text above/outside the detected
    table's grid lines and never show up as a table cell."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                return ""
            return pdf.pages[0].extract_text() or ""
    except Exception as e:
        logger.error(f"[PdfTableExtractor] failed to extract first-page text: {e}")
        return ""
