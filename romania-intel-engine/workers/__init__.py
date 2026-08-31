"""In-process asyncio document-ingestion workers for heavy PDF attachments
(scanned HCL municipal budget annexes, CNAIR technical annexes, blueprints)
that are too slow or too large to parse inline inside an FastAPI request
handler.

No Celery. The original ask for this feature explicitly offered "celery_app.py
(or asyncio background task runner)" as alternatives. This app deploys on
Render's free tier as a single `env: python` web service (render.yaml:
`buildCommand: pip install -r requirements.txt`, one service, no Redis/broker,
no second worker dyno) — introducing Celery would require a message broker
and a separately-deployed worker process that don't exist and can't be
justified here. Every other async orchestration in this codebase (the
ingestion tick in api.py, scrapers/orchestrator.py's scraper fan-out,
scrapers/matrix/municipal_matrix.py's asyncio.Semaphore-bounded county fan-out)
is already plain asyncio running in-process, so this follows the same shape:
two asyncio.Queue()s (fast_text_queue, heavy_ocr_queue — see
document_tasks.py) consumed by bounded worker-pool coroutines living inside
the same FastAPI process, started once at app startup
(document_tasks.start_workers(), called from api.py's lifespan).

Real, but currently deployment-constrained, OCR. workers/ocr_engine.py wraps
pytesseract + workers/pdf_preprocessor.py wraps pdf2image/OpenCV with fully
working image-processing code — not a stub. But pdf2image needs the
poppler-utils system binary (pdftoppm/pdftocairo) and pytesseract needs the
tesseract-ocr binary plus the tesseract-ocr-ron language pack, and Render's
`env: python` buildCommand has no apt-get step, so neither is present on the
current production deployment. Both modules detect binary availability at
runtime (shutil.which, plus catching pdf2image's own "poppler not installed"
exception) and degrade to an honest `ocr_applied: false` + a specific
error_message on the document_extractions row, rather than crashing the
pipeline or fabricating extracted text — the existing pattern for a real gap
in this codebase (see scrapers/matrix/infra_scrapers.py:CnairCfrScraper).
Making OCR actually run in production requires changing render.yaml's build
environment to Docker or an aptfile buildpack, which is a deployment
decision, not something this module assumes for you.

Results (raw text, extracted tables, ocr_applied, detected Cap.1-4 legal
section headers) are persisted to the `document_extractions` Postgres table
(document_extractions.py / document_extractions_schema.sql) via the same
db.with_connection() degrade-to-no-op convention as procurement_notices.py —
a missing/unreachable database means a document silently stays "queued"/
"processing" forever rather than crashing the worker.
"""
