-- ====================================================================
-- ASYNC DOCUMENT-INGESTION WORKER RESULTS
-- Apply by hand via the Supabase SQL editor (same convention as
-- pipeline_schema.sql / seap_notices_schema.sql / scraper_matrix_schema.sql).
--
-- Written by workers/document_tasks.py via document_extractions.py, which
-- goes through db.py's with_connection() the same way every other table in
-- this codebase does — a missing/unreachable database degrades a document's
-- row to permanently "queued"/"processing" rather than crashing the worker,
-- exactly like db.upsert_opportunity()'s no-op-on-no-database convention.
--
-- notice_id is a soft, FK-by-convention link to opportunities.source_id /
-- procurement_notices.notice_id — deliberately not an enforced foreign key,
-- since a caiet de sarcini can legitimately be uploaded standalone (from
-- /eligibility or /drafting) with no matching notice row at all.
-- ====================================================================

CREATE TABLE IF NOT EXISTS document_extractions (
    doc_id TEXT PRIMARY KEY,
    notice_id TEXT,
    original_filename TEXT,
    raw_text TEXT,
    tables_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ocr_applied BOOLEAN NOT NULL DEFAULT false,
    sections_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'processing', 'done', 'failed')),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_document_extractions_notice_id ON document_extractions(notice_id);
CREATE INDEX IF NOT EXISTS idx_document_extractions_status ON document_extractions(status);
CREATE INDEX IF NOT EXISTS idx_document_extractions_created_at ON document_extractions(created_at DESC);
