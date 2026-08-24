import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("WorkflowEngine")

# In-memory concurrent state for fast access with Supabase synchronization
CONCURRENT_DEAL_PIPELINE: Dict[str, List[Dict[str, Any]]] = {
    "t1_infra_transilvania": [
        {
            "deal_id": "DEAL-IASI-ITS-01",
            "product_id": "prod_smart_traffic",
            "opportunity_id": "SICAP-MC-IASI-ITS-101",
            "project_title": "Sistem inteligent de management al traficului Iași",
            "stage": "consultation_drafted",
            "assigned_to": "andrei.muresan@infraconstruct.ro",
            "target_margin_pct": 21.0,
            "estimated_value_ron": 18200000.0,
            "notes": "Fișa tehnică preliminară pregătită pentru transmitere la Primăria Iași."
        }
    ],
    "t2_medtech_bucuresti": [
        {
            "deal_id": "DEAL-IRO-RAD-01",
            "product_id": "prod_oncology_hardware",
            "opportunity_id": "SICAP-MC-IASI-IRO-202",
            "project_title": "Acceleratoare liniare particule IRO Iași",
            "stage": "caiet_sarcini_analysis",
            "assigned_to": "dr.popescu@medtechpharma.ro",
            "target_margin_pct": 28.5,
            "estimated_value_ron": 34000000.0,
            "notes": "Specificațiile tehnice de radioterapie stereotaxică sunt 100% compatibile."
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
