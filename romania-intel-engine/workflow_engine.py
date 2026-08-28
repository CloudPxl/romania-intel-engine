import logging
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("WorkflowEngine")

PIPELINE_STAGES = [
    "discovery",
    "consultation_drafted",
    "consultation_submitted",
    "caiet_sarcini_analysis",
    "offer_prepared",
    "bid_submitted",
    "won",
    "lost",
]

CONCURRENT_DEAL_PIPELINE = {
    "t1_infra_transilvania": [
        {
            "deal_id": "DEAL-IASI-ITS-01",
            "product_id": "prod_smart_traffic",
            "opportunity_id": "SICAP-MC-2026-10892",
            "project_title": "Sistem inteligent de management al traficului Iași",
            "stage": "consultation_drafted",
            "assigned_to": "director@infraconstruct.ro",
            "target_margin_pct": 21.0,
            "estimated_value_ron": 18200000.0,
            "notes": "Fișa tehnică preliminară pregătită pentru transmitere la Primăria Iași."
        }
    ]
}

class ConcurrentWorkflowEngine:
    @staticmethod
    def get_stages() -> List[str]:
        return PIPELINE_STAGES

    @staticmethod
    def get_tenant_pipeline(tenant_id: str, product_id: Optional[str] = None) -> List[Dict[str, Any]]:
        deals = CONCURRENT_DEAL_PIPELINE.get(tenant_id, [])
        if product_id:
            return [d for d in deals if d.get("product_id") == product_id]
        return deals

    @staticmethod
    def add_lead_to_pipeline(tenant_id: str, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        deal = {
            "deal_id": f"DEAL-{uuid.uuid4().hex[:10].upper()}",
            "product_id": lead_data.get("product_id"),
            "opportunity_id": lead_data.get("source_id") or lead_data.get("opportunity_id"),
            "project_title": lead_data.get("project_title", ""),
            "stage": "discovery",
            "assigned_to": lead_data.get("assigned_to"),
            "target_margin_pct": lead_data.get("target_margin_pct"),
            "estimated_value_ron": lead_data.get("estimated_value_ron") or lead_data.get("financial_value_ron", 0.0),
            "notes": lead_data.get("notes", ""),
            "created_at": datetime.now().isoformat(),
        }
        CONCURRENT_DEAL_PIPELINE.setdefault(tenant_id, []).append(deal)
        logger.info(f"➕ Lead added to pipeline for {tenant_id}: {deal['deal_id']}")
        return {"status": "success", "deal": deal}

    @staticmethod
    def update_deal_stage(
        tenant_id: str,
        deal_id: str,
        new_stage: str,
        notes: Optional[str] = None,
        proposed_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        deals = CONCURRENT_DEAL_PIPELINE.get(tenant_id, [])
        for d in deals:
            if d.get("deal_id") == deal_id:
                d["stage"] = new_stage
                if notes:
                    d["notes"] = notes
                if proposed_price is not None:
                    d["proposed_price"] = proposed_price
                d["updated_at"] = datetime.now().isoformat()
                logger.info(f"📈 Deal {deal_id} moved to stage: {new_stage}")
                return {"status": "success", "deal": d}
        return {"status": "error", "message": "Deal not found"}
