-- ====================================================================
-- RO-INTEL ENTERPRISE MULTI-TENANT & MULTI-PRODUCT WORKFLOW SCHEMA
-- ====================================================================

-- 1. Organizations (Tenants)
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    cui_fiscal TEXT UNIQUE,
    subscription_tier TEXT DEFAULT 'enterprise',
    max_seats INTEGER DEFAULT 25,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Tenant Products / Divisions (Multi-Product per Tenant)
CREATE TABLE IF NOT EXISTS tenant_products (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    product_name TEXT NOT NULL,
    domain_category TEXT NOT NULL,
    min_deal_value_ron NUMERIC DEFAULT 1000000.0,
    target_counties TEXT[] DEFAULT '{}',
    matching_keywords TEXT[] DEFAULT '{}',
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. Concurrent Bidding Workflow Pipelines
CREATE TABLE IF NOT EXISTS product_bidding_deals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES tenant_products(id) ON DELETE CASCADE,
    opportunity_id TEXT NOT NULL,
    stage TEXT DEFAULT 'discovery' CHECK (stage IN (
        'discovery', 
        'consultation_drafted', 
        'consultation_submitted', 
        'caiet_sarcini_analysis', 
        'offer_prepared', 
        'bid_submitted', 
        'won', 
        'lost'
    )),
    assigned_user_email TEXT,
    allocated_bid_budget_ron NUMERIC DEFAULT 0.0,
    margin_target_percent NUMERIC DEFAULT 18.5,
    custom_battlecard_notes TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 4. Enable Row Level Security (RLS)
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE product_bidding_deals ENABLE ROW LEVEL SECURITY;
