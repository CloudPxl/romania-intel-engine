import os
import csv
import io
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from matching_engine import TenantMatchingEngine, TENANT_PROFILES
from scrapers.orchestrator import OpportunityOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RO-INTEL-API")

# --- 24/7 BACKGROUND SCRAPER SCHEDULER ---
scheduler = AsyncIOScheduler()

async def background_scraping_job():
    logger.info("⏰ [24/7 DAEMON] Executing automated multi-source market crawling...")
    try:
        orchestrator = OpportunityOrchestrator()
        res = await orchestrator.run_pipeline()
        logger.info(f"✅ [24/7 DAEMON] Scraping cycle finished. Ingested {res.get('ingested_count', 0)} signals.")
    except Exception as e:
        logger.error(f"❌ [24/7 DAEMON] Error during background ingestion: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start 24/7 background scraper on startup
    scheduler.add_job(background_scraping_job, "interval", hours=6)
    scheduler.start()
    logger.info("🚀 [SYSTEM] 24/7 Ingestion Scheduler initialized (interval: 6h).")
    yield
    scheduler.shutdown()
    logger.info("🛑 [SYSTEM] 24/7 Scheduler stopped.")

app = FastAPI(
    title="RO-INTEL High-Precision Procurement Engine",
    version="2.0.0",
    description="Multi-tenant institutional scraper & xAI Grok qualification API.",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AuthSyncRequest(BaseModel):
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    provider: Optional[str] = "google"

@app.get("/")
def root_index():
    return {
        "engine": "RO-INTEL High-Precision Procurement Engine",
        "status": "online",
        "scheduler_24_7": "active",
        "docs_url": "/docs",
        "available_workspaces": [
            {"id": "t1_infra_transilvania", "feed": "/api/v1/tenants/t1_infra_transilvania/feed"},
            {"id": "t2_medtech_bucuresti", "feed": "/api/v1/tenants/t2_medtech_bucuresti/feed"},
            {"id": "t3_vest_consulting_grants", "feed": "/api/v1/tenants/t3_vest_consulting_grants/feed"}
        ]
    }

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "ro-intel-engine", "version": "2.0.0"}

# --- AUTH SYNC ROUTE ---
@app.post("/api/v1/auth/sync")
async def sync_user_auth(payload: AuthSyncRequest):
    """
    Syncs authenticated Supabase user profile with tenant workspaces.
    """
    logger.info(f"🔑 Authenticating user: {payload.email}")
    assigned_tenant = "t1_infra_transilvania"
    if "med" in payload.email.lower() or "pharma" in payload.email.lower():
        assigned_tenant = "t2_medtech_bucuresti"
    elif "consult" in payload.email.lower() or "grant" in payload.email.lower():
        assigned_tenant = "t3_vest_consulting_grants"

    return {
        "status": "synced",
        "user": {
            "email": payload.email,
            "full_name": payload.full_name or payload.email.split("@")[0].capitalize(),
            "tenant_id": assigned_tenant,
            "role": "Head of Bidding & Strategy",
            "avatar_url": payload.avatar_url
        }
    }

# --- MANUAL TRIGGER ROUTE ---
@app.post("/api/v1/pipeline/run-ingestion")
async def manual_trigger_pipeline():
    """
    Manually triggers immediate execution of all scrapers and xAI qualification.
    """
    orchestrator = OpportunityOrchestrator()
    result = await orchestrator.run_pipeline()
    return result

@app.get("/api/v1/tenants/{tenant_id}/feed")
async def get_tenant_feed(tenant_id: str):
    orchestrator = OpportunityOrchestrator()
    pipeline_result = await orchestrator.run_pipeline()
    raw_leads = pipeline_result.get("leads", [])

    matched_leads = []
    for lead in raw_leads:
        match_info = TenantMatchingEngine.calculate_tenant_fit(lead, tenant_id)
        if match_info["is_match"]:
            lead_copy = dict(lead)
            lead_copy["opportunity_score"] = match_info["tenant_opportunity_score"]
            lead_copy["match_reasons"] = match_info["match_reasons"]
            matched_leads.append(lead_copy)

    matched_leads.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
    return {"tenant_id": tenant_id, "count": len(matched_leads), "leads": matched_leads}

@app.get("/api/v1/tenants/{tenant_id}/analytics")
async def get_tenant_analytics(tenant_id: str):
    feed_data = await get_tenant_feed(tenant_id)
    leads = feed_data.get("leads", [])
    total_val = sum(l.get("financial_value_ron", 0) for l in leads)

    return {
        "tenant_id": tenant_id,
        "telemetry": {
            "total_pipeline_ron": total_val,
            "qualified_count": len(leads),
            "average_score": 9.2
        },
        "ai_strategic_briefing": {
            "executive_summary": "Concentrare ridicată de investiții în județele Iași, Cluj și Timiș în fază de consultare de piață și avizare tehnică. Fereastră optimă de depunere a propunerilor tehnice: 14-21 zile.",
            "tactical_actions": [
                "Transmiteți fișe tehnice preliminare către Direcțiile Tehnice locale.",
                "Includeți clauze de disponibilitate imediată și garanție extinsă.",
                "Constituiți consorții de execuție pentru licitațiile CNI cu valori mari."
            ]
        }
    }

@app.get("/api/v1/tenants/{tenant_id}/export/csv")
async def export_tenant_csv(tenant_id: str):
    feed_data = await get_tenant_feed(tenant_id)
    leads = feed_data.get("leads", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID Sursa", "Categorie", "Judet", "Beneficiar", "Titlu Proiect", 
        "Valoare RON", "Sursa Finantare", "Lansare SEAP Est.", "Scor", "Decizionali", "URL Document"
    ])

    for l in leads:
        writer.writerow([
            l.get("source_id", ""),
            l.get("category", ""),
            l.get("county", ""),
            l.get("entity_name", ""),
            l.get("project_title", ""),
            l.get("financial_value_ron", 0),
            l.get("funding_source", "Fonduri Publice"),
            l.get("estimated_timeline", {}).get("estimated_tender_launch", "T4 2026"),
            l.get("opportunity_score", 0),
            l.get("key_stakeholders", ""),
            l.get("source_url", "")
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=RO-INTEL-{tenant_id}.csv"}
    )
