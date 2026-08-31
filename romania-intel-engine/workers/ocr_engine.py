"""pytesseract wrapper (Romanian language pack) plus the Cap.1-4 Romanian
legal-section header detection and a best-effort OCR-text table heuristic.

Binary-availability detection lives here rather than being assumed: see
workers/__init__.py's module docstring for why tesseract-ocr and its
tesseract-ocr-ron language pack are not installed on the current Render
deployment.
"""

import logging
import re
import shutil
from typing import Any, Dict, List, Optional

from text_utils import fold

logger = logging.getLogger("OcrEngine")

TESSERACT_LANG = "ron"


def check_ocr_binaries() -> Dict[str, bool]:
    """Runtime detection, not a static assumption — Render's `env: python`
    buildCommand has no apt-get step, so tesseract and poppler are absent in
    production today, but this is written so it transparently starts working
    the moment someone changes render.yaml's build environment, with no code
    change needed here."""
    return {
        "tesseract": shutil.which("tesseract") is not None,
        "poppler": shutil.which("pdftoppm") is not None or shutil.which("pdftocairo") is not None,
    }


def ocr_available() -> bool:
    availability = check_ocr_binaries()
    return availability["tesseract"] and availability["poppler"]


def ocr_image(image, lang: str = TESSERACT_LANG) -> Optional[str]:
    """Runs pytesseract against one preprocessed image (a numpy array from
    pdf_preprocessor.preprocess_image_for_ocr, or any PIL-compatible image).
    Returns None — never raises — when the tesseract binary or the
    requested language pack is missing, so a caller can log and degrade
    honestly instead of crashing the worker. Only meant to be called after
    check_ocr_binaries() has already confirmed tesseract is present; this
    still guards against the "binary present but tesseract-ocr-ron pack
    missing" case, which shutil.which() cannot detect on its own.
    """
    import pytesseract

    try:
        return pytesseract.image_to_string(image, lang=lang)
    except pytesseract.TesseractNotFoundError:
        logger.error("[OcrEngine] tesseract binary not found on PATH.")
        return None
    except Exception as e:
        # Covers, among other things, "Failed loading language 'ron'" when
        # the binary exists but the tesseract-ocr-ron data file doesn't —
        # a real, distinct failure mode from a missing binary entirely.
        logger.error(f"[OcrEngine] OCR failed ({type(e).__name__}): {e}")
        return None


# ---------------------------------------------------------------------------
# Cap. 1-4 Romanian legal-section header detection.
#
# Matching runs against text_utils.fold()'d text (lowercase, diacritics
# stripped) so "Cerințe" and "cerinte" compare equal, same reasoning as
# addons/caiet_analyzer.py's RESTRICTIVE_PATTERNS. Patterns additionally
# tolerate common OCR noise:
#   - the chapter number is matched as a character class ([1il]) for "1"
#     specifically, since Tesseract frequently confuses a slab-serif "1"
#     with "l"/"I" at low scan resolution — 2/3/4 don't need this, they are
#     rarely misread as a completely different recognizable character;
#   - punctuation/spacing between "cap" and the number, and between the
#     number and the title words, is optional and loosely bounded rather
#     than a fixed literal, since OCR drops or duplicates spaces and
#     periods unpredictably;
#   - title wording is matched on word stems (e.g. "cerint\w*",
#     "tehnic\w*") so inflected forms ("cerințele", "cerință") and small
#     misreads of a trailing letter still match.
# This is inherently best-effort, not a guarantee — a badly enough garbled
# scan can still miss a header, which is why detect_legal_sections reports
# found=False per section rather than failing the whole document.
# ---------------------------------------------------------------------------

_SECTION_DEFINITIONS = [
    (
        "cap_1_obiectul_contractului",
        "Cap. 1 - Obiectul Contractului",
        re.compile(r"cap\.?\s*[1il]\b[\s.:\-–—]{0,10}obiectul?\s+contract\w*"),
    ),
    (
        "cap_2_cerinte_tehnice_minime",
        "Cap. 2 - Cerințe Tehnice Minime",
        re.compile(r"cap\.?\s*2\b[\s.:\-–—]{0,10}cerint\w*\s+tehnic\w*\s+minim\w*"),
    ),
    (
        "cap_3_personal_cheie",
        "Cap. 3 - Personal Cheie",
        re.compile(r"cap\.?\s*3\b[\s.:\-–—]{0,10}personal\w*\s+cheie\w*"),
    ),
    (
        "cap_4_garantii_penalitati",
        "Cap. 4 - Garanții și Penalități",
        re.compile(r"cap\.?\s*4\b[\s.:\-–—]{0,10}garant\w*\s+(?:si\s+)?penalit\w*"),
    ),
]


def detect_legal_sections(text: str) -> Dict[str, Dict[str, Any]]:
    """Scans `text` (raw extracted or OCR'd) for the four standard Romanian
    caiet de sarcini chapter headers. Returns one entry per section keyed by
    a stable id, each reporting whether it was found and, if so, the
    character offset of the match *in the folded text* (text_utils.fold()
    can shift offsets slightly relative to the original string when it
    strips a combining mark from an accented character outside the explicit
    Romanian map) — good enough to say "chapter 2 appears after chapter 1"
    or to sanity-check ordering, not meant as an exact byte offset into the
    original upload.
    """
    folded = fold(text or "")
    results: Dict[str, Dict[str, Any]] = {}
    for key, label, pattern in _SECTION_DEFINITIONS:
        match = pattern.search(folded)
        results[key] = {
            "label": label,
            "found": bool(match),
            "match_offset": match.start() if match else None,
        }
    return results


def extract_tables_heuristic(text: str) -> List[List[str]]:
    """Best-effort tabular extraction for OCR'd text (Deviz General / Liste
    Cantități Lucrări / Criterii de Calificare layouts).

    This is meaningfully lower-fidelity than the digital-text path in
    scrapers/pdf_table_extractor.py: pdfplumber's table extraction there
    detects actual PDF grid/ruling lines, whereas Tesseract's plain-text
    output preserves no layout structure at all — only whitespace. This
    heuristic treats any line with two or more runs of 2+ spaces as a
    candidate table row (common in these documents, whose columns are wide
    enough that OCR usually keeps the visual gap between them intact) and
    splits on those gaps. It will both miss real rows (misaligned OCR
    output) and occasionally split a normal sentence that happens to have a
    wide gap in it. Treat this as a hint for a human reviewer to jump to the
    right page, not as a source of truth for financial figures — unlike the
    digital-text path, which is a trustworthy machine-readable table.
    """
    rows: List[List[str]] = []
    for line in (text or "").splitlines():
        cells = [c for c in re.split(r"\s{2,}", line.strip()) if c]
        if len(cells) >= 3:
            rows.append(cells)
    return rows
