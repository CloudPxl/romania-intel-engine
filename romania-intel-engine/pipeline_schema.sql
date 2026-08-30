-- ====================================================================
-- RO-INTEL DEAL PIPELINE: PERSISTENT WORKFLOW SCHEMA
-- Apply by hand via the Supabase SQL editor (same convention as
-- scraper_matrix_schema.sql). Supersedes workflow_engine.py's
-- CONCURRENT_DEAL_PIPELINE in-memory dict, which is wiped on every
-- process restart.
--
-- tenant_id is a plain TEXT column, not a foreign key into the `tenants`
-- table from multi_tenancy_schema.sql — that table is never actually
-- populated by the live app (TENANT_ORGANIZATIONS in matching_engine.py
-- is a Python dict, not a DB table), matching how
-- tenant_alert_dispatch_log.tenant_id already works in
-- scraper_matrix_schema.sql. Adding a FK here would make every insert
-- fail against a parent table that has no rows.
-- ====================================================================

-- 1. One row per tracked deal
CREATE TABLE IF NOT EXISTS product_bidding_deals (
    deal_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    product_id TEXT,
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
    assigned_to TEXT,
    target_margin_pct NUMERIC,
    estimated_value_ron NUMERIC DEFAULT 0,
    proposed_price NUMERIC,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_deals_tenant ON product_bidding_deals(tenant_id);
CREATE INDEX IF NOT EXISTS idx_deals_tenant_product ON product_bidding_deals(tenant_id, product_id);

-- 2. Stage transition audit trail — what get_pipeline_metrics() in
-- workflow_engine.py uses to compute real time-in-stage and funnel
-- conversion rates, instead of estimating them.
CREATE TABLE IF NOT EXISTS deal_stage_history (
    id BIGSERIAL PRIMARY KEY,
    deal_id TEXT NOT NULL REFERENCES product_bidding_deals(deal_id) ON DELETE CASCADE,
    from_stage TEXT,
    to_stage TEXT NOT NULL,
    changed_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_stage_history_deal ON deal_stage_history(deal_id);
