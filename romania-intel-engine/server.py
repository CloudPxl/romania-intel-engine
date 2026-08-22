import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json
import uvicorn

from src.database.models import get_db_connection, init_db, is_postgres
from src.notifications.exporter import LeadExporter
from src.scrapers.registry import registry
from src.scrapers.sources.seap_consultations import SeapMarketConsultationAdapter
from src.scrapers.sources.seap_direct_awards import SeapDirectAwardsAdapter
from src.scrapers.sources.cluj_urbanism import ClujUrbanismAdapter
from src.scrapers.sources.bucuresti_urbanism import BucurestiUrbanismAdapter
from src.scrapers.sources.apm_environment import ApmEnvironmentalAdapter
from src.scrapers.sources.adr_national import NationalAdrHubAdapter
from src.scrapers.sources.mipe_oportunitati import MipeOportunitatiAdapter
from src.scrapers.sources.datagov_ro import DataGovRoAdapter
from src.ai.processor import RomanianIntelAIProcessor
from src.matching.engine import MultiTenantMatchmaker
from src.analytics.engine import TenantAIAnalyticsEngine

registry.register(SeapMarketConsultationAdapter(min_value_ron=50000.0, page_size=25))
registry.register(SeapDirectAwardsAdapter(min_value_ron=20000.0))
registry.register(ClujUrbanismAdapter())
registry.register(BucurestiUrbanismAdapter())
registry.register(ApmEnvironmentalAdapter())
registry.register(NationalAdrHubAdapter())
registry.register(MipeOportunitatiAdapter())
registry.register(DataGovRoAdapter())

ai_processor = RomanianIntelAIProcessor()
matchmaker = MultiTenantMatchmaker()
analytics_engine = TenantAIAnalyticsEngine()

async def background_scraping_daemon():
    print("[+] 24/7 Background Scraping Daemon active.")
    cycle = 1
    while True:
        try:
            print(f"\n>>> [BACKGROUND CYCLE #{cycle}] Ingesting from 8 public portals...")
            for name, adapter in registry.get_all().items():
                try:
                    records = await adapter.execute_safe()
                    if records:
                        print(f"  • [{name}]: {len(records)} new records")
                except Exception as e:
                    print(f"  [!] Scraper {name} error: {e}")

            structured = ai_processor.process_pending_records(limit=250)
            if structured > 0:
                print(f"  • AI Refined & Scored {structured} new commercial leads.")

            matches = matchmaker.run_matchmaking()
            matched_sum = sum(len(v) for v in matches.values())
            if matched_sum > 0:
                print(f"  • Matched {matched_sum} qualified leads to client portfolios.")

            cycle += 1
        except Exception as err:
            print(f"[!] Daemon cycle exception: {err}")
        
        await asyncio.sleep(120)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    daemon_task = asyncio.create_task(background_scraping_daemon())
    yield
    daemon_task.cancel()

