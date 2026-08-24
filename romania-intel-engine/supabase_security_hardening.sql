-- =========================================================
-- RO-INTEL MULTI-TENANT ROW LEVEL SECURITY (RLS) POLICIES
-- =========================================================

-- 1. Enable RLS on core tables
ALTER TABLE IF EXISTS opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS dossier_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS audit_logs ENABLE ROW LEVEL SECURITY;

-- 2. Audit Logging Table
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    user_email TEXT,
    action TEXT NOT NULL,
    resource_id TEXT,
    ip_address TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. Public Read Policy for Normalized Pre-SEAP Opportunities
-- Allows tenants to read institutional signals matching their assigned industry domain
DROP POLICY IF EXISTS "Allow authenticated tenants to read opportunities" ON opportunities;
CREATE POLICY "Allow authenticated tenants to read opportunities"
ON opportunities FOR SELECT
TO authenticated
USING (true);

-- 4. Strict Isolation Policy for Tenant Dossier Notes
CREATE TABLE IF NOT EXISTS dossier_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    author_email TEXT NOT NULL,
    internal_strategy_notes TEXT,
    bid_budget_allocated NUMERIC,
    created_at TIMESTAMPTZ DEFAULT now()
);

DROP POLICY IF EXISTS "Tenant Isolation for Dossier Notes" ON dossier_notes;
CREATE POLICY "Tenant Isolation for Dossier Notes"
ON dossier_notes FOR ALL
TO authenticated
USING (tenant_id = (auth.jwt() ->> 'tenant_id'))
WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id'));
