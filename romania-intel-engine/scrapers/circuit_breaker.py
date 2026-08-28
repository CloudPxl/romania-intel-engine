import logging
from typing import Optional

import db

logger = logging.getLogger("CircuitBreaker")

OPEN_AFTER_FAILURES = 3


async def is_open(source_name: str) -> bool:
    state = await db.get_circuit_state(source_name)
    return state == "open"


async def record_result(source_name: str, success: bool, error: Optional[str], records: int,
                         poll_interval_minutes: int = 360) -> None:
    await db.record_source_run(
        source_name,
        "SUCCESS" if success else "ERROR",
        records,
        error,
        poll_interval_minutes,
    )
    if success:
        await db.close_circuit(source_name)
        return

    pool = await db.get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
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
