-- ====================================================================
-- RO-INTEL — THE DATABASE
--
-- This file is the ENTIRE schema and the single source of truth for it.
-- It replaces the seven files it supersedes (scraper_matrix_schema.sql,
-- pipeline_schema.sql, seap_notices_schema.sql,
-- document_extractions_schema.sql, tenants_schema.sql,
-- multi_tenancy_schema.sql, supabase_security_hardening.sql), which had
-- no documented apply order, defined three tables incompatibly across
-- two files each, and had drifted from the live database badly enough to
-- cause a total login outage (an undeclared UNIQUE index on
-- user_profiles.email that appeared in none of them).
--
-- Apply by hand via the Supabase SQL editor. Safe to re-run: every
-- statement is guarded, and the destructive section at the top is scoped
-- to tables this file then recreates.
--
-- ------------------------------------------------------------------
-- WHAT CHANGED: multi-tenancy is gone.
--
-- The product sells to individuals. A signup used to create a `tenants`
-- row, exactly one `tenant_products` row, and a `user_profiles` row
-- pointing at the tenant — a 1:1:1 chain modelled as a many-to-many,
-- which forced a {tenant_id} path param onto every route and an entire
-- authorization layer to check that the id in the URL was your own.
--
-- `user_profiles` IS the user now. It holds its own matching criteria
-- and alert settings. Nothing addresses anyone else, so that whole
-- authorization layer is deleted rather than rewritten.
-- ====================================================================


-- ====================================================================
-- 0. DESTRUCTIVE — drops the multi-tenant world.
--
-- Deliberate and approved: this is a clean slate, no backfill. Every
-- account re-onboards afterwards. Market data (opportunities, notices,
-- extractions, scraper state) is NOT touched — it is not user-owned and
-- there is no reason to re-scrape it.
-- ====================================================================

DROP TABLE IF EXISTS deal_stage_history CASCADE;
DROP TABLE IF EXISTS product_bidding_deals CASCADE;
DROP TABLE IF EXISTS tenant_alert_dispatch_log CASCADE;
DROP TABLE IF EXISTS tenant_products CASCADE;
DROP TABLE IF EXISTS user_profiles CASCADE;
DROP TABLE IF EXISTS tenants CASCADE;

-- Created by the old supabase_security_hardening.sql and read by no code
-- anywhere in this repo, ever. Confirmed dead by grep across all *.py.
DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS dossier_notes CASCADE;

-- Re-run safety: these are this file's own tables.
DROP TABLE IF EXISTS alert_dispatch_log CASCADE;
DROP TABLE IF EXISTS saved_deals CASCADE;


-- ====================================================================
-- 1. MARKET DATA — not user-owned, preserved across this migration.
-- ====================================================================

-- Every qualified signal the scraper matrix has found. The product
-- itself. Keyed by the scraper's own stable source_id so a re-scrape
-- updates rather than duplicates.
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

-- Pre-folded haystack for the ranked feed: lowercase, Romanian
-- diacritics stripped, title + summary + authority concatenated.
--
-- Folding on WRITE rather than calling unaccent() on read is what keeps
-- SQL and Python agreeing on what "equal" means. text_utils.fold() is
-- already the definition of equality for the Python matcher; db.py fills
-- this column with the exact same function, so a keyword either matches
-- in both places or neither. The alternative — unaccent() in the query —
-- would need the extension, defeat any index, and quietly disagree with
-- fold() on the legacy cedilla forms (ş/ţ) that Romanian institutional
-- sites still emit.
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS search_blob TEXT;

-- Permanently NULL for every row ever written: ai_refinery.refine_signal
-- maps the source's description into `executive_summary` and never emits a
-- `raw_description` key, so db.upsert_opportunity has always bound None
-- here. Nothing reads it except one masked fallback in the matcher
-- (`executive_summary or raw_description`), where the first operand is
-- always truthy. Dropped rather than kept as a documented lie — the
-- descriptive text lives in executive_summary.
ALTER TABLE opportunities DROP COLUMN IF EXISTS raw_description;

-- One-time backfill for rows ingested before the column existed. This is
-- an approximation of text_utils.fold() using translate() — good enough
-- to make existing rows searchable immediately; each row gets the real
-- Python-folded value on its next re-scrape.
-- These are the same four fields the Python matcher reads, in the same
-- order, so SQL ranking and Python alerting search identical text.
UPDATE opportunities
SET search_blob = translate(
    lower(
        coalesce(project_title, '') || ' ' ||
        coalesce(executive_summary, '') || ' ' ||
        coalesce(sub_category, '') || ' ' ||
        coalesce(entity_name, '')
    ),
    'ăĂâÂîÎșȘşŞțȚţŢ',
    'aaaaiisssstttt'
)
WHERE search_blob IS NULL;

