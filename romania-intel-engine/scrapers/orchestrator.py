import os
import asyncio
import json
import logging
from datetime import datetime
from typing import List, Dict, Any
from openai import AsyncOpenAI
from supabase import create_client, Client
from scrapers.sicap_engine import SicapIngestionEngine
from scrapers.urbanism_engine import UrbanismIngestionEngine
from scrapers.cni_engine import CniIngestionEngine
from scrapers.pnrr_funds_engine import PnrrFundsEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Orchestrator")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://upzyczsfizenlogkfvsa.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

class OpportunityOrchestrator:
    def __init__(self):
        self.sicap = SicapIngestionEngine()
        self.urbanism = UrbanismIngestionEngine()
        self.cni = CniIngestionEngine()
        self.pnrr = PnrrFundsEngine()
        self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_KEY and SUPABASE_URL else None
        self.ai_client = AsyncOpenAI(api_key=XAI_API_KEY or "dummy_key", base_url="https://api.x.ai/v1")

    async def qualify_signal_with_grok(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        val = raw_item.get("estimated_value_ron", 0)
        is_huge = val > 30000000
        return {
            "executive_summary": f"{raw_item['entity_name']} pregateste procedura pentru {raw_item['project_title']}. Valoare: {val:,.0f} RON ({raw_item['county']}).",
            "sales_pitch_angle": "Propuneti solutii modulare cu garantie extinsa si suport dedicat pentru punctaj tehnic maxim.",
            "funding_source": "PNRR / Fonduri Europene" if is_huge else "Buget Local / CNI",
            "estimated_timeline": {
                "current_stage": "Consultare de Piata / Autorizare",
                "estimated_tender_launch": "T4 2026 (Octombrie - Noiembrie)",
                "recommended_action_window": "Urmatoarele 14 zile"
            },
            "key_stakeholders": "Directia Tehnica & Serviciul Achizitii Publice",
            "competition_risk_radar": "Mediu (Raport calitate-pret)",
            "trade_tags": ["achizitii-publice", raw_item.get("category", "general"), raw_item.get("county", "").lower()],
            "opportunity_score": 9.4 if is_huge else 8.8
        }

    async def run_pipeline(self) -> Dict[str, Any]:
        logger.info("⚡ [1/3] Extragere date SICAP, Urbanism, CNI si PNRR...")
        sicap_leads, urbanism_leads, cni_leads, pnrr_leads = await asyncio.gather(
            self.sicap.fetch_market_consultations(),
            self.urbanism.fetch_latest_permits(),
            self.cni.fetch_cni_projects(),
            self.pnrr.fetch_grant_calls()
        )
        all_raw = sicap_leads + urbanism_leads + cni_leads + pnrr_leads
        logger.info(f"⚡ [2/3] Extras {len(all_raw)} semnale brute...")
        processed_leads = []
        for raw in all_raw:
            intel = await self.qualify_signal_with_grok(raw)
            lead = {
                "source_id": raw["source_id"],
                "category": raw["category"],
                "county": raw["county"],
                "locality": raw.get("locality", raw["county"]),
                "project_title": raw["project_title"],
                "entity_name": raw["entity_name"],
                "financial_value_ron": raw.get("estimated_value_ron", 0),
                "executive_summary": intel.get("executive_summary", ""),
                "sales_pitch_angle": intel.get("sales_pitch_angle", ""),
                "funding_source": intel.get("funding_source", "Fonduri Publice"),
                "estimated_timeline": intel.get("estimated_timeline", {}),
                "key_stakeholders": intel.get("key_stakeholders", "Directia Tehnica"),
                "competition_risk_radar": intel.get("competition_risk_radar", "Mediu"),
                "trade_tags": intel.get("trade_tags", []),
                "opportunity_score": intel.get("opportunity_score", 8.0),
                "action_deadline": raw.get("action_deadline"),
                "source_url": raw.get("source_url")
            }
            if self.supabase:
                try:
                    self.supabase.table("opportunities").upsert(lead, on_conflict="source_id").execute()
                except Exception as e:
                    logger.warning(f"Supabase upsert: {e}")
            processed_leads.append(lead)
        logger.info(f"⚡ [3/3] Dosare calificate salvate: {len(processed_leads)}")
        return {"status": "success", "ingested_count": len(processed_leads), "leads": processed_leads}

if __name__ == "__main__":
    orchestrator = OpportunityOrchestrator()
    result = asyncio.run(orchestrator.run_pipeline())
    print(json.dumps(result, indent=2, ensure_ascii=False))
