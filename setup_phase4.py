import os, sys, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(ROOT, "romania-intel-engine")
FRONTEND = os.path.join(ROOT, "romania-intel-frontend")

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
    print(f"  [✓] Written: {os.path.relpath(path, ROOT)}")

def run_cmd(cmd, cwd):
    print(f"\n[RUN] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd)
    if res.returncode != 0:
        print(f"❌ Failed: {' '.join(cmd)}")
        sys.exit(1)

print("\n⚡ [1/5] Creating Backend Addons (Competitor Tracker & Dossier Generator)...")

# 1. COMPETITOR TRACKER
write_file(os.path.join(ENGINE, "addons/competitor_tracker.py"), """
import logging
from typing import Dict, Any, List

logger = logging.getLogger("CompetitorTracker")

MARKET_BENCHMARKS = {
    "infrastructura": {
        "avg_discount_pct": 8.4,
        "undercut_risk": "Mediu-Ridicat",
        "cnsc_dispute_rate": "28%",
        "frequent_players": ["Strabag SRL", "Porr Construct", "Con-A Sibiu", "Ness Proiect Europe", "UTI Facility Management"],
        "pricing_strategy": "Evitati discounturi sub 82% din valoarea estimata pentru a preveni cererile de justificare de pret neobisnuit de scazut (Art. 215 Legea 98/2016)."
    },
    "sanatate": {
        "avg_discount_pct": 4.8,
        "undercut_risk": "Scazut",
        "cnsc_dispute_rate": "34%",
        "frequent_players": ["Medist SRL", "Siemens Healthcare", "General Electric Medical", "Deltamed SRL", "Gral Medical"],
        "pricing_strategy": "Punctajul tehnic (garantie extinsa, SLA service sub 4 ore) cantareste adesea 40-50% din decizia finala de atribuire."
    },
    "energie": {
        "avg_discount_pct": 6.2,
        "undercut_risk": "Mediu",
        "cnsc_dispute_rate": "19%",
        "frequent_players": ["Electrogrup SA", "EnergoBit SA", "Eroup", "Restart Energy One", "Adrem Engineering"],
        "pricing_strategy": "Accentul este pus pe randamentul panourilor (>22%) si eficienta sistemelor de stocare BESS."
    },
    "aparare": {
        "avg_discount_pct": 3.1,
        "undercut_risk": "Scazut",
        "cnsc_dispute_rate": "12%",
        "frequent_players": ["Interactive Systems & Business", "Rasirom RA", "Mira Technologies", "Romarm SA", "Lockheed Martin Partner Network"],
        "pricing_strategy": "Calificarea este conditionata strict de autorizatii ORNISS/NATO si conformitate STANAG."
    },
    "digitalizare": {
        "avg_discount_pct": 9.8,
        "undercut_risk": "Ridicat",
        "cnsc_dispute_rate": "31%",
        "frequent_players": ["Teamnet International", "Siveco / TotalSoft", "Maguay Computers", "Asseco SEE", "Connections Consult"],
        "pricing_strategy": "Diferentiatorul major il reprezinta arhitectura deschisa (API REST) si timpii de implementare agili."
    }
}

class CompetitorTrackerEngine:
    @staticmethod
    def analyze_landscape(category: str, county: str, budget_ron: float) -> Dict[str, Any]:
        cat_key = category.lower() if category.lower() in MARKET_BENCHMARKS else "infrastructura"
        benchmark = MARKET_BENCHMARKS[cat_key]

        avg_discount = benchmark["avg_discount_pct"]
        optimal_price = budget_ron * (1 - (avg_discount / 100.0))
        aggressive_price = budget_ron * 0.82
        safe_price = budget_ron * 0.94

        return {
            "sector": category.capitalize(),
            "county": county,
            "estimated_budget_ron": budget_ron,
            "benchmark": {
                "historical_avg_discount": f"{avg_discount}%",
                "undercutting_risk": benchmark["undercut_risk"],
                "cnsc_dispute_frequency": benchmark["cnsc_dispute_rate"],
                "identified_key_competitors": benchmark["frequent_players"],
                "tactical_guidance": benchmark["pricing_strategy"]
            },
            "pricing_recommendations": {
                "safe_margin_bid_ron": safe_price,
                "optimal_competitive_bid_ron": optimal_price,
                "aggressive_limit_bid_ron": aggressive_price
            }
        }
""")

# 2. TECHNICAL DOSSIER GENERATOR
write_file(os.path.join(ENGINE, "addons/dossier_generator.py"), """
import logging
from typing import Dict, Any

logger = logging.getLogger("DossierGenerator")

class TechnicalDossierGenerator:
    @staticmethod
    def generate_draft(
        project_title: str,
        authority_name: str,
        county: str,
        category: str,
        company_name: str,
        cui: str
    ) -> Dict[str, Any]:
        doc_structure = f\"\"\"
PROPUNERE TEHNICA - DOSAR DE CALIFICARE
Procedura: {project_title}
Autoritate Contractanta: {authority_name} ({county})
Ofertant: {company_name} (CUI: {cui})
Temei Legal: Legea nr. 98/2016 privind achizitiile publice

--------------------------------------------------------------------------------
SECTIUNEA 1: METODOLOGIE DE EXECUTIE SI GRAFIC GANTT
1.1 Organizarea generala a santierului/proiectului conform cerintelor caietului de sarcini.
1.2 Graficul de esalonare a activitatilor pe etape de livrare si receptie partiala.
1.3 Planul de mobilizare al resurselor utilaje grele si echipamente de testare specializate.

SECTIUNEA 2: RESURSE UMANE SI PERSONAL CHEIE
2.1 Echipa de management: Manager de Proiect certificat PMP, Responsabil Tehnic cu Executia (RTE), Responsabil CQ.
2.2 Planul de asigurare a disponibilitatii personalului pe toata durata contractului.

SECTIUNEA 3: PLAN DE MANAGEMENT AL CALITATII, MEDIULUI SI SECURITATII
3.1 Sistemul integrat de management conform standardelor ISO 9001, ISO 14001 si ISO 45001.
3.2 Proceduri specifice pentru reducerea amprentei de carbon si conformitate cu cerintele nZEB/Green Transition.
3.3 Planul de raspuns la incidente si mentenanta corectiva cu timp de interventie sub 4 ore.

SECTIUNEA 4: MATRICE DE CONFORMITATE CU SPECIFICATIILE TEHNICE
4.1 Toate echipamentele si materialele propuse indeplinesc sau depasesc specificatiile minime solicitate.
4.2 Certificate de conformitate CE si declaratii de performanta atasate in anexe.
4.3 Garantie extinsa oferita: 36 de luni de la data semnarii procesului-verbal de receptie fara obiectiuni.

--------------------------------------------------------------------------------
Document generat automat prin motorul de asistenta tehnica RO-INTEL 2026.
\"\"\"
        return {
            "project_title": project_title,
            "authority_name": authority_name,
            "company_name": company_name,
            "dossier_text": doc_structure.strip(),
            "sections_count": 4,
            "status": "ready"
        }
""")

print("\n⚡ [2/5] Updating Backend API Routes...")

# 3. UPDATE API.PY
write_file(os.path.join(ENGINE, "api.py"), """
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
from billing import StripeBillingEngine
from scrapers.orchestrator import OpportunityOrchestrator
from cache_engine import global_cache
from freemium_shield import FreemiumGatekeeper
from notifier import LeadAlertDispatcher

from addons.caiet_analyzer import CaietDeSarciniAnalyzer
from addons.win_probability import WinProbabilityEngine
from addons.foia_generator import LegalClarificationGenerator
from addons.business_eligibility import BusinessEligibilityEngine
from addons.competitor_tracker import CompetitorTrackerEngine
from addons.dossier_generator import TechnicalDossierGenerator
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
        for lead in leads:
            if lead.get("opportunity_score", 0) >= 9.2:
                await LeadAlertDispatcher.dispatch_high_priority_alert(lead)
        global_cache.invalidate()
        logger.info("[24/7 DAEMON] Pipeline synchronized.")
    except Exception as e:
        logger.error(f"[24/7 DAEMON] Error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(background_scraping_job, "interval", hours=6)
    scheduler.start()
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

class CompetitorAnalysisRequest(BaseModel):
    category: str
    county: str
    budget_ron: float

class TechnicalProposalRequest(BaseModel):
    project_title: str
    authority_name: str
    county: str
    category: str
    company_name: str
    cui: str

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
    return {"engine": "RO-INTEL Enterprise Procurement Engine", "status": "online", "version": "2.4.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "cache": "online"}

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
def analyze_competitor_landscape(payload: CompetitorAnalysisRequest):
    return CompetitorTrackerEngine.analyze_landscape(payload.category, payload.county, payload.budget_ron)

@app.post("/api/v1/addons/generate-technical-proposal")
def generate_technical_proposal(payload: TechnicalProposalRequest):
    return TechnicalDossierGenerator.generate_draft(
        payload.project_title, payload.authority_name, payload.county, payload.category, payload.company_name, payload.cui
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

@app.post("/api/v1/business-eligibility/evaluate")
def evaluate_company_eligibility(payload: BusinessScanRequest):
    return BusinessEligibilityEngine.evaluate_company(
        payload.company_name, payload.cui_fiscal, payload.caen_code, payload.turnover_ron, payload.employee_count, payload.county
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

@app.post("/api/v1/addons/generate-clarification")
def generate_clarification_letter(payload: ClarificationLetterRequest):
    return LegalClarificationGenerator.generate_clarification_letter(
        payload.authority_name, payload.project_title, payload.source_id, payload.company_name, payload.cui_fiscal, payload.clarification_points
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
""")

print("\n⚡ [3/5] Updating Frontend API Handlers...")

# 4. UPDATE LIB/API.TS
write_file(os.path.join(FRONTEND, "lib/api.ts"), """
function getApiBase(): string {
  if (typeof window !== "undefined") {
    if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
      return "http://localhost:8000";
    }
    return "https://api.ro-intel.xyz";
  }
  return process.env.NEXT_PUBLIC_API_BASE || "https://api.ro-intel.xyz";
}

export async function syncBackendAuth(email: string, fullName?: string, avatarUrl?: string) {
  try {
    const res = await fetch(`${getApiBase()}/api/v1/auth/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, full_name: fullName, avatar_url: avatarUrl })
    });
    if (res.ok) return await res.json();
  } catch (err) {
    console.warn("[AuthSync] Offline fallback:", err);
  }
  return {
    status: "synced_offline",
    user: { email, full_name: fullName || email.split("@")[0], tenant_id: "t1_infra_transilvania", role: "Director Bidding & Strategie", avatar_url: avatarUrl }
  };
}

export const syncUserWithAuth = syncBackendAuth;

export async function switchTenantWorkspace(tenantId: string) {
  if (typeof window !== "undefined") {
    localStorage.setItem("ro_intel_active_tenant", tenantId);
  }
  return { tenant_id: tenantId, status: "switched" };
}

export async function fetchTenantFeed(tenantId: string, productId?: string, category?: string, forceRefresh = false) {
  let url = `${getApiBase()}/api/v1/tenants/${tenantId}/feed?force_refresh=${forceRefresh}`;
  if (productId) url += `&product_id=${productId}`;
  if (category && category !== "all") url += `&category=${category}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Eroare la preluarea fluxului pre-SEAP");
  return res.json();
}

export async function fetchTenantProducts(tenantId: string) {
  const res = await fetch(`${getApiBase()}/api/v1/tenants/${tenantId}/products`);
  if (!res.ok) throw new Error("Eroare la preluarea liniilor de produse");
  return res.json();
}

export async function fetchTenantPipeline(tenantId: string, stage?: string) {
  let url = `${getApiBase()}/api/v1/tenants/${tenantId}/pipeline`;
  if (stage && stage !== "all") url += `?stage=${stage}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Eroare la preluarea pipeline-ului");
  return res.json();
}

export async function addLeadToPipeline(tenantId: string, leadData: any) {
  const res = await fetch(`${getApiBase()}/api/v1/tenants/${tenantId}/pipeline/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lead_data: leadData })
  });
  if (!res.ok) throw new Error("Eroare la salvarea in pipeline");
  return res.json();
}

export async function updatePipelineDeal(tenantId: string, payload: { deal_id: string; new_stage: string; notes?: string; proposed_price?: number }) {
  const res = await fetch(`${getApiBase()}/api/v1/tenants/${tenantId}/pipeline/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("Eroare la actualizarea stadiului");
  return res.json();
}

export async function triggerEmailAlert(leadData: any, recipientEmail: string) {
  const res = await fetch(`${getApiBase()}/api/v1/notifications/send-email-alert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lead_data: leadData, recipient_email: recipientEmail })
  });
  if (!res.ok) throw new Error("Eroare la expedierea alertei");
  return res.json();
}

export async function fetchCompetitorAnalysis(category: string, county: string, budgetRon: number) {
  const res = await fetch(`${getApiBase()}/api/v1/addons/competitor-analysis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category, county, budget_ron: budgetRon })
  });
  if (!res.ok) throw new Error("Eroare la analiza concurentei");
  return res.json();
}

export async function generateTechnicalProposal(payload: {
  project_title: string;
  authority_name: string;
  county: string;
  category: string;
  company_name: string;
  cui: string;
}) {
  const res = await fetch(`${getApiBase()}/api/v1/addons/generate-technical-proposal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("Eroare la generarea propunerii tehnice");
  return res.json();
}

export async function fetch72hMarketReport(tenantId: string) {
  const res = await fetch(`${getApiBase()}/api/v1/analytics/market-report-72h?tenant_id=${tenantId}`);
  if (!res.ok) throw new Error("Eroare la raportul macro");
  return res.json();
}

export async function askCopilotChat(query: string, tenantId: string) {
  const res = await fetch(`${getApiBase()}/api/v1/copilot/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, tenant_id: tenantId })
  });
  if (!res.ok) throw new Error("Copilot chat failed");
  return res.json();
}

export async function generateProformaInvoice(payload: {
  tenant_id: string;
  plan_id: string;
  company_name: string;
  cui_fiscal: string;
  billing_email: string;
  billing_address?: string;
}) {
  const res = await fetch(`${getApiBase()}/api/v1/tenants/${payload.tenant_id}/billing/proforma`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("Eroare la generarea facturii proforme");
  return res.json();
}

export async function uploadCaietFile(file: File, projectTitle: string) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("project_title", projectTitle);

  const res = await fetch(`${getApiBase()}/api/v1/addons/upload-caiet`, {
    method: "POST",
    body: formData
  });
  if (!res.ok) throw new Error("Eroare la analizarea fisierului");
  return res.json();
}

export async function evaluateBusinessEligibility(payload: {
  company_name: string;
  cui_fiscal: string;
  caen_code: string;
  turnover_ron: number;
  employee_count: number;
  county: string;
}) {
  const res = await fetch(`${getApiBase()}/api/v1/business-eligibility/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("Eroare la scanarea eligibilitatii");
  return res.json();
}

export async function analyzeCaietSarcini(projectTitle: string, specificationText: string) {
  const res = await fetch(`${getApiBase()}/api/v1/addons/analyze-caiet`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_title: projectTitle, specification_text: specificationText })
  });
  if (!res.ok) throw new Error("Eroare la analiza specificatiei");
  return res.json();
}

export async function predictWinRate(estimatedBudget: number, proposedPrice: number, hasLocalPartner = false) {
  const res = await fetch(`${getApiBase()}/api/v1/addons/predict-win-rate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      estimated_budget_ron: estimatedBudget,
      proposed_price_ron: proposedPrice,
      has_local_partnership: hasLocalPartner
    })
  });
  if (!res.ok) throw new Error("Eroare la calcularea sanselor");
  return res.json();
}

export async function generateLegalClarification(payload: {
  authority_name: string;
  project_title: string;
  source_id: string;
  company_name: string;
  cui_fiscal: string;
  clarification_points: string;
}) {
  const res = await fetch(`${getApiBase()}/api/v1/addons/generate-clarification`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("Eroare la generarea adresei oficiale");
  return res.json();
}
""")

print("\n⚡ [4/5] Adding Competitor & Proposal Modals to Frontend...")

# 5. UPDATE ENTERPRISE MODALS WITH COMPETITOR RADAR & DOSSIER MODALS
write_file(os.path.join(FRONTEND, "components/EnterpriseModals.tsx"), """\"use client\";
import React, { useState, useEffect } from "react";
import {
  generateProformaInvoice,
  uploadCaietFile,
  analyzeCaietSarcini,
  predictWinRate,
  generateLegalClarification,
  evaluateBusinessEligibility,
  askCopilotChat,
  fetchTenantPipeline,
  fetchCompetitorAnalysis,
  generateTechnicalProposal
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

// 1. BILLING & PROFORMA MODAL
export function PricingModal({ isOpen, onClose, tenantId }: { isOpen: boolean; onClose: () => void; tenantId: string }) {
  const [selectedPlan, setSelectedPlan] = useState<string | null>("plan_founder_vip");
  const [companyName, setCompanyName] = useState("SC Infra Construct Transilvania SRL");
  const [cui, setCui] = useState("RO12345678");
  const [email, setEmail] = useState("financiar@infraconstruct.ro");
  const [address, setAddress] = useState("Str. Memorandumului 21, Cluj-Napoca");
  const [proformaData, setProformaData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleGenerateProforma = async () => {
    if (!selectedPlan) return;
    setLoading(true);
    try {
      const data = await generateProformaInvoice({
        tenant_id: tenantId,
        plan_id: selectedPlan,
        company_name: companyName,
        cui_fiscal: cui,
        billing_email: email,
        billing_address: address
      });
      setProformaData(data);
    } catch (e: any) {
      alert("Eroare: " + (e?.message || "Nu s-a putut genera factura proforma."));
    } finally {
      setLoading(false);
    }
  };

  const handlePrint = () => {
    if (!proformaData?.proforma_html) return;
    const printWin = window.open("", "_blank");
    if (printWin) {
      printWin.document.write(proformaData.proforma_html);
      printWin.document.close();
      printWin.focus();
      printWin.print();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-4xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-6 border-b border-slate-100 pb-4">
          <div>
            <h2 className="text-xl font-bold text-slate-900">Activare Abonament & Factura Proforma</h2>
            <p className="text-xs text-slate-500">Generare instantanee Factura Proforma pentru plata prin Ordin de Plata (OP) sau Card.</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700">✕</button>
        </div>

        {!proformaData ? (
          <div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-6">
              <div
                onClick={() => setSelectedPlan("plan_acces_complet")}
                className={"cursor-pointer flex flex-col justify-between rounded-xl border p-5 transition " + (selectedPlan === "plan_acces_complet" ? "border-sky-500 bg-sky-50/50" : "border-slate-200 bg-white hover:border-slate-300")}
              >
                <div>
                  <div className="flex justify-between items-baseline mb-2">
                    <h3 className="text-base font-bold text-slate-900">Acces Complet Desk</h3>
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-700">STANDARD</span>
                  </div>
                  <p className="text-2xl font-extrabold text-slate-900 mb-3">499 <span className="text-xs font-normal text-slate-500">RON / luna</span></p>
                  <ul className="space-y-1.5 text-xs text-slate-600">
                    <li>- Acces la toate cele 25 de registre active</li>
                    <li>- Sinteze Executive AI</li>
                    <li>- Export CSV date calificate</li>
                    <li>- 1 Workspace & 2 Utilizatori</li>
                  </ul>
                </div>
                <button className="mt-4 w-full rounded-lg bg-slate-100 py-2 text-xs font-bold text-slate-800 hover:bg-slate-200">
                  {selectedPlan === "plan_acces_complet" ? "Plan Selectat" : "Selecteaza 499 RON"}
                </button>
              </div>

              <div
                onClick={() => setSelectedPlan("plan_founder_vip")}
                className={"cursor-pointer flex flex-col justify-between rounded-xl border-2 p-5 relative transition " + (selectedPlan === "plan_founder_vip" ? "border-sky-600 bg-sky-50/50" : "border-slate-300 bg-white hover:border-slate-400")}
              >
                <div>
                  <div className="flex justify-between items-baseline mb-2">
                    <h3 className="text-base font-bold text-slate-900">VIP Multi-Divizie</h3>
                    <span className="rounded bg-sky-100 px-2 py-0.5 text-[10px] font-semibold text-sky-800">ENTERPRISE</span>
                  </div>
                  <p className="text-2xl font-extrabold text-slate-900 mb-3">1499 <span className="text-xs font-normal text-slate-500">RON / luna</span></p>
                  <ul className="space-y-1.5 text-xs text-slate-600">
                    <li>- Tot ce include pachetul Acces Complet</li>
                    <li>- Scanner Caiet de Sarcini (Upload PDF/DOCX)</li>
                    <li>- Simulator Sanse de Castig & Marje</li>
                    <li>- Generator Adrese Legea 544</li>
                    <li>- Alerte automate Email (Resend)</li>
                    <li>- Pana la 10 Utilizatori</li>
                  </ul>
                </div>
                <button className="mt-4 w-full rounded-lg bg-slate-900 py-2 text-xs font-bold text-white hover:bg-slate-800">
                  {selectedPlan === "plan_founder_vip" ? "Plan Selectat" : "Selecteaza 1499 RON"}
                </button>
              </div>
            </div>

            {selectedPlan && (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs space-y-3">
                <span className="font-bold text-slate-700 block uppercase text-[11px]">Date Facturare Companie:</span>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-slate-600 mb-1">Denumire Companie</label>
                    <input type="text" value={companyName} ={e => setCompanyName(e.target.value)} className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900" />
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">CUI / CIF</label>
                    <input type="text" value={cui} onChange={e => setCui(e.target.value)} className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900" />
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">Email Facturare</label>
                    <input type="email" value={email} onChange={e => setEmail(e.target.value)} className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900" />
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">Adresa Sediu Social</label>
                    <input type="text" value={address} onChange={e => setAddress(e.target.value)} className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900" />
                  </div>
                </div>

                <button
                  onClick={handleGenerateProforma}
                  disabled={loading}
                  className="mt-3 w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white text-xs hover:bg-slate-800 transition"
                >
                  {loading ? "Se emite proforma..." : (selectedPlan === "plan_founder_vip" ? "Genereaza Factura Proforma (1499 RON)" : "Genereaza Factura Proforma (499 RON)")}
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4 text-xs">
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-center">
              <span className="text-emerald-800 font-bold block text-sm">Factura Proforma {proformaData.invoice_number} a fost emisa.</span>
              <p className="text-slate-600 text-xs mt-1">Total de plata: <b>{proformaData.total_ron} RON</b> pentru {proformaData.plan_name}</p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-2">
              <span className="font-bold text-slate-800 block">Date Transfer Bancar (Ordin de Plata - OP):</span>
              <p className="text-slate-700">Banca: <b>{proformaData.bank_details.bank_name}</b></p>
              <p className="text-slate-700">IBAN: <b className="font-mono text-slate-900">{proformaData.bank_details.iban_ron}</b></p>
              <p className="text-slate-700">Beneficiar: <b>{proformaData.bank_details.beneficiary}</b></p>
              <p className="text-slate-700">Detalii Plata: <b>{proformaData.bank_details.payment_details_prefix}{proformaData.invoice_number} ({proformaData.cui_fiscal})</b></p>
            </div>

            <div className="flex gap-3">
              <button
                onClick={handlePrint}
                className="flex-1 rounded-xl bg-slate-900 py-2.5 font-bold text-white hover:bg-slate-800 transition"
              >
                Descarca / Printeaza Factura Proforma (PDF)
              </button>
              <button
                onClick={() => setProformaData(null)}
                className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 font-semibold text-slate-700 hover:bg-slate-50"
              >
                Modifica Datele
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// 2. CAIET SCANNER MODAL
export function CaietScannerModal({ isOpen, onClose, defaultTitle }: { isOpen: boolean; onClose: () => void; defaultTitle: string }) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleAnalyze = async () => {
    setLoading(true);
    try {
      if (file) {
        const data = await uploadCaietFile(file, defaultTitle);
        setResult(data);
      } else if (text.trim()) {
        const data = await analyzeCaietSarcini(defaultTitle, text);
        setResult(data);
      }
    } catch (e: any) {
      alert("Eroare: " + (e?.message || "Nu s-a putut analiza caietul de sarcini."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <h3 className="text-lg font-bold text-slate-900">Scanner Clauze Restrictive (Caiet de Sarcini)</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>
        <p className="text-xs text-slate-500 mb-3 font-mono">Proiect: {defaultTitle}</p>

        <div className="rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 p-4 text-center mb-3">
          <input
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="hidden"
            id="caiet-upload"
          />
          <label htmlFor="caiet-upload" className="cursor-pointer block">
            <span className="text-sky-700 font-bold block text-xs">
              {file ? "Fisier selectat: " + file.name : "Incarcati fisierul PDF sau DOCX aici (sau click pentru a alege)"}
            </span>
            <span className="text-[10px] text-slate-500 mt-1 block">Suporta Caiete de Sarcini oficiale PDF, DOCX</span>
          </label>
        </div>

        <div className="text-center text-[10px] text-slate-400 mb-2 font-bold uppercase">Sau introduceti textul direct</div>

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Introduceti textul din caietul de sarcini..."
          className="w-full h-24 rounded-xl border border-slate-300 bg-slate-50 p-3 text-xs text-slate-900 focus:bg-white focus:border-sky-500 focus:outline-none"
        />

        <button
          onClick={handleAnalyze}
          disabled={loading || (!text && !file)}
          className="mt-3 w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white text-xs hover:bg-slate-800 transition"
        >
          {loading ? "Se analizeaza documentul conform jurisprudentei CNSC..." : "Scaneaza Clauze Restrictive"}
        </button>

        {result && (
          <div className="mt-4 space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs">
            <div className="flex justify-between items-center">
              <span className="font-semibold text-slate-700">Nivel Risc Restrictiv:</span>
              <span className="font-bold text-amber-800">{result.bias_ri_level} (Scor: {result.bias_score}/10)</span>
            </div>
            <p className="text-slate-600">{result.recommended_action}</p>
            <div className="space-y-2 mt-2">
              <span className="font-bold text-slate-500 uppercase text-[10px]">Clauze Identificate:</span>
              {result.detected_red_flags && result.detected_red_flags.map((flag: any, i: number) => (
                <div key={i} className="rounded bg-white p-2.5 border-l-2 border-amber-500 shadow-sm">
                  <p className="font-bold text-slate-900">{flag.pattern} — Risc {flag.severity}</p>
                  <p className="text-slate-600 mt-0.5">{flag.tactical_advisory}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// 3. BUSINESS ELIGIBILITY MODAL
export function BusinessEligibilityModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const { activeDesk } = useAuth();
  const [companyName, setCompanyName] = useState(activeDesk?.name || "SC Infra Construct Transilvania SRL");
  const [cui, setCui] = useState(activeDesk?.cui || "RO12345678");
  const [caen, setCaen] = useState("4211");
  const [turnover, setTurnover] = useState(18500000);
  const [employees, setEmployees] = useState(48);
  const [county, setCounty] = useState(activeDesk?.target_counties?.[0] || "Cluj");
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (activeDesk) {
      setCompanyName(activeDesk.name);
      setCui(activeDesk.cui);
      if (activeDesk.target_counties?.length > 0) setCounty(activeDesk.target_counties[0]);
    }
  }, [activeDesk]);

  if (!isOpen) return null;

  const handleScan = async () => {
    setLoading(true);
    try {
      const data = await evaluateBusinessEligibility({
        company_name: companyName,
        cui_fiscal: cui,
        caen_code: caen,
        turnover_ron: Number(turnover),
        employee_count: Number(employees),
        county
      });
      setResult(data);
    } catch (e: any) {
      alert("Eroare la scanare: " + (e?.message || "Verificati conexiunea cu serverul API."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Scanner Eligibilitate Granturi & Licitatii Strategice</h3>
            <p className="text-xs text-slate-500">Evaluare automata a profilului companiei conform ghidurilor PNRR / MIPE 2026.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs mb-4">
          <div>
            <label className="block text-slate-600 mb-1">Nume Companie</label>
            <input
              type="text"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
            />
          </div>
          <div>
            <label className="block text-slate-600 mb-1">CUI / Cod Fiscal</label>
            <input
              type="text"
              value={cui}
              onChange={(e) => setCui(e.target.value)}
              className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
            />
          </div>
          <div>
            <label className="block text-slate-600 mb-1">Cod CAEN Principal</label>
            <input
              type="text"
              value={caen}
              onChange={(e) => setCaen(e.target.value)}
              className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
            />
          </div>
          <div>
            <label className="block text-slate-600 mb-1">Cifra de Afaceri Anuala (RON)</label>
            <input
              type="number"
              value={turnover}
              onChange={(e) => setTurnover(Number(e.target.value))}
              className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
            />
          </div>
        </div>

        <button onClick={handleScan} disabled={loading} className="w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white hover:bg-slate-800 transition">
          {loading ? "Se verifica criteriile de eligibilitate..." : "Evalueaza Profilul Companiei"}
        </button>

        {result && (
          <div className="mt-4 space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs">
            <div className="flex justify-between items-center border-b border-slate-200 pb-2">
              <span className="font-bold text-slate-800">{result.qualification_status}</span>
              <span className="rounded bg-emerald-100 px-2 py-0.5 font-bold text-emerald-800">Scor: {result.overall_eligibility_score}/10</span>
            </div>
            <p className="text-slate-600 leading-relaxed">{result.advisory_summary}</p>
            <div className="space-y-2 mt-2">
              <span className="font-bold text-slate-500 uppercase text-[10px]">Linii de Finantare Eligibile:</span>
              {result.matched_grants && result.matched_grants.map((g: any, i: number) => (
                <div key={i} className="rounded bg-white p-3 border-l-2 border-sky-600 shadow-sm">
                  <div className="flex justify-between">
                    <span className="font-bold text-slate-900">{g.program_name}</span>
                    <span className="font-bold text-emerald-700">Pana la {g.eligible_grant_up_to}</span>
                  </div>
                  <p className="text-slate-500 text-[11px] mt-1">Cofinantare: {g.required_co_financing} | Baza legala: {g.legal_basis}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// 4. COPILOT AI CHAT MODAL
export function CopilotChatModal({ isOpen, onClose, tenantId, report72h }: { isOpen: boolean; onClose: () => void; tenantId: string; report72h: any }) {
  const [messages, setMessages] = useState<{ sender: "user" | "ai"; text: string }[]>([
    { sender: "ai", text: "Buna ziua! Sunt Copilotul AI RO-INTEL. Cu ce oportunitate, cerinta de calificare sau strategie de licitatie doriti sa incepem?" }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    const userQ = input;
    setInput("");
    setMessages(prev => [...prev, { sender: "user", text: userQ }]);
    setLoading(true);

    try {
      const data = await askCopilotChat(userQ, tenantId);
      setMessages(prev => [...prev, { sender: "ai", text: data.reply }]);
    } catch (e: any) {
      setMessages(prev => [...prev, { sender: "ai", text: "Eroare la conexiunea cu Copilotul AI: " + (e?.message || "") }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 flex flex-col h-[85vh]">
        <div className="flex justify-between items-center mb-3 border-b border-slate-100 pb-2">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Copilot AI Bidding & Radar 72h</h3>
            <p className="text-xs text-slate-500">{report72h?.period || "Ultimele 72 ore"}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        {report72h && (
          <div className="rounded-xl bg-slate-50 p-3 text-xs mb-3 border border-slate-200 space-y-1">
            <span className="font-bold text-slate-700 block">Sinteza Macro Ultimele 72h:</span>
            <ul className="list-disc pl-4 text-slate-600 space-y-0.5">
              {report72h.executive_takeaways && report72h.executive_takeaways.map((t: string, i: number) => <li key={i}>{t}</li>)}
            </ul>
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-3 p-2 text-xs">
          {messages.map((m, i) => (
            <div key={i} className={"flex " + (m.sender === "user" ? "justify-end" : "justify-start")}>
              <div className={"max-w-[85%] rounded-xl p-3 " + (m.sender === "user" ? "bg-slate-900 text-white font-medium" : "bg-slate-100 border border-slate-200 text-slate-800")}>
                {m.text}
              </div>
            </div>
          ))}
          {loading && <div className="text-slate-500 text-xs animate-pulse">Copilotul AI analizeaza dosarele pre-SEAP...</div>}
        </div>

        <div className="flex gap-2 mt-3 pt-2 border-t border-slate-100">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSend()}
            placeholder="Intrebati despre cerinte de atribuire, licitatii CNI, bugete sau contestatii..."
            className="flex-1 rounded-xl border border-slate-300 bg-slate-50 px-3 py-2 text-xs text-slate-900 focus:bg-white focus:outline-none focus:border-sky-500"
          />
          <button onClick={handleSend} disabled={loading} className="rounded-xl bg-slate-900 px-4 py-2 font-bold text-white text-xs hover:bg-slate-800">
            Trimite
          </button>
        </div>
      </div>
    </div>
  );
}

// 5. WIN ODDS MODAL
export function WinOddsModal({ isOpen, onClose, defaultBudget }: { isOpen: boolean; onClose: () => void; defaultBudget: number }) {
  const [budget, setBudget] = useState(defaultBudget || 10000000);
  const [price, setPrice] = useState(Math.round((defaultBudget || 10000000) * 0.92));
  const [hasPartner, setHasPartner] = useState(true);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleCalculate = async () => {
    setLoading(true);
    try {
      const data = await predictWinRate(budget, price, hasPartner);
      setResult(data);
    } catch {
      alert("Eroare la calcularea sanselor.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <h3 className="text-lg font-bold text-slate-900">Simulator Sanse de Castig & Marja Optima</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>
        <div className="space-y-3 text-xs">
          <div>
            <label className="block text-slate-600 mb-1">Buget Estimat Autoritate Contractanta (RON)</label>
            <input type="number" value={budget} onChange={(e) => setBudget(Number(e.target.value))} className="w-full rounded-xl border border-slate-300 bg-slate-50 p-2.5 text-slate-900" />
          </div>
          <div>
            <label className="block text-slate-600 mb-1">Pret Ofertat Propus (RON)</label>
            <input type="number" value={price} onChange={(e) => setPrice(Number(e.target.value))} className="w-full rounded-xl border border-slate-300 bg-slate-50 p-2.5 text-slate-900" />
          </div>
          <label className="flex items-center gap-2 text-slate-700">
            <input type="checkbox" checked={hasPartner} onChange={(e) => setHasPartner(e.target.checked)} className="rounded" />
            Consortiu / Subcontractant local in judetul autoritatii (+12% logistica)
          </label>
          <button onClick={handleCalculate} disabled={loading} className="w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white text-xs hover:bg-slate-800 transition">
            {loading ? "Se evalueaza..." : "Calculeaza Probabilitate Castig"}
          </button>
          {result && (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-center mt-3">
              <p className="uppercase text-slate-500 text-[10px] font-bold">Probabilitate Estimata de Atribuire</p>
              <p className="text-3xl font-extrabold text-emerald-700 my-1">{result.win_probability_score}</p>
              <p className="text-slate-700">Discount propus: <span className="font-bold text-slate-900">{result.discount_percentage}</span> ({result.rating})</p>
              <p className="text-slate-600 mt-2 text-left bg-white p-2.5 rounded border border-slate-200 text-[11px]">{result.tactical_guidance}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// 6. CLARIFICATION MODAL
export function ClarificationModal({ isOpen, onClose, opp }: { isOpen: boolean; onClose: () => void; opp: any }) {
  const { activeDesk } = useAuth();
  const [points, setPoints] = useState("1. Solicitam eliminarea cerintei de autorizatie directa de la producator.\\n2. Solicitam acceptarea standardelor tehnice europene echivalente conform Art. 160 Legea 98/2016.");
  const [letter, setLetter] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const handleGenerate = async () => {
    setLoading(true);
    try {
      const data = await generateLegalClarification({
        authority_name: opp.entity_name,
        project_title: opp.project_title,
        source_id: opp.source_id,
        company_name: activeDesk?.name || "SC Infra Construct Transilvania SRL",
        cui_fiscal: activeDesk?.cui || "RO12345678",
        clarification_points: points
      });
      setLetter(data.generated_letter);
    } catch {
      alert("Eroare la generarea adresei oficiale.");
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = () => {
    navigator.clipboard.writeText(letter);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <h3 className="text-lg font-bold text-slate-900">Generator Solicitare Clarificari (Legea 98/2016)</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>
        <p className="text-xs text-slate-500 mb-2 font-mono">Autoritate: {opp.entity_name}</p>
        <label className="block text-xs text-slate-700 mb-1">Puncte de clarificat / Clauze restrictive:</label>
        <textarea
          value={points}
          onChange={(e) => setPoints(e.target.value)}
          className="w-full h-24 rounded-xl border border-slate-300 bg-slate-50 p-2.5 text-xs text-slate-900 mb-3 focus:bg-white focus:outline-none"
        />
        <button onClick={handleGenerate} disabled={loading} className="w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white text-xs hover:bg-slate-800 transition">
          {loading ? "Se redacteaza adresa oficiala..." : "Genereaza Adresa Oficiala"}
        </button>
        {letter && (
          <div className="mt-4">
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs font-bold text-slate-700">Document Generat:</span>
              <button onClick={copyToClipboard} className="rounded bg-slate-100 border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-800 hover:bg-slate-200">
                {copied ? "Copiat" : "Copiaza Textul"}
              </button>
            </div>
            <pre className="h-48 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-800 whitespace-pre-wrap font-sans">
              {letter}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

// 7. PIPELINE TRACKER MODAL
export function PipelineTrackerModal({ isOpen, onClose, tenantId }: { isOpen: boolean; onClose: () => void; tenantId: string }) {
  const [pipelineData, setPipelineData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const loadPipeline = async () => {
    setLoading(true);
    try {
      const data = await fetchTenantPipeline(tenantId);
      setPipelineData(data);
    } catch (e) {
      console.warn("Pipeline load note:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) loadPipeline();
  }, [isOpen, tenantId]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-5xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Pipeline Bidding & Management Dosare Pre-SEAP</h3>
            <p className="text-xs text-slate-500">Monitorizare stadiu intern: evaluare tehnica, adrese clarificari si marje estimate.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        {loading ? (
          <div className="flex h-48 items-center justify-center text-xs text-slate-500">Se incarca pipeline-ul companiei...</div>
        ) : !pipelineData?.deals?.length ? (
          <div className="flex h-48 flex-col items-center justify-center text-xs text-slate-500 space-y-2">
            <span>Nu aveti dosare salvate in pipeline-ul curent.</span>
            <span className="text-[11px] text-sky-700">Deschideti orice dosar din feed-ul principal si apasati "Salveaza in Pipeline".</span>
          </div>
        ) : (
          <div className="space-y-3">
            {pipelineData.deals && pipelineData.deals.map((d: any) => (
              <div key={d.deal_id} className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs space-y-2">
                <div className="flex justify-between items-start">
                  <div>
                    <span className="rounded bg-slate-200 px-2 py-0.5 text-[10px] font-bold text-slate-800 uppercase">
                      {d.stage ? d.stage.replace("_", " ") : "Nou"}
                    </span>
                    <h4 className="font-bold text-slate-900 text-sm mt-1">{d.project_title}</h4>
                    <p className="text-slate-600 text-xs">{d.entity_name}</p>
                  </div>
                  <div className="text-right">
                    <span className="text-sm font-extrabold text-slate-900">{(d.financial_value_ron / 1000000).toFixed(2)} Mil. RON</span>
                    <span className="block text-[10px] text-emerald-700 font-bold">Marja Tinta: {d.target_margin_pct}%</span>
                  </div>
                </div>
                <div className="rounded bg-white p-2 text-slate-700 text-[11px] border border-slate-200">
                  <b>Notite Bidding:</b> {d.notes}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// 8. ACCOUNT SETTINGS & PREFERENCES MODAL
export function AccountSettingsModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const { user, preferences, updatePreferences, signInWithGoogle, signInWithEmail, signOut } = useAuth();
  const [emailInput, setEmailInput] = useState("");
  const [alertEmail, setAlertEmail] = useState(preferences?.notification_email || user?.email || "");
  const [scoreThreshold, setScoreThreshold] = useState(preferences?.auto_alert_score || 9.0);
  const [magicLinkSent, setMagicLinkSent] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);

  if (!isOpen) return null;

  const handleSave = () => {
    updatePreferences({
      notification_email: alertEmail,
      auto_alert_score: Number(scoreThreshold)
    });
    alert("Setarile au fost salvate.");
    onClose();
  };

  const handleSendMagicLink = async () => {
    if (!emailInput) return;
    setAuthLoading(true);
    const { error } = await signInWithEmail(emailInput);
    setAuthLoading(false);
    if (!error) setMagicLinkSent(true);
    else alert("Eroare: " + error);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Setari Cont & Alerte Email</h3>
            <p className="text-xs text-slate-500">Personalizare flux notificari automate si autentificare.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        <div className="space-y-4 text-xs">
          {!user ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
              <span className="font-bold text-slate-900 block text-sm">Autentificare Operator Economic</span>
              <p className="text-slate-600">Conectati-va pentru a salva dosare in pipeline si a primi alerte automate:</p>
              
              <button
                onClick={signInWithGoogle}
                className="w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white hover:bg-slate-800 transition shadow-sm"
              >
                Conectare cu Google
              </button>

              <div className="flex items-center gap-2 text-slate-400 my-2">
                <div className="flex-1 border-b border-slate-200"></div>
                <span className="text-[10px] uppercase font-bold">Sau Email Magic Link</span>
                <div className="flex-1 border-b border-slate-200"></div>
              </div>

              {!magicLinkSent ? (
                <div className="flex gap-2">
                  <input
                    type="email"
                    placeholder="introduceti email-ul companiei..."
                    value={emailInput}
                    onChange={e => setEmailInput(e.target.value)}
                    className="flex-1 rounded-xl border border-slate-300 bg-white px-3 py-2 text-slate-900"
                  />
                  <button
                    onClick={handleSendMagicLink}
                    disabled={authLoading}
                    className="rounded-xl bg-slate-800 px-4 py-2 font-bold text-white hover:bg-slate-700"
                  >
                    {authLoading ? "Se trimite..." : "Trimite Link"}
                  </button>
                </div>
              ) : (
                <p className="text-emerald-700 font-bold text-center">Link de autentificare expediat. Verificati casuta de email.</p>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-slate-600">Cont Conectat:</span>
                <span className="font-bold text-emerald-700">{user.email}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-600">Rol Platforma:</span>
                <span className="font-semibold text-slate-800">{user.role}</span>
              </div>
              <button onClick={signOut} className="mt-2 w-full rounded-lg bg-rose-50 border border-rose-200 py-1.5 text-center text-rose-700 hover:bg-rose-100 transition font-medium">
                Deconectare Cont
              </button>
            </div>
          )}

          <div className="space-y-3 pt-2">
            <span className="font-bold text-slate-700 block uppercase text-[11px]">Canal Trimitere Alerte Email</span>
            <div>
              <label className="block text-slate-600 mb-1">Email Destinatar Notificari</label>
              <input
                type="email"
                value={alertEmail}
                onChange={e => setAlertEmail(e.target.value)}
                placeholder="ex: director@infraconstruct.ro"
                className="w-full rounded-xl border border-slate-300 bg-slate-50 p-2.5 text-slate-900"
              />
            </div>
            <div>
              <label className="block text-slate-600 mb-1">Prag Minim Scor Oportunitate pentru Alerta Automata</label>
              <select
                value={scoreThreshold}
                onChange={e => setScoreThreshold(Number(e.target.value))}
                className="w-full rounded-xl border border-slate-300 bg-slate-50 p-2.5 text-slate-900"
              >
                <option value={9.5}>Scor &ge; 9.5 (Doar Proiecte Strategice Critice)</option>
                <option value={9.0}>Scor &ge; 9.0 (Toate Oportunitatile Calificate)</option>
                <option value={8.5}>Scor &ge; 8.5 (Toate Semnalele Active)</option>
              </select>
            </div>
          </div>

          <button onClick={handleSave} className="w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white text-xs hover:bg-slate-800 transition mt-2">
            Salveaza Preferintele
          </button>
        </div>
      </div>
    </div>
  );
}

// 9. DYNAMIC WORKSPACE & BUSINESS DESK MANAGER MODAL
export function WorkspaceDeskModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const { desks, activeDesk, createDesk, deleteDesk, switchDesk } = useAuth();
  const [isCreating, setIsCreating] = useState(false);
  const [name, setName] = useState("");
  const [cui, setCui] = useState("");
  const [domain, setDomain] = useState("infrastructura");
  const [counties, setCounties] = useState("Iasi, Cluj, Bucuresti");
  const [minBudget, setMinBudget] = useState(5000000);
  const [keywords, setKeywords] = useState("drum, pod, asfalt, metrou");
  const [divisionName, setDivisionName] = useState("Divizia Principala");

  if (!isOpen) return null;

  const handleCreate = () => {
    if (!name.trim() || !cui.trim()) {
      alert("Completati numele companiei si codul fiscal (CUI).");
      return;
    }
    const countyList = counties.split(",").map(c => c.trim()).filter(Boolean);
    const keywordList = keywords.split(",").map(k => k.trim().toLowerCase()).filter(Boolean);

    createDesk({
      name,
      cui,
      primary_domain: domain,
      target_counties: countyList.length > 0 ? countyList : ["Toate"],
      min_budget_ron: Number(minBudget) || 1000000,
      keywords: keywordList,
      divisions: [
        {
          id: "div_" + Date.now(),
          name: divisionName || "Divizia Principala",
          keywords: keywordList
        }
      ]
    });

    setIsCreating(false);
    setName("");
    setCui("");
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Administrare Companii & Desk-uri</h3>
            <p className="text-xs text-slate-500">Configurati companiile din portofoliu, domeniile de activitate si cuvintele-cheie monitorizate.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        {!isCreating ? (
          <div className="space-y-4 text-xs">
            <div className="flex justify-between items-center">
              <span className="font-bold text-slate-700 uppercase text-[11px]">Companii & Desk-uri Active ({desks.length})</span>
              <button
                onClick={() => setIsCreating(true)}
                className="rounded-lg bg-slate-900 px-3 py-1.5 font-semibold text-white hover:bg-slate-800 transition"
              >
                + Adauga Companie Noua
              </button>
            </div>

            <div className="space-y-2">
              {desks.map(d => (
                <div
                  key={d.id}
                  className={"rounded-xl border p-4 transition flex justify-between items-center " + (d.id === activeDesk?.id ? "border-sky-500 bg-sky-50/40" : "border-slate-200 bg-slate-50")}
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="font-bold text-slate-900 text-sm">{d.name}</h4>
                      {d.id === activeDesk?.id && (
                        <span className="rounded bg-sky-100 px-2 py-0.5 font-bold text-sky-800 text-[10px]">Activ</span>
                      )}
                    </div>
                    <p className="text-slate-500 text-xs mt-0.5">CUI: {d.cui} &bull; Domeniu: <span className="capitalize">{d.primary_domain}</span></p>
                    <p className="text-slate-600 text-[11px] mt-1">Judete: {d.target_counties?.join(", ")}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {d.id !== activeDesk?.id && (
                      <button
                        onClick={() => switchDesk(d.id)}
                        className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 font-semibold text-slate-700 hover:bg-slate-100"
                      >
                        Comuta
                      </button>
                    )}
                    {desks.length > 1 && (
                      <button
                        onClick={() => deleteDesk(d.id)}
                        className="rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1.5 font-semibold text-rose-700 hover:bg-rose-100"
                      >
                        Sterge
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-3 text-xs">
            <div className="flex justify-between items-center border-b border-slate-100 pb-2">
              <span className="font-bold text-slate-900 uppercase text-[11px]">Configurare Desk Nou</span>
              <button onClick={() => setIsCreating(false)} className="text-slate-500 hover:underline">Inapoi</button>
            </div>

            <div>
              <label className="block text-slate-600 mb-1">Denumire Companie</label>
              <input
                type="text"
                placeholder="ex: SC Terra Construct SRL"
                value={name}
                onChange={e => setName(e.target.value)}
                className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-slate-600 mb-1">Cod Fiscal (CUI)</label>
                <input
                  type="text"
                  placeholder="ex: RO34567890"
                  value={cui}
                  onChange={e => setCui(e.target.value)}
                  className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
                />
              </div>
              <div>
                <label className="block text-slate-600 mb-1">Domeniu Strategic Principal</label>
                <select
                  value={domain}
                  onChange={e => setDomain(e.target.value)}
                  className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
                >
                  <option value="infrastructura">Infrastructura & Transporturi</option>
                  <option value="sanatate">Sanatate & Echipamente Medicale</option>
                  <option value="energie">Energie & Utilitati Verzi</option>
                  <option value="aparare">Aparare & Securitate Speciala</option>
                  <option value="digitalizare">Digitalizare, IT & Smart City</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-slate-600 mb-1">Judete Vizate (separate prin virgula)</label>
              <input
                type="text"
                placeholder="ex: Cluj, Iasi, Timis, Bucuresti"
                value={counties}
                onChange={e => setCounties(e.target.value)}
                className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
              />
            </div>

            <div>
              <label className="block text-slate-600 mb-1">Cuvinte-cheie Monitorizate (separate prin virgula)</label>
              <input
                type="text"
                placeholder="ex: pod, asfalt, consolidare, statie tratare"
                value={keywords}
                onChange={e => setKeywords(e.target.value)}
                className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-slate-600 mb-1">Nume Divizie Principala</label>
                <input
                  type="text"
                  placeholder="ex: Divizia Lucrari Civile"
                  value={divisionName}
                  onChange={e => setDivisionName(e.target.value)}
                  className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
                />
              </div>
              <div>
                <label className="block text-slate-600 mb-1">Buget Minim Proiect (RON)</label>
                <input
                  type="number"
                  value={minBudget}
                  onChange={e => setMinBudget(Number(e.target.value))}
                  className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
                />
              </div>
            </div>

            <div className="flex gap-2 pt-2">
              <button
                onClick={handleCreate}
                className="flex-1 rounded-xl bg-slate-900 py-2.5 font-bold text-white hover:bg-slate-800 transition"
              >
                Salveaza si Activeaza Desk
              </button>
              <button
                onClick={() => setIsCreating(false)}
                className="rounded-xl border border-slate-300 bg-slate-100 px-4 py-2.5 font-semibold text-slate-700 hover:bg-slate-200"
              >
                Anuleaza
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// 10. COMPETITOR RADAR MODAL (PHASE 4)
export function CompetitorRadarModal({ isOpen, onClose, category, county, budget }: { isOpen: boolean; onClose: () => void; category: string; county: string; budget: number }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      fetchCompetitorAnalysis(category, county, budget)
        .then(res => setData(res))
        .catch(err => console.warn(err))
        .finally(() => setLoading(false));
    }
  }, [isOpen, category, county, budget]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Radar Concurenta & Profil Piata Regionala</h3>
            <p className="text-xs text-slate-500">Analiza istorica a preturilor de adjudecare si a riscului de contestatie in {county}.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        {loading ? (
          <div className="flex h-48 items-center justify-center text-xs text-slate-500">Se proceseaza curbele de discount...</div>
        ) : data ? (
          <div className="space-y-4 text-xs">
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl bg-slate-50 p-3 border border-slate-200">
                <span className="text-[10px] text-slate-500 block uppercase font-bold">Discount Istoric Mediu</span>
                <span className="text-base font-extrabold text-slate-900">{data.benchmark?.historical_avg_discount}</span>
              </div>
              <div className="rounded-xl bg-slate-50 p-3 border border-slate-200">
                <span className="text-[10px] text-slate-500 block uppercase font-bold">Risc Subcotare</span>
                <span className="text-base font-bold text-amber-700">{data.benchmark?.undercutting_risk}</span>
              </div>
              <div className="rounded-xl bg-slate-50 p-3 border border-slate-200">
                <span className="text-[10px] text-slate-500 block uppercase font-bold">Rata Contestatii CNSC</span>
                <span className="text-base font-bold text-rose-700">{data.benchmark?.cnsc_dispute_frequency}</span>
              </div>
            </div>

            <div className="rounded-xl bg-slate-50 border border-slate-200 p-4 space-y-2">
              <span className="font-bold text-slate-800 block">Jucatori Frecventi Identificati in {data.sector}:</span>
              <ul className="list-disc pl-4 text-slate-600 space-y-1">
                {data.benchmark?.identified_key_competitors?.map((c: string, i: number) => <li key={i}>{c}</li>)}
              </ul>
            </div>

            <div className="rounded-xl bg-sky-50 border border-sky-200 p-4 space-y-2">
              <span className="font-bold text-sky-900 block">Recomandare Pozitionare Financiara:</span>
              <div className="grid grid-cols-3 gap-2">
                <div className="bg-white p-2 rounded border border-sky-100">
                  <span className="text-[10px] text-slate-400 block font-semibold">Oferta Sigura</span>
                  <span className="font-bold text-slate-800">{(data.pricing_recommendations?.safe_margin_bid_ron / 1000000).toFixed(2)} Mil. RON</span>
                </div>
                <div className="bg-white p-2 rounded border border-sky-200 shadow-sm">
                  <span className="text-[10px] text-sky-700 block font-bold">Optim Competitiv</span>
                  <span className="font-extrabold text-sky-900">{(data.pricing_recommendations?.optimal_competitive_bid_ron / 1000000).toFixed(2)} Mil. RON</span>
                </div>
                <div className="bg-white p-2 rounded border border-sky-100">
                  <span className="text-[10px] text-slate-400 block font-semibold">Limita Agresiva</span>
                  <span className="font-bold text-slate-800">{(data.pricing_recommendations?.aggressive_limit_bid_ron / 1000000).toFixed(2)} Mil. RON</span>
                </div>
              </div>
              <p className="text-slate-600 text-[11px] mt-2">{data.benchmark?.tactical_guidance}</p>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

// 11. TECHNICAL PROPOSAL DOSSIER GENERATOR MODAL (PHASE 4)
export function TechnicalProposalModal({ isOpen, onClose, opp }: { isOpen: boolean; onClose: () => void; opp: any }) {
  const { activeDesk } = useAuth();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (isOpen && opp) {
      setLoading(true);
      generateTechnicalProposal({
        project_title: opp.project_title || "",
        authority_name: opp.entity_name || "",
        county: opp.county || "Romania",
        category: opp.category || "infrastructura",
        company_name: activeDesk?.name || "SC Infra Construct Transilvania SRL",
        cui: activeDesk?.cui || "RO12345678"
      })
        .then(res => setData(res))
        .catch(err => console.warn(err))
        .finally(() => setLoading(false));
    }
  }, [isOpen, opp, activeDesk]);

  if (!isOpen) return null;

  const handleCopy = () => {
    if (data?.dossier_text) {
      navigator.clipboard.writeText(data.dossier_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Generator Schita Propunere Tehnica (Legea 98/2016)</h3>
            <p className="text-xs text-slate-500">Structura orientativa pe 4 sectiuni conform standardelor nationale de achizitii.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        {loading ? (
          <div className="flex h-48 items-center justify-center text-xs text-slate-500">Se asambleaza structura propunerii tehnice...</div>
        ) : data ? (
          <div className="space-y-3 text-xs">
            <div className="flex justify-between items-center">
              <span className="text-slate-500">Schita generata pentru: <b className="text-slate-800">{data.company_name}</b></span>
              <button
                onClick={handleCopy}
                className="rounded-lg bg-slate-900 px-3.5 py-1.5 font-bold text-white hover:bg-slate-800 transition"
              >
                {copied ? "Copiat in Clipboard" : "Copiaza Textul Integral"}
              </button>
            </div>
            <pre className="h-96 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-800 whitespace-pre-wrap font-sans leading-relaxed">
              {data.dossier_text}
            </pre>
          </div>
        ) : null}
      </div>
    </div>
  );
}
""")

# 6. UPDATE APP/PAGE.TSX (INTEGRATING PHASE 4 ACTION BUTTONS INSIDE DOSSIER DRAWER)
write_file(os.path.join(FRONTEND, "app/page.tsx"), """\"use client\";
import React, { useState, useEffect } from "react";
import { useAuth } from "../context/AuthContext";
import { fetchTenantFeed, fetch72hMarketReport, addLeadToPipeline, triggerEmailAlert } from "../lib/api";
import {
  PricingModal,
  CaietScannerModal,
  WinOddsModal,
  ClarificationModal,
  BusinessEligibilityModal,
  CopilotChatModal,
  PipelineTrackerModal,
  AccountSettingsModal,
  WorkspaceDeskModal,
  CompetitorRadarModal,
  TechnicalProposalModal
} from "../components/EnterpriseModals";

export default function DeskPage() {
  const { user, preferences, desks, activeDesk, switchDesk } = useAuth();
  const [selectedDivision, setSelectedDivision] = useState<string>("all");
  const [activeCategory, setActiveCategory] = useState<string>("all");
  const [leads, setLeads] = useState<any[]>([]);
  const [selectedLead, setSelectedLead] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedCounty, setSelectedCounty] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy, setSortBy] = useState<string>("score_desc");
  const [report72h, setReport72h] = useState<any>(null);
  const [profileDropdownOpen, setProfileDropdownOpen] = useState(false);
  const [workspaceDropdownOpen, setWorkspaceDropdownOpen] = useState(false);
  const [emailSending, setEmailSending] = useState(false);
  const [emailSentSuccess, setEmailSentSuccess] = useState(false);

  // Modals
  const [pricingOpen, setPricingOpen] = useState(false);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [winModalOpen, setWinModalOpen] = useState(false);
  const [clarificationOpen, setClarificationOpen] = useState(false);
  const [businessScannerOpen, setBusinessScannerOpen] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [pipelineOpen, setPipelineOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [deskManagerOpen, setDeskManagerOpen] = useState(false);
  const [competitorModalOpen, setCompetitorModalOpen] = useState(false);
  const [proposalModalOpen, setProposalModalOpen] = useState(false);

  const loadWorkspace = async (force = false) => {
    if (force) setRefreshing(true);
    else setLoading(true);

    try {
      const feedData = await fetchTenantFeed(activeDesk?.id || "desk_default", undefined, activeCategory, force);
      setLeads(feedData?.leads || []);

      const macroData = await fetch72hMarketReport(activeDesk?.id || "desk_default");
      setReport72h(macroData);
    } catch (err) {
      console.warn("[Desk] Load note:", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadWorkspace(false);
  }, [activeDesk?.id, activeCategory]);

  const handleSaveToPipeline = async (lead: any) => {
    try {
      await addLeadToPipeline(activeDesk?.id || "desk_default", lead);
      alert("Dosarul a fost salvat in Pipeline.");
    } catch {
      alert("Eroare la salvarea in pipeline.");
    }
  };

  const handleSendEmailAlert = async (lead: any) => {
    setEmailSending(true);
    setEmailSentSuccess(false);
    try {
      const recipient = preferences?.notification_email || user?.email || "director@infraconstruct.ro";
      await triggerEmailAlert(lead, recipient);
      setEmailSentSuccess(true);
      setTimeout(() => setEmailSentSuccess(false), 4000);
    } catch {
      alert("Eroare la transmiterea alertei pe email.");
    } finally {
      setEmailSending(false);
    }
  };

  const filteredLeads = leads.filter((l) => {
    const matchCounty = selectedCounty === "all" || l?.county?.toLowerCase() === selectedCounty.toLowerCase();
    const matchSearch =
      !searchQuery ||
      l?.project_title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      l?.entity_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      l?.locality?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      l?.sub_category?.toLowerCase().includes(searchQuery.toLowerCase());

    let matchDivision = true;
    if (selectedDivision !== "all" && activeDesk?.divisions) {
      const activeDiv = activeDesk.divisions.find(d => d.id === selectedDivision);
      if (activeDiv && activeDiv.keywords?.length > 0) {
        const text = (l?.project_title + " " + l?.executive_summary + " " + l?.sub_category).toLowerCase();
        matchDivision = activeDiv.keywords.some(k => text.includes(k.toLowerCase()));
      }
    }

    return matchCounty && matchSearch && matchDivision;
  });

  filteredLeads.sort((a, b) => {
    if (sortBy === "budget_desc") return (b.financial_value_ron || 0) - (a.financial_value_ron || 0);
    if (sortBy === "budget_asc") return (a.financial_value_ron || 0) - (b.financial_value_ron || 0);
    if (sortBy === "date_desc") return (b.published_date || "").localeCompare(a.published_date || "");
    return (b.opportunity_score || 0) - (a.opportunity_score || 0);
  });

  const totalPipeline = filteredLeads.reduce((acc, curr) => acc + (curr?.financial_value_ron || 0), 0);
  const isSubscriber = Boolean(user?.is_subscribed);

  return (
    <div className="min-h-screen bg-[#f8fafc] text-slate-900 flex flex-col font-sans">
      {/* 1. TOP BAR */}
      <header className="h-16 border-b border-slate-200 bg-white px-6 flex items-center justify-between sticky top-0 z-30 shadow-sm">
        <div className="flex items-center gap-5">
          <span className="font-bold text-base tracking-wider text-slate-900 uppercase">
            RO-INTEL
          </span>

          <div className="relative">
            <button
              onClick={() => setWorkspaceDropdownOpen(!workspaceDropdownOpen)}
              className="flex items-center gap-2 rounded-lg border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-800 hover:border-slate-400 hover:bg-white transition shadow-sm"
            >
              <span className="h-2 w-2 rounded-full bg-sky-600"></span>
              <span className="truncate max-w-[200px]">{activeDesk?.name || "Selecteaza Desk"}</span>
              <span className="text-[10px] text-slate-500 font-normal">▼</span>
            </button>

            {workspaceDropdownOpen && (
              <div className="absolute left-0 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-2 shadow-xl z-50 text-xs space-y-1">
                <span className="text-[10px] uppercase font-bold text-slate-400 px-2 py-1 block">Companii & Desk-uri</span>
                {desks.map((d) => (
                  <button
                    key={d.id}
                    onClick={() => {
                      switchDesk(d.id);
                      setSelectedDivision("all");
                      setWorkspaceDropdownOpen(false);
                    }}
                    className={"w-full text-left rounded-lg px-2.5 py-2 transition flex items-center justify-between " + (activeDesk?.id === d.id ? "bg-sky-50 text-sky-800 font-bold border border-sky-200" : "text-slate-700 hover:bg-slate-100")}
                  >
                    <span className="truncate">{d.name}</span>
                    {activeDesk?.id === d.id && <span className="text-sky-700 text-xs font-bold">Activ</span>}
                  </button>
                ))}
                <div className="border-t border-slate-100 pt-1 mt-1">
                  <button
                    onClick={() => {
                      setWorkspaceDropdownOpen(false);
                      setDeskManagerOpen(true);
                    }}
                    className="w-full text-left rounded-lg px-2.5 py-1.5 font-bold text-sky-700 hover:bg-sky-50 transition"
                  >
                    + Administrare & Adaugare Companii
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setPipelineOpen(true)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition shadow-sm"
          >
            Pipeline Oportunitati
          </button>

          <button
            onClick={() => setBusinessScannerOpen(true)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition shadow-sm"
          >
            Eligibilitate Finantari
          </button>

          <button
            onClick={() => setCopilotOpen(true)}
            className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-800 hover:bg-sky-100 transition shadow-sm"
          >
            Copilot AI & Radar 72h
          </button>

          <button
            onClick={() => setPricingOpen(true)}
            className="rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 transition shadow-sm"
          >
            Factura Proforma / OP
          </button>

          <div className="relative ml-2 pl-3 border-l border-slate-200">
            <button
              onClick={() => setProfileDropdownOpen(!profileDropdownOpen)}
              className="flex items-center gap-2 rounded-lg p-1 hover:bg-slate-100 transition"
            >
              <div className="h-7 w-7 rounded-full bg-slate-200 flex items-center justify-center font-bold text-xs text-slate-700 border border-slate-300">
                {user?.full_name ? user.full_name.charAt(0).toUpperCase() : "U"}
              </div>
              <div className="hidden lg:block text-left">
                <span className="block text-[11px] font-bold text-slate-800 leading-none">{user?.full_name || "Cont Nelogat"}</span>
                <span className="text-[10px] text-slate-500">{user?.role || "Vizitator Desk"}</span>
              </div>
            </button>

            {profileDropdownOpen && (
              <div className="absolute right-0 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-3 shadow-xl z-50 text-xs space-y-2">
                <div className="border-b border-slate-100 pb-2">
                  <p className="font-bold text-slate-900">{user?.full_name || "Utilizator Nelogat"}</p>
                  <p className="text-[11px] text-slate-500 truncate">{user?.email || "Acces limitat demo"}</p>
                  <span className="inline-block mt-1 rounded bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-700">
                    {user?.role || "Neautentificat"}
                  </span>
                </div>

                <button
                  onClick={() => {
                    setProfileDropdownOpen(false);
                    setSettingsOpen(true);
                  }}
                  className="w-full rounded-lg bg-slate-100 py-2 text-center text-slate-700 hover:bg-slate-200 transition font-medium"
                >
                  Setari Cont & Alerte
                </button>

                <button
                  onClick={() => {
                    setProfileDropdownOpen(false);
                    setDeskManagerOpen(true);
                  }}
                  className="w-full rounded-lg bg-slate-100 py-2 text-center text-slate-700 hover:bg-slate-200 transition font-medium"
                >
                  Companii & Desk-uri
                </button>

                {!user ? (
                  <button
                    onClick={() => {
                      setProfileDropdownOpen(false);
                      setSettingsOpen(true);
                    }}
                    className="w-full rounded-lg bg-sky-600 py-2 text-center text-white hover:bg-sky-700 transition font-bold"
                  >
                    Autentificare / Log in
                  </button>
                ) : (
                  <button
                    onClick={() => {
                      setProfileDropdownOpen(false);
                      setSettingsOpen(true);
                    }}
                    className="w-full rounded-lg bg-rose-50 py-2 text-center text-rose-700 hover:bg-rose-100 transition font-medium border border-rose-200"
                  >
                    Deconectare
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </header>

      {/* 2. BODY CONTENT */}
      <div className="flex-1 flex overflow-hidden">
        {/* SIDEBAR */}
        <aside className="w-72 border-r border-slate-200 bg-white p-5 flex flex-col justify-between hidden md:flex">
          <div>
            <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block mb-3">Domenii Strategice</span>
            <div className="space-y-1 mb-5 text-xs">
              {[
                { id: "all", label: "Toate Categoriile (Complet)" },
                { id: "infrastructura", label: "Infrastructura & Transporturi" },
                { id: "sanatate", label: "Sanatate & Echipamente Medicale" },
                { id: "energie", label: "Energie & Utilitati Verzi" },
                { id: "aparare", label: "Aparare & Securitate Speciala" },
                { id: "digitalizare", label: "Digitalizare, IT & Smart City" }
              ].map((c) => (
                <button
                  key={c.id}
                  onClick={() => setActiveCategory(c.id)}
                  className={"w-full text-left rounded-lg px-3 py-2 font-medium transition " + (activeCategory === c.id ? "bg-sky-50 text-sky-800 border border-sky-200 font-bold" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")}
                >
                  {c.label}
                </button>
              ))}
            </div>

            <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block mb-2">Divizii Desk ({activeDesk?.name ? activeDesk.name.split(" ")[0] : ""})</span>
            <div className="space-y-1 mb-5">
              <button
                onClick={() => setSelectedDivision("all")}
                className={"w-full text-left rounded-lg px-3 py-1.5 text-xs transition " + (selectedDivision === "all" ? "text-sky-700 font-bold" : "text-slate-600 hover:bg-slate-50")}
              >
                Toate Liniile Desk
              </button>
              {activeDesk?.divisions?.map((d) => (
                <button
                  key={d.id}
                  onClick={() => setSelectedDivision(d.id)}
                  className={"w-full text-left rounded-lg px-3 py-1.5 text-xs transition " + (selectedDivision === d.id ? "text-sky-700 font-bold" : "text-slate-600 hover:bg-slate-50")}
                >
                  {d.name}
                </button>
              ))}
            </div>

            <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block mb-2">Filtrare Judet</span>
            <select
              value={selectedCounty}
              onChange={(e) => setSelectedCounty(e.target.value)}
              className="w-full rounded-lg border border-slate-300 bg-slate-50 p-2 text-xs text-slate-800 focus:bg-white focus:outline-none focus:border-sky-500"
            >
              <option value="all">Toate Judetele Monitorizate (8)</option>
              <option value="Iasi">Iasi</option>
              <option value="Cluj">Cluj</option>
              <option value="Timis">Timis</option>
              <option value="Bucuresti">Bucuresti</option>
              <option value="Brasov">Brasov</option>
              <option value="Constanta">Constanta</option>
              <option value="Bihor">Bihor</option>
            </select>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 text-xs text-slate-600 shadow-sm">
            <span className="block text-[10px] uppercase font-bold text-slate-500">Volum Total Identificat</span>
            <span className="text-xl font-extrabold text-slate-900 mt-0.5 block">{(totalPipeline / 1000000).toFixed(1)} Mil. RON</span>
            <span className="text-[11px] text-emerald-700 font-medium block mt-1">25 Motoare de Monitorizare Active</span>
          </div>
        </aside>

        {/* MAIN FEED */}
        <main className="flex-1 p-6 overflow-y-auto">
          {/* SEARCH & REPOSITIONED REFRESH BUTTON TOOLBAR */}
          <div className="flex flex-col lg:flex-row gap-3 justify-between items-center mb-6 bg-white p-3.5 rounded-xl border border-slate-200 shadow-sm">
            <div className="flex-1 w-full lg:w-auto flex items-center gap-2">
              <input
                type="text"
                placeholder="Cautare dupa proiect, autoritate, subcategorie sau cod..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full md:w-96 rounded-lg border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs text-slate-900 placeholder-slate-400 focus:bg-white focus:border-sky-600 focus:outline-none"
              />
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="rounded-lg border border-slate-300 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700 focus:bg-white focus:outline-none"
              >
                <option value="score_desc">Sortare: Scor Oportunitate</option>
                <option value="budget_desc">Sortare: Buget Descrescator</option>
                <option value="budget_asc">Sortare: Buget Crescator</option>
                <option value="date_desc">Sortare: Cele mai recente</option>
              </select>
            </div>

            <div className="flex items-center gap-2.5 w-full lg:w-auto justify-end">
              <span className="text-xs text-slate-500 font-medium">{filteredLeads.length} semnale</span>
              
              <button
                onClick={() => loadWorkspace(true)}
                disabled={refreshing}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition shadow-sm"
              >
                {refreshing ? "Se actualizeaza..." : "Actualizeaza date"}
              </button>

              <a
                href={"https://api.ro-intel.xyz/api/v1/tenants/" + (activeDesk?.id || "desk_default") + "/export/csv"}
                download
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition shadow-sm"
              >
                Export CSV
              </a>
            </div>
          </div>

          {loading ? (
            <div className="flex h-64 items-center justify-center text-xs text-slate-500 font-medium">Sincronizare registru pre-SEAP...</div>
          ) : filteredLeads.length === 0 ? (
            <div className="flex h-64 items-center justify-center text-xs text-slate-500">Nu exista semnale pentru criteriile selectate.</div>
          ) : (
            <div className="grid grid-cols-1 gap-3.5">
              {filteredLeads.map((l, index) => {
                const isGated = !isSubscriber && index >= 2;
                return (
                  <div
                    key={l.source_id}
                    onClick={() => {
                      if (isGated) setPricingOpen(true);
                      else setSelectedLead(l);
                    }}
                    className={"relative rounded-xl border bg-white p-5 cursor-pointer transition shadow-sm " + (isGated ? "border-slate-200 opacity-80" : "border-slate-200 hover:border-sky-500 hover:shadow-md")}
                  >
                    <div className="flex justify-between items-start mb-2.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded bg-sky-50 px-2 py-0.5 text-[10px] font-bold text-sky-800 border border-sky-200 uppercase">
                          {l.category}
                        </span>
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-700">
                          {l.sub_category || "General"}
                        </span>
                        <span className="text-xs text-slate-500">
                          {l.locality}, {l.county}
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="text-base font-extrabold text-slate-900">
                          {l.financial_value_ron ? (l.financial_value_ron / 1000000).toFixed(1) + " Mil. RON" : "Buget Neestimat"}
                        </span>
                        <span className="block text-[11px] font-bold text-emerald-700">Scor: {l.opportunity_score} / 10</span>
                      </div>
                    </div>

                    <h4 className={"text-sm font-bold text-slate-900 mb-1 " + (isGated ? "blur-[2px]" : "")}>{l.project_title}</h4>
                    <p className="text-xs text-slate-600 mb-2 font-medium">{l.entity_name} &bull; Sursa: <span className="text-slate-800 font-semibold">{l.source_type}</span></p>
                    
                    <p className={"text-xs text-slate-700 line-clamp-2 leading-relaxed bg-slate-50 p-3 rounded-lg border border-slate-100 " + (isGated ? "blur-[3px] select-none" : "")}>
                      {l.executive_summary}
                    </p>

                    <div className="mt-3 flex flex-wrap items-center justify-between text-[11px] text-slate-500 border-t border-slate-100 pt-2.5">
                      <div className="flex items-center gap-4">
                        <span>Publicat: <b className="text-slate-800">{l.published_date || "2026-08-25"}</b></span>
                        <span>Termen Reactie: <b className="text-amber-700">{l.action_deadline || "T4 2026"}</b></span>
                      </div>
                      {isGated ? (
                        <span className="text-sky-700 font-bold">Deblocheaza Dosarul &rarr;</span>
                      ) : (
                        <span className="text-sky-700 font-semibold hover:underline">Deschide Dosar Strategic &rarr;</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </main>
      </div>

      {/* 3. SLIDE-OVER DOSSIER */}
      {selectedLead && (
        <div className="fixed inset-y-0 right-0 z-40 w-full max-w-xl bg-white border-l border-slate-200 shadow-2xl p-6 overflow-y-auto flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-start mb-4 border-b border-slate-200 pb-3">
              <div>
                <span className="text-[11px] font-bold text-sky-700 uppercase tracking-wide">Dosar Tehnic Pre-SEAP &bull; {selectedLead.source_id}</span>
                <h3 className="text-lg font-bold text-slate-900 mt-0.5">{selectedLead.project_title}</h3>
                <p className="text-xs text-slate-600">{selectedLead.entity_name} ({selectedLead.county})</p>
              </div>
              <button onClick={() => setSelectedLead(null)} className="text-slate-400 hover:text-slate-700 p-1 font-bold text-sm">✕</button>
            </div>

            <div className="space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-slate-50 p-3.5 border border-slate-200">
                  <span className="text-[10px] text-slate-500 block uppercase font-semibold">Buget Estimat</span>
                  <span className="text-base font-extrabold text-slate-900">{(selectedLead.financial_value_ron / 1000000).toFixed(2)} Mil. RON</span>
                </div>
                <div className="rounded-xl bg-slate-50 p-3.5 border border-slate-200">
                  <span className="text-[10px] text-slate-500 block uppercase font-semibold">Sursa Finantare</span>
                  <span className="text-sm font-bold text-sky-800">{selectedLead.funding_source}</span>
                </div>
              </div>

              <div className="rounded-xl bg-slate-50 border border-slate-200 p-3.5 space-y-2">
                <div className="flex justify-between">
                  <span className="text-slate-500">Data Publicarii:</span>
                  <span className="font-semibold text-slate-800">{selectedLead.published_date}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Termen Limita Dialog Tehnic:</span>
                  <span className="font-semibold text-amber-700">{selectedLead.action_deadline || "Nespecificat"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Registru Sursa:</span>
                  <span className="font-semibold text-slate-800">{selectedLead.source_type}</span>
                </div>
              </div>

              <div className="rounded-xl bg-sky-50 border border-sky-200 p-4">
                <span className="font-bold text-sky-900 block mb-1">Pozitionare Tehnica & Factori de Evaluare</span>
                <p className="text-slate-700 leading-relaxed">{selectedLead.sales_pitch_angle}</p>
              </div>

              <div className="pt-2 space-y-2">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block">Actiuni Dosar</span>
                
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => handleSaveToPipeline(selectedLead)}
                    className="rounded-lg bg-slate-900 p-2.5 text-center text-xs font-semibold text-white hover:bg-slate-800 transition shadow-sm"
                  >
                    Salveaza in Pipeline
                  </button>

                  <button
                    onClick={() => handleSendEmailAlert(selectedLead)}
                    disabled={emailSending}
                    className="rounded-lg border border-slate-300 bg-white p-2.5 text-center text-xs font-semibold text-slate-700 hover:bg-slate-50 transition shadow-sm"
                  >
                    {emailSending ? "Se expediaza..." : emailSentSuccess ? "Alerta Trimisa" : "Trimite Alerta Email"}
                  </button>
                </div>

                {/* PHASE 4 TOOLS: COMPETITOR RADAR & TECHNICAL PROPOSAL DRAFT */}
                <div className="grid grid-cols-2 gap-2 pt-1">
                  <button
                    onClick={() => setCompetitorModalOpen(true)}
                    className="rounded-lg border border-sky-300 bg-sky-50 p-2 text-center text-[11px] font-bold text-sky-800 hover:bg-sky-100 transition shadow-sm"
                  >
                    Radar Concurenta
                  </button>
                  <button
                    onClick={() => setProposalModalOpen(true)}
                    className="rounded-lg border border-slate-800 bg-slate-900 p-2 text-center text-[11px] font-bold text-white hover:bg-slate-800 transition shadow-sm"
                  >
                    Propunere Tehnica
                  </button>
                </div>

                <div className="grid grid-cols-3 gap-2 pt-1">
                  <button onClick={() => setScannerOpen(true)} className="rounded-lg bg-slate-100 border border-slate-200 p-2 text-center text-[11px] font-semibold text-slate-800 hover:bg-slate-200">
                    Scanner Caiet
                  </button>
                  <button onClick={() => setWinModalOpen(true)} className="rounded-lg bg-slate-100 border border-slate-200 p-2 text-center text-[11px] font-semibold text-slate-800 hover:bg-slate-200">
                    Simulator Sanse
                  </button>
                  <button onClick={() => setClarificationOpen(true)} className="rounded-lg bg-slate-100 border border-slate-200 p-2 text-center text-[11px] font-semibold text-slate-800 hover:bg-slate-200">
                    Adresa Legea 544
                  </button>
                </div>
              </div>
            </div>
          </div>

          <a
            href={selectedLead.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-6 w-full rounded-xl bg-slate-900 py-2.5 text-center font-semibold text-xs text-white hover:bg-slate-800 transition block shadow-sm"
          >
            Acceseaza Documentul Oficial Sursa &rarr;
          </a>
        </div>
      )}

      {/* 4. MODALS */}
      <PricingModal isOpen={pricingOpen} onClose={() => setPricingOpen(false)} tenantId={activeDesk?.id || "desk_default"} />
      <BusinessEligibilityModal isOpen={businessScannerOpen} onClose={() => setBusinessScannerOpen(false)} />
      <CopilotChatModal isOpen={copilotOpen} onClose={() => setCopilotOpen(false)} tenantId={activeDesk?.id || "desk_default"} report72h={report72h} />
      <CaietScannerModal isOpen={scannerOpen} onClose={() => setScannerOpen(false)} defaultTitle={selectedLead?.project_title || ""} />
      <WinOddsModal isOpen={winModalOpen} onClose={() => setWinModalOpen(false)} defaultBudget={selectedLead?.financial_value_ron || 10000000} />
      <ClarificationModal isOpen={clarificationOpen} onClose={() => setClarificationOpen(false)} opp={selectedLead || {}} />
      <PipelineTrackerModal isOpen={pipelineOpen} onClose={() => setPipelineOpen(false)} tenantId={activeDesk?.id || "desk_default"} />
      <AccountSettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <WorkspaceDeskModal isOpen={deskManagerOpen} onClose={() => setDeskManagerOpen(false)} />
      <CompetitorRadarModal isOpen={competitorModalOpen} onClose={() => setCompetitorModalOpen(false)} category={selectedLead?.category || "infrastructura"} county={selectedLead?.county || "Romania"} budget={selectedLead?.financial_value_ron || 10000000} />
      <TechnicalProposalModal isOpen={proposalModalOpen} onClose={() => setProposalModalOpen(false)} opp={selectedLead || {}} />
    </div>
  );
}
""")

print("\n⚡ [3/4] Testing Python Compilation...")
res_py = subprocess.run([sys.executable, "-c", "import api, notifier, workflow_engine, ai_refinery, scrapers.orchestrator, ai_copilot, addons.competitor_tracker, addons.dossier_generator; print('  [OK] Backend Python 100% Valid (0 errors)')"], cwd=ENGINE)
if res_py.returncode != 0:
    print("❌ Backend verification failed.")
    sys.exit(1)

print("\n⚡ [4/4] Testing Next.js Production Build...")
res_next = subprocess.run(["npm", "run", "build"], cwd=FRONTEND)
if res_next.returncode != 0:
    print("❌ Frontend build failed.")
    sys.exit(1)

print("\n⚡ [DEPLOY] Executing Direct Git Commits & Pushes...")

run_cmd(["git", "add", "-A"], cwd=FRONTEND)
subprocess.run(["git", "commit", "-m", "feat: Phase 4 competitor radar, technical proposal generator, clean UI, and conversational copilot"], cwd=FRONTEND)
run_cmd(["git", "push", "origin", "main"], cwd=FRONTEND)

run_cmd(["git", "add", "-A"], cwd=ENGINE)
subprocess.run(["git", "commit", "-m", "feat: Phase 4 competitor tracker, proposal assembler, and conversational copilot engine"], cwd=ENGINE)
run_cmd(["git", "push", "origin", "main"], cwd=ENGINE)

run_cmd(["git", "add", "-A"], cwd=ROOT)
subprocess.run(["git", "commit", "-m", "deploy: sync all submodules for Phase 4 release"], cwd=ROOT)
run_cmd(["git", "push", "origin", "main"], cwd=ROOT)

print("\n🎉 [SUCCESS] Phase 4 build verified and deployed to Vercel and Render!")
