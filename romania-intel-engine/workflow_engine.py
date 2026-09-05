import logging
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import db

logger = logging.getLogger("WorkflowEngine")


def _now() -> datetime:
    """Always timezone-aware UTC.

    `datetime.now()` returns a *naive* local time. Written into a
    TIMESTAMPTZ column asyncpg interprets it as UTC, so on any host whose
    clock is not UTC every deal timestamp was silently shifted; and read
    back it produced the crash below.
    """
    return datetime.now(timezone.utc)


def _as_aware(value: Any) -> Optional[datetime]:
    """Parses a stored timestamp into an offset-aware datetime.

    This is the fix for a 500 on GET /api/v1/me/pipeline/metrics that
    appeared the moment a user saved their first deal. The two persistence
    paths disagree about tzinfo: Postgres returns TIMESTAMPTZ, which
    db._deal_row_to_dict renders with .isoformat() *including* the offset,
    while the in-memory fallback stores a naive datetime.now().isoformat().
    Subtracting a naive datetime from an aware one raises
    `TypeError: can't subtract offset-naive and offset-aware datetimes`,
    which escaped to the global handler as an opaque "eroare neașteptată".

    It only ever reproduced with a database attached — the in-memory path
    is naive on both sides and cancels out — which is exactly why the test
    suite, which runs without DATABASE_URL, stayed green through it.

    A naive value is interpreted as *local* time, not UTC: Postgres never
    returns one, so the only naive timestamps that can reach here were
    written by the in-memory fallback's `datetime.now()`, which is local.
    Reading those as UTC shifted every duration by the host's offset —
    three hours in Romania, which is enough to misreport a deal's age.
    """
    if value is None:
        return None
    dt = value if isinstance(value, datetime) else None
    if dt is None:
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    return dt if dt.tzinfo is not None else dt.astimezone()

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

# In-memory fallback only. This previously shipped with a seeded demo
# deal ("DEAL-IASI-ITS-01") referencing opportunity SICAP-MC-2026-10892 —
# an id from old fixture data that no longer exists in any source. It
# appeared in the live pipeline as though a real bid were in progress,
# with a real assignee email and an 18.2M RON value attached to nothing.
# Starting empty is both accurate and what a new user should see.
#
# The real store is Postgres (schema.sql: saved_deals,
# deal_stage_history), via db.py's get_deals_for_user/add_deal/
# update_deal/record_stage_transition. This dict is only touched when
# those return "not available" (DATABASE_URL unset, or the migration
# hasn't been applied yet) — every write also lands here so a session
# stays internally consistent even without Postgres, but it still resets
# on restart, unlike the DB-backed path.
CONCURRENT_DEAL_PIPELINE: Dict[str, List[Dict[str, Any]]] = {}

