-- ====================================================================
-- REAL TENANT CONFIG + USER->TENANT MEMBERSHIP
-- Apply by hand via the Supabase SQL editor (same convention as
-- pipeline_schema.sql / seap_notices_schema.sql / scraper_matrix_schema.sql
-- / document_extractions_schema.sql).
--
-- Replaces matching_engine.py's hardcoded TENANT_ORGANIZATIONS dict and
-- closes the "any authenticated user can address any tenant_id" gap
-- (security.py's own verify_tenant_authorization docstring already named
-- this limitation explicitly). This is a separate, from-scratch design —
-- NOT a resumption of multi_tenancy_schema.sql / supabase_security_
-- hardening.sql / scripts/seed_tenants.py's `user_profiles` reference,
-- all three of which are confirmed dead (never read by db.py/security.py/
-- api.py; seed_tenants.py's user ids are synthetic strings, not real
-- Supabase Auth UUIDs, so nothing there could back a real check anyway).
--
-- One tenant per user is enough for this product's current shape (an
-- employee at one client company) — no join table, tenant_id lives
-- directly on user_profiles.
-- ====================================================================

CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    primary_domain TEXT NOT NULL,
    alert_emails TEXT[] NOT NULL DEFAULT '{}',
    telegram_chat_id TEXT,
    min_alert_score NUMERIC,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_products (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    target_counties TEXT[] NOT NULL DEFAULT '{}',
    min_value_ron NUMERIC NOT NULL DEFAULT 0,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    exclude_keywords TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenant_products_tenant_id ON tenant_products(tenant_id);

-- id is the Supabase Auth user id (JWT `sub` claim) — a real UUID, not a
-- synthetic string. tenant_id is nullable: a user who has signed in via
-- /api/v1/auth/sync but hasn't been provisioned to a tenant yet (by
-- scripts/provision_tenant.py) has a row here with tenant_id = NULL,
-- reported honestly as "not provisioned" rather than silently defaulted
-- into any tenant's data.
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL,
    tenant_id TEXT REFERENCES tenants(id) ON DELETE SET NULL,
    role TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_tenant_id ON user_profiles(tenant_id);

-- One-time seed: the 3 tenants/products matching_engine.py hardcodes
-- today, so enabling this schema does not change day-one matching
-- behaviour. Safe to re-run (ON CONFLICT DO NOTHING) if applied twice.
INSERT INTO tenants (id, company_name, primary_domain, alert_emails, telegram_chat_id, min_alert_score) VALUES
    ('t1_infra_transilvania', 'SC Infra Construct Transilvania SRL', 'infrastructura', ARRAY['director@infraconstruct.ro'], NULL, 7.5),
    ('t2_medtech_bucuresti', 'SC MedTech Pharma SRL', 'sanatate', ARRAY['office@ro-intel.xyz'], NULL, 7.5),
    ('t3_vest_consulting_grants', 'SC Vest Project Consulting', 'energie', ARRAY['office@ro-intel.xyz'], NULL, 7.5)
ON CONFLICT (id) DO NOTHING;

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
ON CONFLICT (id) DO NOTHING;
