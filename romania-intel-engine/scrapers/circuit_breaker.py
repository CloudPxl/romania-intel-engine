import logging
from typing import Any, Dict, Optional

import db

logger = logging.getLogger("CircuitBreaker")

OPEN_AFTER_FAILURES = 3

# A scraper that quietly returns an honest empty list on every poll is,
# from the circuit breaker's perspective above, indistinguishable from one
# whose target site changed shape and broke — neither throws, so neither
# opens the circuit. This is a second, independent staleness signal that
# reacts to a zero-result streak instead of exceptions. The dual gate
# scales the *wall-clock* silence window with each source's own polling
# cadence rather than a fixed tick count: a 10-minute source needs ~288
# zero-signal ticks (48h) before alerting, a 6-hour source needs 8 ticks
# (48h), and the slowest, 24-hour sources are bound by the 5-tick floor
# instead — 5 days, deliberately conservative so a multi-day site hiccup
# on the least-frequently-polled sources can't false-positive.
STALE_ZERO_STREAK_MIN_TICKS = 5
STALE_ZERO_STREAK_MIN_MINUTES = 48 * 60


async def is_open(source_name: str) -> bool:
    state = await db.get_circuit_state(source_name)
    return state == "open"


def _is_stale_streak(row: Dict[str, Any]) -> bool:
    if row.get("stale_alert_fired_at") is not None:
        return False
    streak = row.get("consecutive_zero_result_runs") or 0
    interval = row.get("poll_interval_minutes") or 360
    return streak >= STALE_ZERO_STREAK_MIN_TICKS and streak * interval >= STALE_ZERO_STREAK_MIN_MINUTES


async def record_result(source_name: str, success: bool, error: Optional[str], records: int,
                         poll_interval_minutes: int = 360) -> None:
    row = await db.record_source_run(
        source_name,
        "SUCCESS" if success else "ERROR",
        records,
        error,
        poll_interval_minutes,
    )
    if success:
        await db.close_circuit(source_name)
        if row and _is_stale_streak(row):
            await db.mark_stale_alert_fired(source_name)
            await _fire_stale_alert(source_name, row["consecutive_zero_result_runs"], row["poll_interval_minutes"])
        return

    async with db.with_connection() as conn:
        if conn is None:
            return
        row = await conn.fetchrow(
            "SELECT consecutive_failures FROM source_run_log WHERE source_name = $1", source_name
        )
    failures = row["consecutive_failures"] if row else 1
    if failures >= OPEN_AFTER_FAILURES:
        await db.open_circuit(source_name)
        await _fire_admin_alert(source_name, failures, error)


async def _fire_admin_alert(source_name: str, failures: int, error: Optional[str]) -> None:
    try:
        from notifier import LeadAlertDispatcher
        await LeadAlertDispatcher.dispatch_admin_alert(
            f"⚠️ Circuit OPEN pentru sursa '{source_name}' după {failures} eșecuri consecutive.\nUltima eroare: {error}"
        )
    except Exception as e:
        logger.error(f"[CircuitBreaker] Failed to fire admin alert for {source_name}: {e}")


async def _fire_stale_alert(source_name: str, streak: int, interval_minutes: int) -> None:
    hours = round(streak * interval_minutes / 60, 1)
    try:
        from notifier import LeadAlertDispatcher
        await LeadAlertDispatcher.dispatch_admin_alert(
            f"🔇 Sursa '{source_name}' a returnat 0 semnale în {streak} rulări consecutive "
            f"(~{hours}h) — verificați dacă structura paginii sursă s-a schimbat."
        )
    except Exception as e:
        logger.error(f"[CircuitBreaker] Failed to fire staleness alert for {source_name}: {e}")