CREATE INDEX IF NOT EXISTS idx_opportunities_category ON opportunities(category);
CREATE INDEX IF NOT EXISTS idx_opportunities_county ON opportunities(county);
CREATE INDEX IF NOT EXISTS idx_opportunities_last_seen ON opportunities(last_seen_at DESC);
-- Postgres cannot use a plain btree for a lower() predicate, and both the
-- SQL filters and the Python fallback compare case-insensitively.
CREATE INDEX IF NOT EXISTS idx_opportunities_county_lower ON opportunities(lower(county));
CREATE INDEX IF NOT EXISTS idx_opportunities_category_lower ON opportunities(lower(category));


-- Per-scraper scheduling and circuit-breaker state. One row per source.
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


-- One row per ingestion run. `is_stale` on /api/v1/system/status reads
-- the most recent error-free completed row; without this the watchdog
-- cannot tell a stopped scheduler from a quiet market.
CREATE TABLE IF NOT EXISTS system_ticks (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    sources_run INT DEFAULT 0,
    new_opportunities INT DEFAULT 0,
    errors INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_system_ticks_completed ON system_ticks(completed_at DESC);


-- Richer SEAP notices, additive to `opportunities` rather than replacing
-- it: every scraper still writes its lean signal above. Only sources rich
-- enough to fill these fields land here (today: DA and CAN).
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
    -- The UPSERT conflict target. NOT the fingerprint: a notice's
    -- estimated value legitimately changes as it progresses, so keying
    -- identity on it would insert a new row per revision.
    PRIMARY KEY (notice_id, notice_type)
);

CREATE INDEX IF NOT EXISTS idx_procurement_notices_type ON procurement_notices(notice_type);
CREATE INDEX IF NOT EXISTS idx_procurement_notices_fingerprint ON procurement_notices(fingerprint);
CREATE INDEX IF NOT EXISTS idx_procurement_notices_last_seen ON procurement_notices(last_seen_at DESC);


CREATE TABLE IF NOT EXISTS seap_ingest_state (
    notice_type TEXT PRIMARY KEY CHECK (notice_type IN ('CN', 'SC', 'DA', 'CAN', 'MC')),
    last_synced_date TIMESTAMPTZ,
    last_item_id TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);


-- Async document-worker results. notice_id is a soft link to
-- opportunities.source_id / procurement_notices.notice_id, deliberately
-- NOT an FK: a caiet de sarcini can legitimately be uploaded standalone.
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


-- ====================================================================
-- 2. THE USER — the core entity.
-- ====================================================================

-- One row per person. `id` IS the Supabase Auth user id (the JWT `sub`
-- claim), so this table is 1:1 with auth.users by construction.
--
-- The FK to auth.users with ON DELETE CASCADE does real work: deleting
-- the auth identity removes the profile, and every table below cascades
-- from the profile — so GDPR erasure is one delete rather than a
-- hand-maintained list of cleanup statements that drifts.
--
-- email is UNIQUE, declared here for the first time. That constraint has
-- existed in the live database for weeks while appearing in no file in
-- the repo, and it caused a total login outage on 2026-09-01: one person
-- can hold several Supabase auth identities for one email (Google and
-- magic link mint different auth.users rows), so an INSERT keyed only on
-- id sailed past its conflict handler and hit this index instead.
-- db.upsert_user_profile_email handles that by re-pointing the existing
-- row onto the current auth identity; the constraint is what keeps one
-- human to one row.
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,

    -- Matching criteria. Previously a whole `tenant_products` table that
    -- never held more than one row per user.
    domain TEXT,
    target_counties TEXT[] NOT NULL DEFAULT '{}',
    keywords TEXT[] NOT NULL DEFAULT '{}',
    exclude_keywords TEXT[] NOT NULL DEFAULT '{}',
    min_value_ron NUMERIC NOT NULL DEFAULT 0,

    -- Optional, and only for the bidding entity's own paperwork: the
    -- eligibility check, the generated dossier/clarification letters and
    -- the proforma invoice all name a real legal person. These used to
    -- live on the browser-local "desk" object, which is being deleted —
    -- without them here, three pages silently regress to blank fields on
    -- every load. Nullable because an individual monitoring the market
    -- has no CUI and is not required to invent one.
    company_name TEXT,
    cui TEXT,

    -- Alert delivery. Previously columns on `tenants`.
    alert_email TEXT,
    -- Numeric Telegram chat id, not an @username — the Bot API's
    -- sendMessage will not accept a username.
    telegram_chat_id TEXT,
    min_alert_score NUMERIC NOT NULL DEFAULT 7.5,

    -- NULL until the user completes onboarding. This is what the API
    -- reports as "not provisioned yet" and what makes the frontend show
    -- the onboarding form instead of an empty dashboard.
    onboarded_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- The ranked feed reads every onboarded profile once per tick to match