app = FastAPI(
    title="RO-INTEL Enterprise API",
    description="Institutional Commercial Intelligence & Multi-Tenant Lead Engine",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    email: str
    password: Optional[str] = None
    provider: Optional[str] = "email"
    full_name: Optional[str] = None
    phone: Optional[str] = None

class SwitchTenantRequest(BaseModel):
    user_id: str
    target_tenant_id: str

class TenantPreferencesUpdate(BaseModel):
    allowed_counties: List[str]
    subscribed_trade_tags: List[str]
    min_financial_value_ron: float = 0.0
    min_opportunity_score: int = 6

@app.get("/")
def root():
    return {
        "status": "online",
        "system": "RO-INTEL Enterprise API",
        "database": "Supabase PostgreSQL" if is_postgres() else "Local SQLite",
        "active_sources": 8,
        "docs_url": "/docs"
    }

@app.post("/api/v1/auth/login")
def login_or_register(req: LoginRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if is_postgres() else "?"

    cursor.execute(f"""
        SELECT id, email, phone, full_name, avatar_url, auth_provider, tenant_id, role, custom_ui_settings 
        FROM user_profiles 
        WHERE email = {ph}
    """, (req.email,))
    user = cursor.fetchone()

    if not user:
        user_id = f"usr_{os.urandom(6).hex()}"
        default_tenant = "t1_infra_transilvania"
        name = req.full_name or req.email.split("@")[0].capitalize()
        ui_sett = json.dumps({"advanced_mode": False, "theme": "dark", "instant_notifications": True})

        if is_postgres():
            cursor.execute("""
                INSERT INTO user_profiles (id, email, phone, full_name, auth_provider, tenant_id, role, custom_ui_settings)
                VALUES (%s, %s, %s, %s, %s, %s, 'owner', %s)
            """, (user_id, req.email, req.phone, name, req.provider, default_tenant, ui_sett))
        else:
            cursor.execute("""
                INSERT INTO user_profiles (id, email, phone, full_name, auth_provider, tenant_id, role, custom_ui_settings)
                VALUES (?, ?, ?, ?, ?, ?, 'owner', ?)
            """, (user_id, req.email, req.phone, name, req.provider, default_tenant, ui_sett))
        conn.commit()

        user_data = {
            "id": user_id,
            "email": req.email,
            "phone": req.phone,
            "full_name": name,
            "tenant_id": default_tenant,
            "role": "owner",
            "custom_ui_settings": json.loads(ui_sett)
        }
    else:
        user_data = {
            "id": user[0],
            "email": user[1],
            "phone": user[2],
            "full_name": user[3],
            "avatar_url": user[4],
            "auth_provider": user[5],
            "tenant_id": user[6],
            "role": user[7],
            "custom_ui_settings": json.loads(user[8]) if isinstance(user[8], str) else (user[8] or {})
        }

    cursor.execute(f"SELECT company_name, fiscal_code_cui, tier FROM tenants WHERE id = {ph}", (user_data["tenant_id"],))
    tenant = cursor.fetchone()
    conn.close()

    return {
        "status": "authenticated",
        "token": f"jwt_{user_data['id']}_{os.urandom(8).hex()}",
        "user": user_data,
        "tenant": {
            "id": user_data["tenant_id"],
            "company_name": tenant[0] if tenant else "Individual Workspace",
            "fiscal_code_cui": tenant[1] if tenant else "RO000000",
            "tier": tenant[2] if tenant else "standard"
        }
    }

@app.get("/api/v1/auth/me")
def get_user_profile(email: Optional[str] = Query(None), user_id: Optional[str] = Query(None)):
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if is_postgres() else "?"

    if user_id:
        cursor.execute(f"""
            SELECT u.id, u.email, u.phone, u.full_name, u.avatar_url, u.tenant_id, u.role, u.custom_ui_settings,
                   t.company_name, t.fiscal_code_cui, t.tier
            FROM user_profiles u
            LEFT JOIN tenants t ON u.tenant_id = t.id
            WHERE u.id = {ph}
        """, (user_id,))
    elif email:
        cursor.execute(f"""
            SELECT u.id, u.email, u.phone, u.full_name, u.avatar_url, u.tenant_id, u.role, u.custom_ui_settings,
                   t.company_name, t.fiscal_code_cui, t.tier
            FROM user_profiles u
            LEFT JOIN tenants t ON u.tenant_id = t.id
            WHERE u.email = {ph}
        """, (email,))
    else:
        conn.close()
        raise HTTPException(status_code=400, detail="Provide either email or user_id")

    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="User profile not found")

    return {
        "id": row[0],
        "email": row[1],
        "phone": row[2],
        "full_name": row[3],
        "avatar_url": row[4],
        "tenant_id": row[5],
        "role": row[6],
        "custom_ui_settings": json.loads(row[7]) if isinstance(row[7], str) else row[7],
        "tenant": {
            "id": row[5],
            "company_name": row[8],
            "fiscal_code_cui": row[9],
            "tier": row[10]
        }
    }

@app.post("/api/v1/auth/switch-tenant")
def switch_tenant(req: SwitchTenantRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if is_postgres() else "?"

    cursor.execute(f"SELECT id, company_name, tier FROM tenants WHERE id = {ph}", (req.target_tenant_id,))
    tenant = cursor.fetchone()
    if not tenant:
        conn.close()
        raise HTTPException(status_code=404, detail="Target tenant does not exist")

    cursor.execute(f"UPDATE user_profiles SET tenant_id = {ph} WHERE id = {ph}", (req.target_tenant_id, req.user_id))
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "active_tenant": {
            "id": tenant[0],
            "company_name": tenant[1],
            "tier": tenant[2]
        }
    }

@app.get("/api/v1/tenants")
def list_tenants():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.company_name, t.fiscal_code_cui, t.contact_email, t.contact_phone, t.tier, t.is_active,
               f.allowed_counties, f.subscribed_trade_tags, f.min_financial_value_ron, f.min_opportunity_score
        FROM tenants t
        LEFT JOIN tenant_filters f ON t.id = f.tenant_id
        ORDER BY t.created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "company_name": r[1],
            "fiscal_code_cui": r[2],
            "contact_email": r[3],
            "contact_phone": r[4],
            "tier": r[5],
            "is_active": bool(r[6]),
            "allowed_counties": json.loads(r[7]) if isinstance(r[7], str) else r[7],
            "subscribed_trade_tags": json.loads(r[8]) if isinstance(r[8], str) else r[8],
            "min_financial_value_ron": float(r[9]) if r[9] is not None else 0.0,
            "min_opportunity_score": r[10] or 6,
            "feed_url": f"/api/v1/tenants/{r[0]}/feed",
            "analytics_url": f"/api/v1/tenants/{r[0]}/analytics",
            "export_csv_url": f"/api/v1/tenants/{r[0]}/export/csv"
        })
    return {"count": len(result), "tenants": result}

