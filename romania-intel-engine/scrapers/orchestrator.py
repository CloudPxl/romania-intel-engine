import logging
from typing import List, Dict, Any
from scrapers.sicap_engine import SicapIngestionEngine
from scrapers.municipal_engine import MunicipalRegistryEngine
from scrapers.cni_engine import CniIngestionEngine
from scrapers.pnrr_mipe_engine import PnrrMipeIngestionEngine

logger = logging.getLogger("OpportunityOrchestrator")

class OpportunityOrchestrator:
    def __init__(self):
        self.sicap = SicapIngestionEngine()
        self.municipal = MunicipalRegistryEngine()
        self.cni = CniIngestionEngine()
        self.pnrr = PnrrMipeIngestionEngine()

    async def run_pipeline(self) -> Dict[str, Any]:
        signals = []
        signals.extend(await self.sicap.fetch_market_consultations())
        signals.extend(await self.municipal.fetch_market_consultations())
        signals.extend(await self.cni.fetch_market_consultations())
        signals.extend(await self.pnrr.fetch_market_consultations())

        leads = []
        for s in signals:
            score = 9.4 if s.estimated_value_ron > 20000000 else 8.8
            leads.append({
                "source_id": s.source_id,
                "source_type": s.source_type,
                "category": s.category,
                "county": s.county,
                "locality": s.locality,
                "project_title": s.project_title,
                "entity_name": s.entity_name,
                "financial_value_ron": s.estimated_value_ron,
                "executive_summary": s.raw_description,
                "sales_pitch_angle": "Poziționați oferta pe fiabilitate ridicată, mentenanță preventivă inclusă și timpi de răspuns sub 4 ore.",
                "funding_source": "PNRR / Fonduri Europene Nerambursabile" if "PNRR" in s.project_title or "MIPE" in s.source_type else "Buget Local / CNI",
                "estimated_timeline": {
                    "current_stage": "Consultare de Piață & Avizare Tehnică",
                    "estimated_tender_launch": "T4 2026 (Octombrie - Noiembrie)",
                    "recommended_action_window": "Următoarele 14 zile (Faza de dialog tehnic)"
                },
                "opportunity_score": score,
                "action_deadline": s.action_deadline,
                "source_url": s.source_url,
                "metadata": s.metadata
            })

        return {"leads": leads, "total_count": len(leads)}
