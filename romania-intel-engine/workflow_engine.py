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

TERMINAL_STAGES = {"won", "lost"}

# Baseline probability-to-close by stage — the standard sales-pipeline
# convention (weighted pipeline = value * stage probability), used here
# because it is a stated, inspectable heuristic rather than a claim of
# statistical calibration. This mirrors addons/win_probability.py's own
# stance: the system has never ingested a single award result, so it
# cannot produce a trained probability — what it can produce is a
# transparent, auditable weighting, which is what a pipeline forecast
# needs to be useful without overclaiming precision.
STAGE_WIN_PROBABILITY: Dict[str, float] = {
    "discovery": 0.10,
    "consultation_drafted": 0.20,
    "consultation_submitted": 0.30,
    "caiet_sarcini_analysis": 0.40,
    "offer_prepared": 0.55,
    "bid_submitted": 0.70,
    "won": 1.0,
    "lost": 0.0,
}

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

    @staticmethod
    def _reached_stages(deal: Dict[str, Any]) -> set:
        """Every stage a deal has actually passed through, including its
        current one. `stage_history` only logs transitions, so a deal that
        has never moved (still sitting in discovery) has an empty history
        but has still "reached" discovery — that has to be added explicitly
        rather than inferred from an empty list."""
        reached = {"discovery", deal.get("stage")}
        for entry in deal.get("stage_history", []):
            if entry.get("to"):
                reached.add(entry["to"])
        reached.discard(None)
        return reached

    @staticmethod
    def _stage_durations_days(deal: Dict[str, Any], now: datetime) -> Dict[str, float]:
        """Days spent in each stage the deal has passed through, computed
        from real transition timestamps in `stage_history` rather than
        estimated — the time between entering a stage (the previous
        transition's timestamp, or `created_at` for the first stage) and
        leaving it (the next transition's timestamp, or `now` if it's the
        deal's current stage)."""
        try:
            entered_at = datetime.fromisoformat(deal["created_at"])
        except (KeyError, ValueError, TypeError):
            return {}

        current_stage = "discovery"
        durations: Dict[str, float] = {}
        for entry in deal.get("stage_history", []):
            try:
                left_at = datetime.fromisoformat(entry["at"])
            except (KeyError, ValueError, TypeError):
                continue
            days = max(0.0, (left_at - entered_at).total_seconds() / 86400)
            durations[current_stage] = durations.get(current_stage, 0.0) + days
            current_stage = entry.get("to", current_stage)
            entered_at = left_at

        days_in_current = max(0.0, (now - entered_at).total_seconds() / 86400)
        durations[current_stage] = durations.get(current_stage, 0.0) + days_in_current
        return durations

    @staticmethod
    def get_pipeline_metrics(tenant_id: str, product_id: Optional[str] = None) -> Dict[str, Any]:
        """Real pipeline analytics over the tenant's current deals: value
        weighted by stage-based win probability, actual time spent per
        stage (from transition timestamps, not estimated), and funnel
        conversion rates derived from which stages each deal has actually
        reached — not fixed/seeded numbers.
        """
        deals = ConcurrentWorkflowEngine.get_tenant_pipeline(tenant_id, product_id)
        now = datetime.now()

        total_deals = len(deals)
        won = [d for d in deals if d.get("stage") == "won"]
        lost = [d for d in deals if d.get("stage") == "lost"]
        active = [d for d in deals if d.get("stage") not in TERMINAL_STAGES]

        def _value(d: Dict[str, Any]) -> float:
            return d.get("proposed_price") or d.get("estimated_value_ron") or 0.0

        active_pipeline_value_ron = sum(_value(d) for d in active)
        weighted_pipeline_value_ron = sum(
            _value(d) * STAGE_WIN_PROBABILITY.get(d.get("stage"), 0.0) for d in active
        )
        won_value_ron = sum(_value(d) for d in won)

        stage_breakdown: Dict[str, Dict[str, Any]] = {
            stage: {"count": 0, "value_ron": 0.0} for stage in PIPELINE_STAGES
        }
        stage_duration_totals: Dict[str, List[float]] = {stage: [] for stage in PIPELINE_STAGES}
        reached_counts: Dict[str, int] = {stage: 0 for stage in PIPELINE_STAGES}

        for d in deals:
            stage = d.get("stage")
            if stage in stage_breakdown:
                stage_breakdown[stage]["count"] += 1
                stage_breakdown[stage]["value_ron"] += _value(d)
            for reached in ConcurrentWorkflowEngine._reached_stages(d):
                if reached in reached_counts:
                    reached_counts[reached] += 1
            for reached_stage, days in ConcurrentWorkflowEngine._stage_durations_days(d, now).items():
                if reached_stage in stage_duration_totals:
                    stage_duration_totals[reached_stage].append(days)

        average_days_in_stage = {
            stage: round(sum(vals) / len(vals), 1)
            for stage, vals in stage_duration_totals.items()
            if vals
        }

        def _conversion(from_stage: str, to_stage: str) -> Optional[float]:
            denom = reached_counts.get(from_stage, 0)
            if denom == 0:
                return None
            return round(reached_counts.get(to_stage, 0) / denom * 100, 1)

        closed = len(won) + len(lost)

        return {
            "tenant_id": tenant_id,
            "product_id": product_id,
            "total_deals": total_deals,
            "active_deals": len(active),
            "won_deals": len(won),
            "lost_deals": len(lost),
            "active_pipeline_value_ron": active_pipeline_value_ron,
            "weighted_pipeline_value_ron": round(weighted_pipeline_value_ron, 2),
            "won_value_ron": won_value_ron,
            "stage_breakdown": stage_breakdown,
            "average_days_in_stage": average_days_in_stage,
            "conversion_rates_pct": {
                "discovery_to_bid_submitted": _conversion("discovery", "bid_submitted"),
                "bid_submitted_to_won": _conversion("bid_submitted", "won"),
                "overall_win_rate": round(len(won) / closed * 100, 1) if closed else None,
            },
            "methodology_note": (
                "Valoarea ponderată folosește probabilități standard de închidere pe etapă "
                "(euristică transparentă, nu un model calibrat pe rezultate istorice — sistemul "
                "nu a înregistrat încă rezultate reale de atribuire). Ratele de conversie și "
                "timpul mediu pe etapă sunt calculate din istoricul real de tranziții al "
                "dosarelor din acest pipeline."
            ),
        }
