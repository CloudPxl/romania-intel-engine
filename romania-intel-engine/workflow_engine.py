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

# Deals added by users at runtime, keyed by tenant.
#
# This previously shipped with a seeded demo deal ("DEAL-IASI-ITS-01")
# referencing opportunity SICAP-MC-2026-10892 — an id from the old fixture
# data that no longer exists in any source. It appeared in the live
# pipeline as though a real bid were in progress, with a real assignee
# email and a 18.2M RON value attached to nothing. Starting empty is both
# accurate and what a new tenant should see.
#
# Note this is process-local and resets on restart (see CLAUDE.md); the
# pipeline is not yet persisted to Postgres.
CONCURRENT_DEAL_PIPELINE: Dict[str, List[Dict[str, Any]]] = {}

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
        # Validate before mutating. Without this an unrecognised stage (a
        # typo, or a renamed stage on the frontend) was written straight
        # into the deal, silently dropping it out of every stage-filtered
        # view with no error surfaced anywhere.
        if new_stage not in PIPELINE_STAGES:
            logger.warning(f"[Workflow] Rejected unknown stage '{new_stage}' for deal {deal_id}")
            return {
                "status": "error",
                "message": f"Etapă necunoscută: '{new_stage}'",
                "valid_stages": PIPELINE_STAGES,
            }

        if proposed_price is not None and proposed_price < 0:
            return {"status": "error", "message": "Prețul propus nu poate fi negativ."}

        deals = CONCURRENT_DEAL_PIPELINE.get(tenant_id, [])
        for d in deals:
            if d.get("deal_id") == deal_id:
                previous_stage = d.get("stage")
                d["stage"] = new_stage
                if notes:
                    d["notes"] = notes
                if proposed_price is not None:
                    d["proposed_price"] = proposed_price
                d["updated_at"] = datetime.now().isoformat()
                # Keep an audit trail: which stages a deal passed through
                # and when is exactly what a post-mortem on a lost bid needs.
                d.setdefault("stage_history", []).append({
                    "from": previous_stage,
                    "to": new_stage,
                    "at": d["updated_at"],
                })
                logger.info(f"📈 Deal {deal_id} moved {previous_stage} -> {new_stage}")
                return {"status": "success", "deal": d}
        return {"status": "error", "message": "Deal not found"}
