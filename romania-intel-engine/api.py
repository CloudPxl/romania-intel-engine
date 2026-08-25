import os
import csv
import io
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request, Response, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from matching_engine import TenantMatchingEngine, TENANT_ORGANIZATIONS
from workflow_engine import ConcurrentWorkflowEngine
from billing import StripeBillingEngine, SUBSCRIPTION_PLANS
from scrapers.orchestrator import OpportunityOrchestrator
from cache_engine import global_cache
from security import SecurityGuard
from freemium_shield import FreemiumGatekeeper
from notifier import LeadAlertDispatcher

from addons.caiet_analyzer import CaietDeSarciniAnalyzer
from addons.win_probability import WinProbabilityEngine
from addons.foia_generator import LegalClarificationGenerator
from addons.business_eligibility import BusinessEligibilityEngine
from ai_copilot import ProcurementAICopilot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RO-INTEL-API")

scheduler = AsyncIOScheduler()
copilot_engine = ProcurementAICopilot()

async def background_scraping_job():
    logger.info("[24/7 DAEMON] Ingesting and qualifying pre-SEAP signals...")
    try:
        orchestrator = OpportunityOrchestrator()
        result = await orchestrator.run_pipeline()
        leads = result.get("leads", [])
        
        # Dispatch instant email alerts for high score signals
        for lead in leads:
            if lead.get("opportunity_score", 0) >= 9.2:
                await LeadAlertDispatcher.dispatch_high_priority_alert(lead)

        global_cache.invalidate()
        logger.info("[24/7 DAEMON] Pipeline synchronized and email alerts processed.")
    except Exception as e:
        logger.error(f"[24/7 DAEMON] Error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(background_scraping_job, "interval", hours=6)
    scheduler.start()
    logger.info("[SYSTEM] RO-INTEL Enterprise API active with 24/7 scheduler.")
    yield
    scheduler.shutdown()

app = FastAPI(
    title="RO-INTEL Enterprise Procurement Engine",
    version="2.3.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://ro-intel.xyz",
        "https://www.ro-intel.xyz",
        "https://romania-intel-frontend.vercel.app"
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class AuthSyncRequest(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    provider: Optional[str] = "google"

class ProformaRequest(BaseModel):
    plan_id: str
    company_name: str
    cui_fiscal: str
    billing_email: EmailStr
    billing_address: Optional[str] = "România"

class BusinessScanRequest(BaseModel):
    company_name: str
    cui_fiscal: str
    caen_code: str
    turnover_ron: float
    employee_count: int
    county: str

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

class CaietAnalysisRequest(BaseModel):
    project_title: str
    specification_text: str

class WinProbabilityRequest(BaseModel):
    estimated_budget_ron: float
    proposed_price_ron: float
    has_local_partnership: Optional[bool] = False
    lead_time_days: Optional[int] = 30

class ClarificationLetterRequest(BaseModel):
    authority_name: str
    project_title: str
    source_id: str
    company_name: str
    cui_fiscal: str
    clarification_points: str

@app.get("/")
def root_index():
    return {
        "engine": "RO-INTEL Enterprise Procurement Engine",
        "status": "online",
        "version": "2.3.0"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy", "cache": "online"}

@app.post("/api/v1/auth/sync")
async def sync_user_auth(payload: AuthSyncRequest):
    assigned_tenant = "t1_infra_transilvania"
    if "med" in payload.email.lower() or "pharma" in payload.email.lower():
        assigned_tenant = "t2_medtech_bucuresti"
    elif "consult" in payload.email.lower() or "grant" in payload.email.lower():
        assigned_tenant = "t3_vest_consulting_grants"

    return {
        "status": "synced",
        "user": {
            "email": payload.email,
            "full_name": payload.full_name or payload.email.split("@")[0].title(),
            "tenant_id": assigned_tenant,
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
    return {
        "status": "success" if success else "failed",
        "recipient": payload.recipient_email,
        "project_title": payload.lead_data.get("project_title")
    }

@app.post("/api/v1/addons/upload-caiet")
async def upload_and_analyze_caiet(
    file: UploadFile = File(...),
    project_title: str = Form(...)
):
    file_bytes = await file.read()
    extracted_text = CaietDeSarciniAnalyzer.extract_text_from_file(file_bytes, file.filename)
    if not extracted_text:
        raise HTTPException(status_code=400, detail="Nu s-a putut extrage text din fișierul încărcat.")
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
            if product_id:
                has_product = any(p["product_id"] == product_id for p in match_info["product_matches"])
                if not has_product:
                    continue
            
            lead_copy = dict(lead)
            lead_copy["opportunity_score"] = match_info["tenant_opportunity_score"]
            lead_copy["product_matches"] = match_info["product_matches"]
            lead_copy["match_reasons"] = match_info["match_reasons"]
            matched_leads.append(lead_copy)

    matched_leads.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
    gated_leads = FreemiumGatekeeper.enforce_paywall_tier(matched_leads, has_active_subscription=is_subscribed)
    
    payload = {"tenant_id": tenant_id, "count": len(gated_leads), "leads": gated_leads}
    global_cache.set(cache_key, payload, ttl_seconds=60)
    return payload

@app.post("/api/v1/business-eligibility/evaluate")
def evaluate_company_eligibility(payload: BusinessScanRequest):
    return BusinessEligibilityEngine.evaluate_company(
        payload.company_name,
        payload.cui_fiscal,
        payload.caen_code,
        payload.turnover_ron,
        payload.employee_count,
        payload.county
    )

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
        raise HTTPException(status_code=404, detail="Organizație inexistentă")
    return {"tenant_id": tenant_id, "company_name": org["name"], "products": org["products"]}

@app.post("/api/v1/addons/analyze-caiet")
def analyze_caiet_sarcini(payload: CaietAnalysisRequest):
    return CaietDeSarciniAnalyzer.analyze_specification_text(payload.specification_text, payload.project_title)

@app.post("/api/v1/addons/predict-win-rate")
def predict_win_rate(payload: WinProbabilityRequest):
    return WinProbabilityEngine.calculate_win_odds(
        payload.estimated_budget_ron,
        payload.proposed_price_ron,
        payload.has_local_partnership,
        payload.lead_time_days
    )

@app.post("/api/v1/addons/generate-clarification")
def generate_clarification_letter(payload: ClarificationLetterRequest):
    return LegalClarificationGenerator.generate_clarification_letter(
        payload.authority_name,
        payload.project_title,
        payload.source_id,
        payload.company_name,
        payload.cui_fiscal,
        payload.clarification_points
    )

@app.get("/api/v1/tenants/{tenant_id}/export/csv")
async def export_tenant_csv(tenant_id: str):
    feed_data = await get_tenant_feed(tenant_id)
    leads = feed_data.get("leads", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID Sursa", "Tip Registru", "Categorie", "Subcategorie", "Judet", "Beneficiar", "Titlu Proiect", 
        "Valoare RON", "Data Publicare", "Termen Reactie", "Sursa Finantare", "Scor", "URL Document"
    ])

    for l in leads:
        writer.writerow([
            l.get("source_id", ""),
            l.get("source_type", "SICAP"),
            l.get("category", ""),
            l.get("sub_category", ""),
            l.get("county", ""),
            l.get("entity_name", ""),
            l.get("project_title", ""),
            l.get("financial_value_ron", 0),
            l.get("published_date", ""),
            l.get("action_deadline", ""),
            l.get("funding_source", "Fonduri Publice"),
            l.get("opportunity_score", 0),
            l.get("source_url", "")
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=RO-INTEL-{tenant_id}.csv"}
    )
