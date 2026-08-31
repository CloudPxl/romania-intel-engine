-- ====================================================================
-- SEAP/e-licitatie NORMALIZED PROCUREMENT NOTICES
-- Apply by hand via the Supabase SQL editor (same convention as
-- pipeline_schema.sql / scraper_matrix_schema.sql).
--
-- This is additive to, not a replacement for, `opportunities`
-- (scraper_matrix_schema.sql): every scraper still writes its lean
-- RawInstitutionalSignal there for the tenant feed/matching/alerts. This
-- table only exists for SEAP sources rich enough to fill it — see
-- procurement_notices.py for the Pydantic schema and
-- scrapers/matrix/direct_acquisition_scraper.py for which of the five
-- SEAP notice types are actually live as of this migration (DA and CAN;
-- CN/SC's real public endpoint was not located — search that file's
-- docstring before assuming a name for it in a future pass).
-- ====================================================================

CREATE TABLE IF NOT EXISTS procurement_notices (
    notice_id TEXT NOT NULL,
    notice_type TEXT NOT NULL CHECK (notice_type IN ('CN', 'SC', 'DA', 'CAN', 'MC')),
    fingerprint TEXT NOT NULL,
    caen_codes TEXT[] DEFAULT '{}',
    cpv_code TEXT,
    contracting_authority JSONB NOT NULL DEFAULT '{}'::jsonb,
    financial JSONB NOT NULL DEFAULT '{}'::jsonb,
    award_details JSONB,
    timeline JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_url TEXT,
    first_seen_at TIMESTAMPTZ DEFAULT now(),
    last_seen_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (notice_id, notice_type)
);

CREATE INDEX IF NOT EXISTS idx_procurement_notices_type ON procurement_notices(notice_type);
CREATE INDEX IF NOT EXISTS idx_procurement_notices_fingerprint ON procurement_notices(fingerprint);
CREATE INDEX IF NOT EXISTS idx_procurement_notices_last_seen ON procurement_notices(last_seen_at DESC);

-- One row per notice type — tracks incremental sync progress so a tick
-- doesn't have to re-walk the full remote list from page 0 every time.
-- last_item_id is advisory (the remote list's sort order isn't verified
-- to be stable — see the scraper's module docstring), not a correctness
-- guarantee: db-level (notice_id, notice_type) UPSERT is what actually
-- prevents duplicates regardless of how much gets re-scanned.
CREATE TABLE IF NOT EXISTS seap_ingest_state (
    notice_type TEXT PRIMARY KEY CHECK (notice_type IN ('CN', 'SC', 'DA', 'CAN', 'MC')),
    last_synced_date TIMESTAMPTZ,
    last_item_id TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);
