import os
import csv
import io
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Depends, Request, Response, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr
from typing import Any, Dict, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db
from matching_engine import TenantMatchingEngine, TENANT_ORGANIZATIONS
from workflow_engine import ConcurrentWorkflowEngine
from billing import StripeBillingEngine
from scrapers.orchestrator import OpportunityOrchestrator, TICK_DEADLINE_SECONDS
from cache_engine import global_cache, newsletter_store
from freemium_shield import FreemiumGatekeeper
from notifier import LeadAlertDispatcher

from addons.caiet_analyzer import CaietDeSarciniAnalyzer
from addons.win_probability import WinProbabilityEngine
from addons.competitor_tracker import CompetitorTrackerEngine
from ai_copilot import ProcurementAICopilot
from routers import eligibility, drafting, analysis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RO-INTEL-API")

scheduler = AsyncIOScheduler()
copilot_engine = ProcurementAICopilot()
orchestrator = OpportunityOrchestrator()

TICK_SECRET = os.getenv("TICK_SECRET", "")
# How long without a completed tick before ingestion counts as stale.
#
# The heartbeat asks GitHub Actions for a tick every 5 minutes, but
# scheduled workflow delivery there is explicitly best-effort: GitHub
# delays and drops cron runs under load, and hour-long gaps are normal on
# a */5 schedule. A 20-minute threshold therefore flagged healthy systems
# as broken purely because the scheduler was late, which is the fastest
# way to teach someone to ignore the alert. This is set to catch genuine
# stoppages (the kind that went unnoticed for four days) rather than
# ordinary scheduler jitter.
STALENESS_THRESHOLD_MINUTES = float(os.getenv("STALENESS_THRESHOLD_MINUTES", "180"))