class ConcurrentWorkflowEngine:
    @staticmethod
    def get_stages() -> List[str]:
        return PIPELINE_STAGES

    @staticmethod
    async def get_pipeline_for_user(user_id: str) -> List[Dict[str, Any]]:
        deals = await db.get_deals_for_user(user_id)
        if deals is not None:
            return deals
        return CONCURRENT_DEAL_PIPELINE.get(user_id, [])

    @staticmethod
    async def add_lead_to_pipeline(user_id: str, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        opportunity_id = lead_data.get("source_id") or lead_data.get("opportunity_id")

        # Saving the same lead twice produced two independent deals that
        # then diverged in stage and both counted toward pipeline value —
        # double-counting a contract that can only be won once. Returning
        # the existing deal is what the user meant anyway.
        if opportunity_id:
            existing = await db.find_deal_by_opportunity(user_id, opportunity_id)
            if existing is None:
                existing = next(
                    (d for d in CONCURRENT_DEAL_PIPELINE.get(user_id, [])
                     if d.get("opportunity_id") == opportunity_id),
                    None,
                )
            if existing is not None:
                logger.info(f"↩︎ Lead {opportunity_id} already in pipeline for {user_id} as {existing['deal_id']}")
                return {
                    "status": "already_saved",
                    "deal": existing,
                    "message": "Acest dosar este deja în pipeline.",
                }

        deal = {
            "deal_id": f"DEAL-{uuid.uuid4().hex[:10].upper()}",
            "user_id": user_id,
            "opportunity_id": opportunity_id,
            "project_title": lead_data.get("project_title", ""),
            "stage": "discovery",
            "target_margin_pct": lead_data.get("target_margin_pct"),
            "estimated_value_ron": lead_data.get("estimated_value_ron") or lead_data.get("financial_value_ron", 0.0),
            "notes": lead_data.get("notes", ""),
            "created_at": _now().isoformat(),
        }
        persisted = await db.add_deal(deal)
        if not persisted:
            CONCURRENT_DEAL_PIPELINE.setdefault(user_id, []).append(deal)
        logger.info(f"➕ Lead added to pipeline for {user_id}: {deal['deal_id']} (persisted={persisted})")
        return {"status": "success", "deal": deal, "persisted": persisted}

    @staticmethod
    async def remove_deal(user_id: str, deal_id: str) -> Dict[str, Any]:
        deleted = await db.delete_deal(user_id, deal_id)
        # Mirror it in the in-memory fallback either way: a deal added
        # while Postgres was down lives only there.
        deals = CONCURRENT_DEAL_PIPELINE.get(user_id, [])
        remaining = [d for d in deals if d.get("deal_id") != deal_id]
        if len(remaining) != len(deals):
            CONCURRENT_DEAL_PIPELINE[user_id] = remaining
            deleted = True
        if not deleted:
            return {"status": "error", "message": "Dosarul nu a fost găsit."}
        logger.info(f"🗑️ Deal {deal_id} removed for {user_id}")
        return {"status": "success", "deal_id": deal_id}

    @staticmethod
    async def update_deal_stage(
        user_id: str,
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

        existing = await db.get_deal(user_id, deal_id)
        if existing is not None:
            updated_at = _now().isoformat()
            previous_stage = existing.get("stage")
            updated_deal = await db.update_deal(user_id, deal_id, new_stage, notes, proposed_price, updated_at)
            if updated_deal is not None:
                # Only a real move is a transition. Editing the price or a
                # note while the deal stays put used to write a
                # stage -> same-stage row, which inflated the history and
                # reset time-in-stage to zero on every keystroke-sized
                # edit, corrupting the average-days-in-stage figure.
                if new_stage != previous_stage:
                    await db.record_stage_transition(deal_id, previous_stage, new_stage, updated_at)
                    updated_deal.setdefault("stage_history", []).append({
                        "from": previous_stage, "to": new_stage, "at": updated_at,
                    })
                    logger.info(f"📈 Deal {deal_id} moved {previous_stage} -> {new_stage} (Postgres)")
                else:
                    updated_deal.setdefault("stage_history", existing.get("stage_history", []))
                return {"status": "success", "deal": updated_deal}

        # Fallback: in-memory (also the path for a deal added while
        # Postgres was unavailable, which never made it into the DB).
        deals = CONCURRENT_DEAL_PIPELINE.get(user_id, [])
        for d in deals:
            if d.get("deal_id") == deal_id:
                previous_stage = d.get("stage")
                d["stage"] = new_stage
                if notes:
                    d["notes"] = notes
                if proposed_price is not None:
                    d["proposed_price"] = proposed_price
                d["updated_at"] = _now().isoformat()
                # Keep an audit trail: which stages a deal passed through
                # and when is exactly what a post-mortem on a lost bid needs.
                # Same rule as the Postgres branch — a same-stage edit is
                # not a transition.
                if new_stage != previous_stage:
                    d.setdefault("stage_history", []).append({
                        "from": previous_stage,
                        "to": new_stage,
                        "at": d["updated_at"],
                    })
                    logger.info(f"📈 Deal {deal_id} moved {previous_stage} -> {new_stage} (in-memory)")
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
        entered_at = _as_aware(deal.get("created_at"))
        if entered_at is None:
            return {}
        now = _as_aware(now) or _now()

        current_stage = "discovery"
        durations: Dict[str, float] = {}
        for entry in deal.get("stage_history", []):
            left_at = _as_aware(entry.get("at"))
            if left_at is None:
                continue
            days = max(0.0, (left_at - entered_at).total_seconds() / 86400)
            durations[current_stage] = durations.get(current_stage, 0.0) + days
            current_stage = entry.get("to", current_stage)
            entered_at = left_at

        days_in_current = max(0.0, (now - entered_at).total_seconds() / 86400)
        durations[current_stage] = durations.get(current_stage, 0.0) + days_in_current
        return durations

    @staticmethod
    async def get_pipeline_metrics(user_id: str) -> Dict[str, Any]:
        """Real pipeline analytics over the user's current deals: value
        weighted by stage-based win probability, actual time spent per
        stage (from transition timestamps, not estimated), and funnel
        conversion rates derived from which stages each deal has actually
        reached — not fixed/seeded numbers.
        """
        deals = await ConcurrentWorkflowEngine.get_pipeline_for_user(user_id)
        now = _now()

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