-- new signals; this keeps that scan off the full table.
CREATE INDEX idx_user_profiles_onboarded ON user_profiles(onboarded_at) WHERE onboarded_at IS NOT NULL;


-- ====================================================================
-- 3. USER-OWNED DATA — all cascade from the profile.
-- ====================================================================

-- Deals the user is working. Renamed from `product_bidding_deals`, and
-- the rename is not cosmetic: the live table of that name was created by
-- the old multi_tenancy_schema.sql with an `id UUID` primary key and no
-- `deal_id` column at all, so pipeline_schema.sql's CREATE TABLE IF NOT
-- EXISTS silently no-opped against it and every write from db.py hit a
-- column that was not there. A new name cannot inherit that shape.
CREATE TABLE saved_deals (
    deal_id TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    opportunity_id TEXT,
    project_title TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'discovery' CHECK (stage IN (
        'discovery',
        'consultation_drafted',
        'consultation_submitted',
        'caiet_sarcini_analysis',
        'offer_prepared',
        'bid_submitted',
        'won',
        'lost'
    )),
    target_margin_pct NUMERIC,
    estimated_value_ron NUMERIC DEFAULT 0,
    proposed_price NUMERIC,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX idx_saved_deals_user ON saved_deals(user_id);


-- Stage transition audit trail. This is what makes the pipeline's
-- time-in-stage and funnel conversion figures real measurements rather
-- than estimates.
CREATE TABLE deal_stage_history (
    id BIGSERIAL PRIMARY KEY,
    deal_id TEXT NOT NULL REFERENCES saved_deals(deal_id) ON DELETE CASCADE,
    from_stage TEXT,
    to_stage TEXT NOT NULL,
    changed_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_stage_history_deal ON deal_stage_history(deal_id);


-- What has already been alerted, so nobody is notified twice about the
-- same opportunity on the same channel. Renamed from
-- tenant_alert_dispatch_log.
CREATE TABLE alert_dispatch_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES opportunities(source_id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('email', 'telegram')),
    dispatched_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, source_id, channel)
);


-- ====================================================================
-- 4. ROW LEVEL SECURITY
--
-- READ THIS BEFORE TRUSTING IT.
--
-- These policies are correct, but they are NOT the security boundary
-- today and must not be mistaken for one. The API connects to Postgres
-- as the `postgres` owner over DATABASE_URL. There is no JWT in that
-- session, so auth.uid() is NULL, and a table's owner bypasses RLS
-- anyway. Every byte of real access control happens in FastAPI, where
-- the user is taken from a verified Supabase JWT and never from a URL.
--
-- They exist so that the day anything talks to Supabase directly
-- (supabase-js from the browser, PostgREST, an edge function) the
-- correct rules are already in force rather than being written under
-- pressure.
--
-- RLS is ENABLED but deliberately never FORCEd. FORCE applies the
-- policies to the table owner too — which is us — and would take the
-- entire backend offline the moment this file is applied. The previous
-- schema left RLS enabled on three tables with NO policies at all, which
-- is deny-all for anyone who is not the owner; that landmine goes away
-- with those tables.
-- ====================================================================

ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE saved_deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE deal_stage_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_dispatch_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own profile" ON user_profiles;
CREATE POLICY "own profile" ON user_profiles
    FOR ALL TO authenticated
    USING (id = auth.uid())
    WITH CHECK (id = auth.uid());

DROP POLICY IF EXISTS "own deals" ON saved_deals;
CREATE POLICY "own deals" ON saved_deals
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Reached only through its parent deal, so ownership is transitive.
DROP POLICY IF EXISTS "own deal history" ON deal_stage_history;
CREATE POLICY "own deal history" ON deal_stage_history
    FOR ALL TO authenticated
    USING (EXISTS (
        SELECT 1 FROM saved_deals d
        WHERE d.deal_id = deal_stage_history.deal_id AND d.user_id = auth.uid()
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM saved_deals d
        WHERE d.deal_id = deal_stage_history.deal_id AND d.user_id = auth.uid()
    ));

DROP POLICY IF EXISTS "own alert log" ON alert_dispatch_log;
CREATE POLICY "own alert log" ON alert_dispatch_log
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Market data is not user-owned. `opportunities` is readable by any
-- signed-in user; the aggregate market figures are public by design and
-- served through the API, not from here.
ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "read opportunities" ON opportunities;
CREATE POLICY "read opportunities" ON opportunities
    FOR SELECT TO authenticated
    USING (true);