async def background_scraping_job():
    logger.info("[24/7 DAEMON] Ingesting and qualifying pre-SEAP signals...")
    try:
        orchestrator = OpportunityOrchestrator()
        result = await orchestrator.run_pipeline()
        leads = result.get("leads", [])
        newsletter_store.save(leads)
        for lead in leads:
            # dispatch_high_priority_alert applies HIGH_PRIORITY_SCORE
            # itself; the duplicate literal threshold that used to sit here
            # was stricter than the one inside it and silently overrode it.
            await LeadAlertDispatcher.dispatch_high_priority_alert(lead)
        global_cache.invalidate()
        logger.info("[24/7 DAEMON] Pipeline synchronized.")
    except Exception as e:
        logger.error(f"[24/7 DAEMON] Error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(background_scraping_job, "interval", hours=6)
    scheduler.start()
    asyncio.create_task(background_scraping_job())
    logger.info("[SYSTEM] RO-INTEL Enterprise API active.")
    yield
    scheduler.shutdown()

app = FastAPI(title="RO-INTEL Enterprise Procurement Engine", version="2.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://ro-intel.xyz", "https://www.ro-intel.xyz", "https://romania-intel-frontend.vercel.app"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(eligibility.router)
app.include_router(drafting.router)
app.include_router(analysis.router)

class AuthSyncRequest(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None

class ProformaRequest(BaseModel):
    plan_id: str
    company_name: str
    cui_fiscal: str
    billing_email: EmailStr
    billing_address: Optional[str] = "Romania"

class CopilotQueryRequest(BaseModel):
    query: str
    tenant_id: Optional[str] = "t1_infra_transilvania"

class PipelineAddRequest(BaseModel):
    lead_data: dict

class PipelineUpdateRequest(BaseModel):
    deal_id: str
    new_stage: str
    notes: Optional[str] = None
    proposed_price: Optional[float] = None

class EmailAlertRequest(BaseModel):
    lead_data: dict
    recipient_email: EmailStr

class CompetitorAnalysisRequest(BaseModel):
    category: str
    county: str
    budget_ron: float

class CaietAnalysisRequest(BaseModel):
    project_title: str
    specification_text: str

class WinProbabilityRequest(BaseModel):
    estimated_budget_ron: float
    proposed_price_ron: float
    has_local_partnership: Optional[bool] = False
    lead_time_days: Optional[int] = 30

@app.get("/")
def root_index():
    return {"engine": "RO-INTEL Enterprise Procurement Engine", "status": "online", "version": "2.4.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "cache": "online"}

@app.post("/api/v1/system/tick")
async def system_tick(x_tick_secret: Optional[str] = Header(None)):
    """Driven by the free GitHub Actions heartbeat (and any external pinger)
    instead of relying on the Render dyno's own uptime — see
    .github/workflows/heartbeat.yml. Runs only scrapers whose own polling
    interval has elapsed (db.is_source_due) and streams matches/alerts per
    signal (scrapers/orchestrator.py:run_tick)."""
    if not TICK_SECRET or x_tick_secret != TICK_SECRET:
        raise HTTPException(status_code=401, detail="unauthorized")
    # run_tick enforces its own soft deadline (TICK_DEADLINE_SECONDS) and
    # records the tick before returning. This outer timeout is only a
    # backstop for a hang below that layer, so it must stay comfortably
    # above the soft deadline — if it fired first it would cancel the tick
    # mid-write and leave the run unrecorded, which is the failure mode
    # the soft deadline exists to prevent.
    return await asyncio.wait_for(orchestrator.run_tick(), timeout=TICK_DEADLINE_SECONDS + 60)

@app.get("/api/v1/system/status")
async def system_status():
    # The heartbeat parses this response, and a 500 here fails the whole
    # workflow run — so a database blip must not take the watchdog down
    # with it. Report the degradation instead of raising.
    try:
        last = await db.get_last_successful_tick()
    except Exception as e:
        logger.error(f"[Status] Could not read last tick: {e}")
        return {
            "last_tick_completed_at": None,
            "minutes_since_last_tick": None,
            "is_stale": True,
            "degraded": True,
            "detail": "database unavailable",
        }
    minutes_since = (datetime.now(timezone.utc) - last).total_seconds() / 60 if last else None
    return {
        "last_tick_completed_at": last.isoformat() if last else None,
        "minutes_since_last_tick": minutes_since,
        "is_stale": minutes_since is None or minutes_since > STALENESS_THRESHOLD_MINUTES,
    }

def _row_to_lead(row: Dict[str, Any]) -> Dict[str, Any]:
    """Converts a Postgres row into the JSON-serialisable lead shape the API
    already returns from the file cache.

    Three conversions are mandatory, not cosmetic — without them FastAPI
    raises while encoding and the endpoint 500s:
      * NUMERIC (estimated_value_ron, opportunity_score) arrives as
        decimal.Decimal, which the default JSON encoder cannot serialise.
      * DATE/TIMESTAMP arrive as date/datetime objects.
      * JSONB arrives as a raw string, while every consumer expects a dict.
    """
    lead: Dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, Decimal):
            lead[key] = float(value)
        elif isinstance(value, (datetime, date)):
            lead[key] = value.isoformat()
        else:
            lead[key] = value

    metadata = lead.get("metadata")
    if isinstance(metadata, str):
        try:
            lead["metadata"] = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            lead["metadata"] = {}

    # The DB column is estimated_value_ron; the API contract and the
    # frontend both read financial_value_ron.
    if lead.get("financial_value_ron") is None:
        lead["financial_value_ron"] = lead.get("estimated_value_ron") or 0.0
    return lead


async def _load_feed() -> Dict[str, Any]:
    """Reads the durable copy first, falling back to the on-disk cache.

    newsletter_store writes to Render's ephemeral disk, so it is wiped on
    every deploy and restart — the feed was returning 0 entries after a
    redeploy until the background job had re-scraped everything, even
    though the same opportunities were sitting safely in Postgres the
    whole time. Postgres is the source of truth; the file stays as a
    fallback for when DATABASE_URL is not configured (local runs).

    Keeps NewsletterStore's {updated_at, count, leads} shape either way —
    routers/analysis.py and the frontend both read `leads` off this.
    """
    db_failed = False
    try:
        rows = await db.get_recent_opportunities(limit=500)
    except Exception as e:
        logger.error(f"[Feed] Postgres read failed, falling back to file cache: {e}")
        rows = []
        db_failed = True

    if not rows:
        fallback = newsletter_store.load()
        # An empty feed caused by an unreachable database is not the same
        # thing as a market with no opportunities, and the caller cannot
        # tell them apart from the payload alone. Say which it is, so the
        # UI can show a warning instead of an empty state that looks like
        # a real (and alarming) result.
        if db_failed:
            fallback["degraded"] = True
            fallback["detail"] = "database unavailable — showing last cached snapshot"
        fallback.setdefault("source", "file-cache")
        return fallback

    leads = [_row_to_lead(row) for row in rows]

    newest = max((r.get("last_seen_at") for r in rows if r.get("last_seen_at")), default=None)
    return {
        "updated_at": newest.isoformat() if newest is not None and not isinstance(newest, str) else newest,
        "count": len(leads),
        "leads": leads,
        "source": "postgres",
    }


@app.get("/api/v1/newsletter/feed")
async def get_newsletter_feed():
    return await _load_feed()

@app.post("/api/v1/auth/sync")
async def sync_user_auth(payload: AuthSyncRequest):
    return {
        "status": "synced",
        "user": {
            "email": payload.email,
            "full_name": payload.full_name or payload.email.split("@")[0].title(),
            "tenant_id": "t1_infra_transilvania",
            "role": "Director Bidding & Strategie",
            "avatar_url": payload.avatar_url
        }
    }

@app.get("/api/v1/billing/plans")
def list_billing_plans():
    return StripeBillingEngine.get_plans()

@app.post("/api/v1/tenants/{tenant_id}/billing/proforma")
def generate_proforma(tenant_id: str, payload: ProformaRequest):
    return StripeBillingEngine.generate_proforma_invoice(
        tenant_id=tenant_id,
        plan_id=payload.plan_id,
        company_name=payload.company_name,
        cui_fiscal=payload.cui_fiscal,
        billing_email=payload.billing_email,
        billing_address=payload.billing_address
    )

@app.get("/api/v1/tenants/{tenant_id}/pipeline")
def get_tenant_pipeline(tenant_id: str, stage: Optional[str] = None):
    return {
        "tenant_id": tenant_id,
        "stages": ConcurrentWorkflowEngine.get_stages(),
        "deals": ConcurrentWorkflowEngine.get_tenant_pipeline(tenant_id, stage)
    }

@app.post("/api/v1/tenants/{tenant_id}/pipeline/add")
def add_pipeline_deal(tenant_id: str, payload: PipelineAddRequest):
    return ConcurrentWorkflowEngine.add_lead_to_pipeline(tenant_id, payload.lead_data)

@app.post("/api/v1/tenants/{tenant_id}/pipeline/update")
def update_pipeline_deal(tenant_id: str, payload: PipelineUpdateRequest):
    return ConcurrentWorkflowEngine.update_deal_stage(
        tenant_id=tenant_id,
        deal_id=payload.deal_id,
        new_stage=payload.new_stage,
        notes=payload.notes,
        proposed_price=payload.proposed_price
    )

@app.post("/api/v1/notifications/send-email-alert")
async def send_manual_email_alert(payload: EmailAlertRequest):
    success = await LeadAlertDispatcher.dispatch_email_alert(payload.lead_data, [payload.recipient_email])
    return {"status": "success" if success else "failed", "recipient": payload.recipient_email}

@app.post("/api/v1/addons/competitor-analysis")
async def analyze_competitor_landscape(payload: CompetitorAnalysisRequest):
    # Feed the engine the opportunities actually ingested, so the sector
    # view is computed from real data. It previously received nothing and
    # answered from a hardcoded benchmark table.
    return CompetitorTrackerEngine.analyze_landscape(
        payload.category,
        payload.county,
        payload.budget_ron,
        observed_opportunities=(await _load_feed()).get("leads", []),
    )

@app.post("/api/v1/addons/upload-caiet")
async def upload_and_analyze_caiet(file: UploadFile = File(...), project_title: str = Form(...)):
    file_bytes = await file.read()
    extracted_text = CaietDeSarciniAnalyzer.extract_text_from_file(file_bytes, file.filename)
    if not extracted_text:
        raise HTTPException(status_code=400, detail="Nu s-a putut extrage text din fisier.")
    return CaietDeSarciniAnalyzer.analyze_specification_text(extracted_text, project_title)

@app.get("/api/v1/tenants/{tenant_id}/feed")
async def get_tenant_feed(
    tenant_id: str,
    product_id: Optional[str] = None,
    category: Optional[str] = None,
    force_refresh: bool = False,
    is_subscribed: bool = True
):
    cache_key = f"feed:{tenant_id}:{product_id or 'all'}:{category or 'all'}:{is_subscribed}"
    if not force_refresh:
        cached_data = global_cache.get(cache_key)
        if cached_data:
            return cached_data

    orchestrator = OpportunityOrchestrator()
    pipeline_result = await orchestrator.run_pipeline()
    raw_leads = pipeline_result.get("leads", [])

    matched_leads = []
    for lead in raw_leads:
        if category and category != "all" and lead.get("category") != category:
            continue
        match_info = TenantMatchingEngine.evaluate_opportunity_for_tenant(lead, tenant_id)
        if match_info["is_match"]:
            lead_copy = dict(lead)
            lead_copy["opportunity_score"] = match_info["tenant_opportunity_score"]
            matched_leads.append(lead_copy)

    matched_leads.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
    gated_leads = FreemiumGatekeeper.enforce_paywall_tier(matched_leads, has_active_subscription=is_subscribed)
    
    payload = {"tenant_id": tenant_id, "count": len(gated_leads), "leads": gated_leads}
    global_cache.set(cache_key, payload, ttl_seconds=60)
    return payload

@app.get("/api/v1/analytics/market-report-72h")
async def get_72h_report(tenant_id: str = "t1_infra_transilvania"):
    feed_data = await get_tenant_feed(tenant_id)
    leads = feed_data.get("leads", [])
    return ProcurementAICopilot.generate_72h_macro_report(leads)

@app.post("/api/v1/copilot/chat")
async def copilot_chat(payload: CopilotQueryRequest):
    feed_data = await get_tenant_feed(payload.tenant_id or "t1_infra_transilvania")
    leads = feed_data.get("leads", [])
    reply = await copilot_engine.answer_copilot_query(payload.query, leads)
    return {"reply": reply}

@app.get("/api/v1/tenants/{tenant_id}/products")
async def get_tenant_products(tenant_id: str):
    org = TENANT_ORGANIZATIONS.get(tenant_id)
    if not org:
        return {"tenant_id": tenant_id, "company_name": "SC General Procurement SRL", "products": []}
    return {"tenant_id": tenant_id, "company_name": org["name"], "products": org["products"]}

@app.post("/api/v1/addons/analyze-caiet")
def analyze_caiet_sarcini(payload: CaietAnalysisRequest):
    return CaietDeSarciniAnalyzer.analyze_specification_text(payload.specification_text, payload.project_title)

@app.post("/api/v1/addons/predict-win-rate")
def predict_win_rate(payload: WinProbabilityRequest):
    return WinProbabilityEngine.calculate_win_odds(
        payload.estimated_budget_ron, payload.proposed_price_ron, payload.has_local_partnership, payload.lead_time_days
    )

@app.get("/api/v1/tenants/{tenant_id}/export/csv")
async def export_tenant_csv(tenant_id: str):
    feed_data = await get_tenant_feed(tenant_id)
    leads = feed_data.get("leads", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID Sursa", "Tip Registru", "Categorie", "Judet", "Beneficiar", "Titlu Proiect", "Valoare RON", "Data Publicare", "Termen Reactie", "Scor", "URL"])

    for l in leads:
        writer.writerow([
            l.get("source_id", ""), l.get("source_type", "SICAP"), l.get("category", ""), l.get("county", ""),
            l.get("entity_name", ""), l.get("project_title", ""), l.get("financial_value_ron", 0),
            l.get("published_date", ""), l.get("action_deadline", ""), l.get("opportunity_score", 0), l.get("source_url", "")
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=RO-INTEL-{tenant_id}.csv"}
    )