@app.put("/api/v1/tenants/{tenant_id}/preferences")
def update_tenant_preferences(tenant_id: str, prefs: TenantPreferencesUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if is_postgres() else "?"

    counties_json = json.dumps(prefs.allowed_counties)
    tags_json = json.dumps(prefs.subscribed_trade_tags)

    if is_postgres():
        cursor.execute("""
            INSERT INTO tenant_filters (tenant_id, allowed_counties, subscribed_trade_tags, min_financial_value_ron, min_opportunity_score)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET
                allowed_counties = EXCLUDED.allowed_counties,
                subscribed_trade_tags = EXCLUDED.subscribed_trade_tags,
                min_financial_value_ron = EXCLUDED.min_financial_value_ron,
                min_opportunity_score = EXCLUDED.min_opportunity_score
        """, (tenant_id, counties_json, tags_json, prefs.min_financial_value_ron, prefs.min_opportunity_score))
    else:
        cursor.execute("""
            INSERT OR REPLACE INTO tenant_filters (tenant_id, allowed_counties, subscribed_trade_tags, min_financial_value_ron, min_opportunity_score)
            VALUES (?, ?, ?, ?, ?)
        """, (tenant_id, counties_json, tags_json, prefs.min_financial_value_ron, prefs.min_opportunity_score))

    conn.commit()
    conn.close()

    matchmaker.run_matchmaking()
    return {"status": "success", "message": "Tenant filtering preferences updated."}

@app.get("/api/v1/tenants/{tenant_id}/analytics")
def get_tenant_market_analytics(tenant_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if is_postgres() else "?"

    cursor.execute(f"SELECT company_name, tier FROM tenants WHERE id = {ph}", (tenant_id,))
    tenant = cursor.fetchone()
    conn.close()

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    company_name, tier = tenant[0], tenant[1]
    market_data = analytics_engine.aggregate_tenant_market_data(tenant_id)
    ai_briefing = analytics_engine.generate_ai_executive_briefing(company_name, tier, market_data)

    return {
        "tenant_id": tenant_id,
        "company_name": company_name,
        "tier": tier,
        "telemetry": {
            "total_qualified_leads": market_data["total_leads"],
            "total_pipeline_ron": market_data["total_pipeline_ron"],
            "avg_opportunity_score": market_data["avg_opportunity_score"]
        },
        "market_distribution": {
            "top_counties": market_data["county_distribution"],
            "top_spenders": market_data["top_spenders"],
            "tag_density": market_data["tag_density"]
        },
        "ai_strategic_briefing": ai_briefing
    }

@app.get("/api/v1/leads")
def get_leads(
    county: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    min_score: int = Query(1, ge=1, le=10),
    min_value: Optional[float] = None,
    limit: int = 100
):
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if is_postgres() else "?"

    query = f"SELECT source_id, category, county, locality, project_title, entity_name, financial_value_ron, executive_summary, sales_pitch_angle, trade_tags, opportunity_score, action_deadline, source_url FROM structured_intel WHERE opportunity_score >= {ph}"
    params = [min_score]

    if county and county.lower() != "all":
        query += f" AND LOWER(county) LIKE {ph}"
        params.append(f"%{county.lower()}%")
    if category and category.lower() != "all":
        query += f" AND category = {ph}"
        params.append(category)
    if tag:
        query += f" AND LOWER(CAST(trade_tags AS TEXT)) LIKE {ph}"
        params.append(f"%{tag.lower()}%")
    if min_value:
        query += f" AND financial_value_ron >= {ph}"
        params.append(min_value)

    query += f" ORDER BY opportunity_score DESC, financial_value_ron DESC NULLS LAST LIMIT {ph}"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    leads = []
    for r in rows:
        leads.append({
            "source_id": r[0],
            "category": r[1],
            "county": r[2],
            "locality": r[3],
            "project_title": r[4],
            "entity_name": r[5],
            "financial_value_ron": float(r[6]) if r[6] is not None else None,
            "executive_summary": r[7],
            "sales_pitch_angle": r[8],
            "trade_tags": json.loads(r[9]) if isinstance(r[9], str) else r[9],
            "opportunity_score": r[10],
            "action_deadline": r[11],
            "source_url": r[12]
        })
    return {"count": len(leads), "data": leads}

@app.get("/api/v1/tenants/{tenant_id}/feed")
def get_tenant_feed(tenant_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if is_postgres() else "?"

    active_condition = "is_active = TRUE" if is_postgres() else "is_active = 1"
    cursor.execute(f"SELECT company_name, tier FROM tenants WHERE id = {ph} AND {active_condition}", (tenant_id,))
    tenant = cursor.fetchone()
    if not tenant:
        conn.close()
        raise HTTPException(status_code=404, detail="Tenant not found or inactive")

    cursor.execute(f"""
        SELECT s.source_id, s.category, s.county, s.locality, s.project_title, s.entity_name,
               s.financial_value_ron, s.executive_summary, s.sales_pitch_angle, s.trade_tags,
               s.opportunity_score, s.action_deadline, s.source_url, d.matched_at, d.is_sent
        FROM tenant_dispatches d
        JOIN structured_intel s ON d.source_id = s.source_id
        WHERE d.tenant_id = {ph}
        ORDER BY s.opportunity_score DESC, d.matched_at DESC
    """, (tenant_id,))
    rows = cursor.fetchall()
    conn.close()

    leads = []
    for r in rows:
        leads.append({
            "source_id": r[0],
            "category": r[1],
            "county": r[2],
            "locality": r[3],
            "project_title": r[4],
            "entity_name": r[5],
            "financial_value_ron": float(r[6]) if r[6] is not None else None,
            "executive_summary": r[7],
            "sales_pitch_angle": r[8],
            "trade_tags": json.loads(r[9]) if isinstance(r[9], str) else r[9],
            "opportunity_score": r[10],
            "action_deadline": r[11],
            "source_url": r[12]
        })

    return {
        "tenant_id": tenant_id,
        "company_name": tenant[0],
        "tier": tenant[1],
        "lead_count": len(leads),
        "leads": leads
    }

@app.get("/api/v1/tenants/{tenant_id}/export/csv")
def export_tenant_leads_csv(tenant_id: str):
    feed = get_tenant_feed(tenant_id)
    leads = feed["leads"]
    company_name = feed["company_name"]

    csv_content = LeadExporter.export_to_csv_string(leads)
    filename = f"Leads_{company_name.replace(' ', '_')}.csv"

    return Response(
        content=csv_content.encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
