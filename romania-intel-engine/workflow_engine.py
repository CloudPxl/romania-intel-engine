import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("WorkflowEngine")

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
    def get_tenant_pipeline(tenant_id: str, product_id: Optional[str] = None) -> List[Dict[str, Any]]:
        deals = CONCURRENT_DEAL_PIPELINE.get(tenant_id, [])
        if product_id:
            return [d for d in deals if d.get("product_id") == product_id]
        return deals

    @staticmethod
    def update_deal_stage(tenant_id: str, deal_id: str, new_stage: str, notes: Optional[str] = None) -> Dict[str, Any]:
        deals = CONCURRENT_DEAL_PIPELINE.get(tenant_id, [])
        for d in deals:
            if d.get("deal_id") == deal_id:
                d["stage"] = new_stage
                if notes:
                    d["notes"] = notes
                d["updated_at"] = datetime.now().isoformat()
                logger.info(f"📈 Deal {deal_id} moved to stage: {new_stage}")
                return {"status": "success", "deal": d}
        return {"status": "error", "message": "Deal not found"}
