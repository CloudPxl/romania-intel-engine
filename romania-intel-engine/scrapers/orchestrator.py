import os
import asyncio
import json
import logging
from typing import List, Dict, Any
from supabase import create_client, Client

from scrapers.models import RawInstitutionalSignal
from scrapers.dedup_engine import IngestionDeduplicator
from scrapers.sicap_engine import SicapIngestionEngine
from scrapers.municipal_engine import MunicipalIngestionEngine
from scrapers.cni_engine import CniIngestionEngine
from scrapers.pnrr_mipe_engine import PnrrMipeEngine
from ai_refinery import ProcurementAIRefinery

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("OpportunityOrchestrator")

SUPABASE_URL = os.getenv("SUPABASE_URL", "[https://upzyczsfizenlogkfvsa.supabase.co](https://upzyczsfizenlogkfvsa.supabase.co)")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))

class OpportunityOrchestrator:
    def __init__(self):
        self.sicap = SicapIngestionEngine()
        self.municipal = MunicipalIngestionEngine()
        self.cni = CniIngestionEngine()
        self.pnrr = PnrrMipeEngine()
        self.refinery = ProcurementAIRefinery()
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_KEY and SUPABASE_URL else None

    async def run_pipeline(self) -> Dict[str, Any]:
        logger.info("⚡ [1/3] Ingestion: Extracting signals from SICAP, Municipal HCL/AC, CNI, and MIPE/PNRR...")
        
        results = await asyncio.gather(
            self.sicap.fetch_market_consultations(),
            self.municipal.fetch_all_regional_signals(),
            self.cni.fetch_cni_projects(),
            self.pnrr.fetch_all_grant_calls(),
            return_exceptions=True
        )

        all_raw_signals: List[RawInstitutionalSignal] = []
        for res in results:
            if isinstance(res, list):
                all_raw_signals.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"[Orchestrator] Scraper error: {res}")

        logger.info(f"⚡ [2/3] Deduplication: Checking {len(all_raw_signals)} extracted signals against registry hashes...")
        new_signals = IngestionDeduplicator.filter_new_signals(all_raw_signals, self.supabase)
        logger.info(f"⚡ [2/3] Processing {len(new_signals)} signals through the AI Refinery...")

        processed_leads = []
        for signal in new_signals:
            intel = await self.refinery.refine_signal(signal)
            
            lead_record = {
                "source_id": signal.source_id,
                "source_type": signal.source_type,
                "category": signal.category,
                "county": signal.county,
                "locality": signal.locality,
                "project_title": signal.project_title,
                "entity_name": signal.entity_name,
                "financial_value_ron": signal.estimated_value_ron,
                "executive_summary": intel.get("executive_summary", ""),
                "sales_pitch_angle": intel.get("sales_pitch_angle", ""),
                "funding_source": intel.get("funding_source", "Fonduri Publice"),
                "estimated_timeline": intel.get("estimated_timeline", {}),
                "key_stakeholders": intel.get("key_stakeholders", "Directia Tehnica"),
                "competition_risk_radar": intel.get("competition_risk_radar", "Mediu"),
                "trade_tags": intel.get("trade_tags", []),
                "opportunity_score": intel.get("opportunity_score", 8.8),
                "scoring_breakdown": intel.get("scoring_breakdown", {}),
                "action_deadline": signal.action_deadline,
                "source_url": signal.source_url,
                "metadata": signal.metadata
            }

            if self.supabase:
                try:
                    self.supabase.table("opportunities").upsert(lead_record, on_conflict="source_id").execute()
                except Exception as e:
                    logger.warning(f"[Orchestrator] Supabase upsert note: {e}")

            processed_leads.append(lead_record)

        logger.info(f"⚡ [3/3] Intelligence pipeline complete. {len(processed_leads)} qualified dossiers generated.")
        return {
            "status": "success",
            "ingested_count": len(processed_leads),
            "leads": processed_leads
        }

if __name__ == "__main__":
    orchestrator = OpportunityOrchestrator()
    result = asyncio.run(orchestrator.run_pipeline())
    print(json.dumps(result, indent=2, ensure_ascii=False))
