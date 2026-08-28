-- ====================================================================
-- RO-INTEL SCRAPER MATRIX: PERSISTENT INGESTION & ALERTING SCHEMA
-- Apply by hand via the Supabase SQL editor (same convention as
-- multi_tenancy_schema.sql). Superseds cache_engine.py:NewsletterStore's
-- ephemeral JSON file and scrapers/dedup_engine.py's dead scaffolding.
-- ====================================================================

-- 1. Canonical, deduped, persisted opportunity store
CREATE TABLE IF NOT EXISTS opportunities (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    category TEXT NOT NULL,
    sub_category TEXT,
    county TEXT,
    locality TEXT,
    entity_name TEXT NOT NULL,
    project_title TEXT NOT NULL,
    estimated_value_ron NUMERIC DEFAULT 0,
    caen_codes TEXT[] DEFAULT '{}',
    cpv_code TEXT,
    published_date DATE,
    action_deadline DATE,
    raw_description TEXT,
    executive_summary TEXT,
    sales_pitch_angle TEXT,
    funding_source TEXT,
    opportunity_score NUMERIC,
    source_url TEXT,
    document_url TEXT,
    metadata JSONB DEFAULT '{}',
    first_seen_at TIMESTAMPTZ DEFAULT now(),
    last_seen_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_opportunities_category ON opportunities(category);
CREATE INDEX IF NOT EXISTS idx_opportunities_county ON opportunities(county);
CREATE INDEX IF NOT EXISTS idx_opportunities_last_seen ON opportunities(last_seen_at DESC);

-- 2. Per-source polling cadence, staleness, and circuit-breaker state
CREATE TABLE IF NOT EXISTS source_run_log (
    source_name TEXT PRIMARY KEY,
    poll_interval_minutes INT NOT NULL DEFAULT 360,
    last_run_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_error TEXT,
    consecutive_failures INT DEFAULT 0,
    circuit_state TEXT DEFAULT 'closed' CHECK (circuit_state IN ('closed', 'open', 'half_open')),
    circuit_opened_at TIMESTAMPTZ,
    records_last_run INT DEFAULT 0
);

-- 3. Idempotent per-tenant, per-channel alert dispatch log
CREATE TABLE IF NOT EXISTS tenant_alert_dispatch_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES opportunities(source_id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('email', 'telegram')),
    dispatched_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (tenant_id, source_id, channel)
);

-- 4. Whole-tick bookkeeping for the staleness watchdog (/api/v1/system/status)
CREATE TABLE IF NOT EXISTS system_ticks (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    sources_run INT DEFAULT 0,
    new_opportunities INT DEFAULT 0,
    errors INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_system_ticks_completed ON system_ticks(completed_at DESC);
