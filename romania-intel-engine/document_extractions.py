"""Pydantic model + Postgres persistence for workers/document_tasks.py's
async PDF-ingestion pipeline — the same convention as procurement_notices.py:
a self-contained module owning its own schema file
(document_extractions_schema.sql, applied by hand via the Supabase SQL
editor) and functions that go through db.py's with_connection() so a
missing/unreachable database degrades to a no-op instead of crashing a
background worker task.

Unlike procurement_notices.py's upsert-by-natural-key, a document_extractions
row has a real lifecycle (queued -> processing -> done|failed) driven by
workers/document_tasks.py, so this module exposes lifecycle-transition
functions (mark_processing/mark_result) rather than one upsert.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

import db

logger = logging.getLogger("DocumentExtractions")

Status = str  # "queued" | "processing" | "done" | "failed"


class DocumentExtraction(BaseModel):
    doc_id: str
    notice_id: Optional[str] = None
    original_filename: Optional[str] = None
    raw_text: Optional[str] = None
    tables_json: List[Any] = Field(default_factory=list)
    ocr_applied: bool = False
    sections_json: Dict[str, Any] = Field(default_factory=dict)
    status: Status = "queued"
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


def _to_jsonb(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    d = dict(row)
    # asyncpg hands JSONB columns back as raw JSON text (same convention as
    # db.py's opportunities.metadata — see api.py's `if isinstance(metadata,
    # str): json.loads(...)` handling), so callers of this module get real
    # Python objects rather than having to know that detail themselves.
    for key in ("tables_json", "sections_json"):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except (TypeError, ValueError):
                pass
    for key in ("created_at", "completed_at"):
        if isinstance(d.get(key), datetime):
            d[key] = d[key].isoformat()
    return d


async def create_queued_extraction(doc_id: str, notice_id: Optional[str], filename: str) -> bool:
    """Inserts the initial 'queued' row. Returns True if a database is
    configured and reachable (regardless of whether the row already
    existed — ON CONFLICT DO NOTHING guards against a retried request
    reusing a doc_id), False when there's no persistence to record it in.
    The caller (api.py's upload-caiet-async route) still returns
    {"doc_id", "status": "queued"} to the client either way — a database
    outage shouldn't block accepting the upload, but the GET endpoint will
    honestly 404 for a doc_id that was never actually recorded."""
    async with db.with_connection() as conn:
        if conn is None:
            return False
        await conn.execute(
            """
            INSERT INTO document_extractions (doc_id, notice_id, original_filename, status, created_at)
            VALUES ($1, $2, $3, 'queued', now())
            ON CONFLICT (doc_id) DO NOTHING
            """,
            doc_id, notice_id, filename,
        )
    return True


async def mark_processing(doc_id: str) -> None:
    async with db.with_connection() as conn:
        if conn is None:
            return
        await conn.execute(
            "UPDATE document_extractions SET status = 'processing' WHERE doc_id = $1",
            doc_id,
        )


async def mark_result(
    doc_id: str,
    status: Status,
    raw_text: str,
    tables_json: List[Any],
    ocr_applied: bool,
    sections_json: Dict[str, Any],
    error_message: Optional[str] = None,
) -> None:
    """Terminal transition to 'done' or 'failed', called exactly once per
    document by document_tasks.py's _execute() regardless of which branch
    (success, timeout, exception, missing-OCR-binaries) produced the
    result — every branch there fills in the same five fields so this
    function doesn't need per-failure-mode variants."""
    async with db.with_connection() as conn:
        if conn is None:
            return
        await conn.execute(
            """
            UPDATE document_extractions
            SET status = $2, raw_text = $3, tables_json = $4, ocr_applied = $5,
                sections_json = $6, error_message = $7, completed_at = now()
            WHERE doc_id = $1
            """,
            doc_id, status, raw_text, _to_jsonb(tables_json), ocr_applied,
            _to_jsonb(sections_json), error_message,
        )


async def get_extraction(doc_id: str) -> Optional[Dict[str, Any]]:
    async with db.with_connection() as conn:
        if conn is None:
            return None
        row = await conn.fetchrow("SELECT * FROM document_extractions WHERE doc_id = $1", doc_id)
    return _row_to_dict(row) if row else None


async def get_latest_extraction_for_notice(notice_id: str) -> Optional[Dict[str, Any]]:
    """Used by addons/caiet_analyzer.py's load_extracted_text() when a
    caller has a notice_id but not the specific doc_id — e.g. re-analyzing
    the most recent upload attached to a given opportunity. 'Latest' by
    created_at, not completed_at, so a still-processing row can be reported
    honestly (status != 'done') rather than silently skipped in favor of an
    older completed one."""
    async with db.with_connection() as conn:
        if conn is None:
            return None
        row = await conn.fetchrow(
            "SELECT * FROM document_extractions WHERE notice_id = $1 ORDER BY created_at DESC LIMIT 1",
            notice_id,
        )
    return _row_to_dict(row) if row else None
