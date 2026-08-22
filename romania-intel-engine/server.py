import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
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
    title="Romania B2B Intelligence Engine API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "status": "online",
        "system": "Romania B2B Intelligence Engine",
        "database": "Supabase PostgreSQL" if is_postgres() else "Local SQLite",
        "active_sources": 8,
        "docs_url": "/docs"
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
            "export_csv_url": f"/api/v1/tenants/{r[0]}/export/csv"
        })
    return {"count": len(result), "tenants": result}

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

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
