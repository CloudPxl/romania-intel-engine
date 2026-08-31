"""Classifies a PDF as digital-text vs scanned/rasterized, and — for the
scanned path only — renders pages to high-DPI images and runs real OpenCV
preprocessing (deskew, denoise, adaptive threshold) to make them legible to
Tesseract.

See workers/__init__.py's module docstring for why the rendering step
(render_pdf_to_images, which needs poppler's pdftoppm/pdftocairo binary)
cannot run on the current Render deployment and how that's detected and
reported rather than assumed.
"""

import io
import logging
import shutil
from typing import Any, Dict, List, Literal

import pdfplumber

logger = logging.getLogger("PdfPreprocessor")

Classification = Literal["digital", "scanned", "empty"]

# Below this many extracted characters per sampled page, a PDF is treated as
# a scan rather than a real text layer. A genuine digital page routinely
# carries hundreds of characters even on a mostly-whitespace cover sheet,
# while a scanned/rasterized page returns either nothing or a handful of
# stray glyphs pdfplumber can pick up from a corrupted/partial text layer —
# this mirrors the live finding already documented in
# scrapers/pdf_table_extractor.py (CNAIR's 278-page PAAP export: real page
# images, page.extract_text() empty on every sampled page).
MIN_CHARS_PER_PAGE_FOR_DIGITAL = 40
SAMPLE_PAGES = 3


def classify_pdf(pdf_bytes: bytes, sample_pages: int = SAMPLE_PAGES) -> Dict[str, Any]:
    """Samples the first `sample_pages` pages via pdfplumber rather than
    walking the whole document — a 150-page scan would otherwise cost
    several seconds in pdfplumber before document_tasks.py even knows which
    queue to route it to. Returns a dict (never raises) so a corrupt upload
    degrades to "scanned" (the safer assumption — OCR degrades further to an
    honest failure, whereas treating a corrupt file as "digital" would just
    hand pdf_table_extractor/fitz an unreadable stream) rather than crashing
    the dispatch path.
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
            if page_count == 0:
                return {"classification": "empty", "page_count": 0, "sampled_pages": 0, "chars_found": 0}
            sample = pdf.pages[:sample_pages]
            chars_found = 0
            for page in sample:
                text = page.extract_text() or ""
                chars_found += len(text.strip())
            avg = chars_found / len(sample)
            classification: Classification = "digital" if avg >= MIN_CHARS_PER_PAGE_FOR_DIGITAL else "scanned"
            return {
                "classification": classification,
                "page_count": page_count,
                "sampled_pages": len(sample),
                "chars_found": chars_found,
            }
    except Exception as e:
        logger.error(f"[PdfPreprocessor] failed to classify PDF, defaulting to 'scanned': {e}")
        return {"classification": "scanned", "page_count": 0, "sampled_pages": 0, "chars_found": 0, "error": str(e)}


class PopplerUnavailableError(RuntimeError):
    """Raised when pdf2image needs poppler's pdftoppm/pdftocairo binaries and
    neither is on PATH. Deliberately its own exception type so callers have
    exactly one thing to catch regardless of which internal pdf2image
    exception class fires for "poppler not installed" — that has changed
    across pdf2image versions, while this wrapper's contract stays stable.
    Expected on the current Render deployment; see workers/__init__.py.
    """


def render_pdf_to_images(pdf_bytes: bytes, output_dir: str, dpi: int = 300, max_pages: int = 150) -> List[str]:
    """Renders a scanned PDF's pages to high-DPI PNG files inside
    `output_dir` and returns their paths in page order.

    The caller is expected to supply `output_dir` from a
    tempfile.TemporaryDirectory() context manager so every rendered image is
    cleaned up automatically even if OCR later raises or times out —
    pdf2image itself has no cleanup hook of its own.
    """
    if shutil.which("pdftoppm") is None and shutil.which("pdftocairo") is None:
        raise PopplerUnavailableError(
            "poppler-utils (pdftoppm/pdftocairo) not found on PATH — pdf2image cannot "
            "render PDF pages to images. Render's `env: python` buildCommand "
            "(pip install -r requirements.txt) has no apt-get step, so this binary is "
            "absent on the current production deployment; fixing it requires switching "
            "render.yaml to a Docker or aptfile-based build environment."
        )

    from pdf2image import convert_from_bytes
    from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError

    try:
        paths = convert_from_bytes(
            pdf_bytes,
            dpi=dpi,
            output_folder=output_dir,
            fmt="png",
            paths_only=True,
            last_page=max_pages,
        )
    except PDFInfoNotInstalledError as e:
        # Defensive: the shutil.which() check above should already have
        # caught this, but pdf2image also shells out to pdfinfo specifically,
        # which is a third poppler binary the which() check doesn't probe.
        raise PopplerUnavailableError(f"poppler binaries not usable ({e})") from e
    except PDFPageCountError as e:
        raise PopplerUnavailableError(f"poppler could not read the PDF's page count ({e})") from e
    return list(paths)


def preprocess_image_for_ocr(image_path: str):
    """Deskews, denoises, and adaptively thresholds one rendered page before
    handing it to Tesseract. Real OpenCV processing, not a stub:

    1. Grayscale + fastNlMeansDenoising to clean up scanner speckle noise,
       which is common on low-resolution municipal scans (HCL budget
       annexes, CNAIR technical annexes photocopied/faxed before scanning).
    2. Otsu threshold + minAreaRect over the ink-pixel mass to estimate the
       page's skew angle, then an affine rotation to correct it — a scanner
       feed a few degrees off is enough to measurably hurt Tesseract's line
       segmentation.
    3. Adaptive (Gaussian, local-neighborhood) thresholding rather than a
       single global threshold, since uneven scan lighting otherwise clips
       one edge of the page to solid black or solid white.

    Returns a binarized numpy array ready for pytesseract.image_to_string.
    Raises ValueError if OpenCV can't decode the file at all (caller treats
    that as a per-document failure, same as any other pipeline exception).
    """
    import cv2

    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"OpenCV could not read rendered page image at {image_path}")

    denoised = cv2.fastNlMeansDenoising(img, h=10)

    _, otsu = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = cv2.findNonZero(otsu)
    angle = 0.0
    if coords is not None and len(coords) > 0:
        rect = cv2.minAreaRect(coords)
        raw_angle = rect[-1]
        # cv2.minAreaRect's angle convention wraps at -90/0 depending on
        # OpenCV version; normalizing to "how far off horizontal" avoids
        # over-rotating a page that's actually close to level.
        angle = -(90 + raw_angle) if raw_angle < -45 else -raw_angle

    if abs(angle) > 0.1:
        h, w = denoised.shape
        matrix = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        denoised = cv2.warpAffine(
            denoised, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )

    thresholded = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15,
    )
    return thresholded
