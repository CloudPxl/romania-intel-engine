-- ====================================================================
-- REAL TENANT CONFIG + USER->TENANT MEMBERSHIP
-- Apply by hand via the Supabase SQL editor (same convention as
-- pipeline_schema.sql / seap_notices_schema.sql / scraper_matrix_schema.sql
-- / document_extractions_schema.sql).
--
-- Replaces matching_engine.py's hardcoded TENANT_ORGANIZATIONS dict and
-- closes the "any authenticated user can address any tenant_id" gap
-- (security.py's own verify_tenant_authorization docstring already named
-- this limitation explicitly).
--
-- IMPORTANT — this project's Supabase instance already has a `tenants`
-- table (and a differently-shaped `tenant_products`) created by hand at
-- some point from the old multi_tenancy_schema.sql, which this repo's
-- Python code never reads but which WAS actually applied to the live
-- database (confirmed live: running this file's first version failed
-- with `column "primary_domain" of relation "tenants" does not exist`,
-- because CREATE TABLE IF NOT EXISTS is a no-op against that pre-existing
-- narrower table). "Not referenced by any live code" and "not present in
-- the database" turned out to be two different claims — only the first
-- was actually verified before. This version adds every column via
-- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` as well, so it converges to
-- the right shape whether the table is brand new, already has the old
-- multi_tenancy_schema.sql columns, or (from a retry) already has this
-- file's own columns. New columns are added nullable rather than
-- NOT NULL, since Postgres refuses to add a NOT NULL column with no
-- DEFAULT to a table that might already have rows.
--
-- One tenant per user is enough for this product's current shape (an
-- employee at one client company) — no join table, tenant_id lives
-- directly on user_profiles.
-- ====================================================================

CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL
);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS primary_domain TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS alert_emails TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS telegram_chat_id TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS min_alert_score NUMERIC;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();

CREATE TABLE IF NOT EXISTS tenant_products (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE
);
ALTER TABLE tenant_products ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE tenant_products ADD COLUMN IF NOT EXISTS domain TEXT;
ALTER TABLE tenant_products ADD COLUMN IF NOT EXISTS target_counties TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE tenant_products ADD COLUMN IF NOT EXISTS min_value_ron NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE tenant_products ADD COLUMN IF NOT EXISTS keywords TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE tenant_products ADD COLUMN IF NOT EXISTS exclude_keywords TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE tenant_products ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_tenant_products_tenant_id ON tenant_products(tenant_id);

-- id is the Supabase Auth user id (JWT `sub` claim) — a real UUID, not a
-- synthetic string. tenant_id is nullable: a user who has signed in via
-- /api/v1/auth/sync but hasn't been provisioned to a tenant yet (by
-- scripts/provision_tenant.py) has a row here with tenant_id = NULL,
-- reported honestly as "not provisioned" rather than silently defaulted
-- into any tenant's data.
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY
);
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS tenant_id TEXT REFERENCES tenants(id) ON DELETE SET NULL;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS role TEXT;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_user_profiles_tenant_id ON user_profiles(tenant_id);

-- One-time seed: the 3 tenants/products matching_engine.py hardcodes
-- today, so enabling this schema does not change day-one matching
-- behaviour. Safe to re-run (ON CONFLICT DO UPDATE) if applied twice —
-- upserts rather than DO NOTHING specifically so re-running this file
-- after the column-fix above actually backfills primary_domain/keywords/
-- etc. on rows a first, partially-failed attempt might already have
-- inserted with only the pre-existing old columns populated.
INSERT INTO tenants (id, company_name, primary_domain, alert_emails, telegram_chat_id, min_alert_score) VALUES
    ('t1_infra_transilvania', 'SC Infra Construct Transilvania SRL', 'infrastructura', ARRAY['director@infraconstruct.ro'], NULL, 7.5),
    ('t2_medtech_bucuresti', 'SC MedTech Pharma SRL', 'sanatate', ARRAY['office@ro-intel.xyz'], NULL, 7.5),
    ('t3_vest_consulting_grants', 'SC Vest Project Consulting', 'energie', ARRAY['office@ro-intel.xyz'], NULL, 7.5)
ON CONFLICT (id) DO UPDATE SET
    company_name = EXCLUDED.company_name,
    primary_domain = EXCLUDED.primary_domain,
    alert_emails = EXCLUDED.alert_emails,
    min_alert_score = EXCLUDED.min_alert_score;

INSERT INTO tenant_products (id, tenant_id, name, domain, target_counties, min_value_ron, keywords, exclude_keywords) VALUES
    ('prod_heavy_infra', 't1_infra_transilvania', 'Divizia Infrastructură Grea & Drumuri Județene', 'infrastructura',
     ARRAY['Cluj','Iasi','Bihor','Timis','Bucuresti','Constanta'], 10000000.0,
     ARRAY['drum','drumuri','pod','poduri','pasaj','asfalt','asfaltare','reabilitare','modernizare','infrastructura','metrou','sala de sport','sala polivalenta','viaduct','tunel','consolidare','terasamente','constructie','construire','extindere'],
     ARRAY['curatenie','igienizare','papetarie','rechizite','catering','asigurare','medicina muncii','formare profesionala']),
    ('prod_smart_traffic', 't1_infra_transilvania', 'Divizia Smart City & Sisteme ITS SCATS', 'infrastructura',
     ARRAY['Iasi','Cluj','Bucuresti','Timis','Constanta'], 3000000.0,
     ARRAY['its','trafic','semaforizare','semafor','anpr','senzori','scats','monitorizare video','supraveghere video','smart city','management al traficului','parcari'],
     ARRAY['curatenie','papetarie','catering']),
    ('prod_radiology_advanced', 't2_medtech_bucuresti', 'Divizia Imagistică Avansată & Radioterapie', 'sanatate',
     ARRAY['Bucuresti','Iasi','Cluj','Timis','Dolj'], 5000000.0,
     ARRAY['rmn','ct','radioterapie','accelerator','imagistica','imagistic','spital','spitalicesc','oncologie','oncologic','radiologie','tomograf','angiograf','mamograf','ecograf','dispensar','unitate sanitara','ambulatoriu','bloc operator'],
     ARRAY['papetarie','curatenie','paza','formare profesionala','catering']),
    ('prod_green_energy', 't3_vest_consulting_grants', 'Divizia Consultanță Parcuri Solare & BESS', 'energie',
     ARRAY['Timis','Cluj','Iasi','Constanta','Bihor'], 5000000.0,
     ARRAY['fotovoltaic','fotovoltaice','solar','solara','energie','energetica','baterii','stocare','cogenerare','eficienta energetica','regenerabil','regenerabila','panouri','bess','termoficare','pompe de caldura','eolian'],
     ARRAY['papetarie','curatenie','catering'])
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    domain = EXCLUDED.domain,
    target_counties = EXCLUDED.target_counties,
    min_value_ron = EXCLUDED.min_value_ron,
    keywords = EXCLUDED.keywords,
    exclude_keywords = EXCLUDED.exclude_keywords;
