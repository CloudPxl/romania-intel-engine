import asyncio
import os
import time
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger("DB")

DATABASE_URL = os.getenv("DATABASE_URL", "")

_pool: Optional[asyncpg.Pool] = None
_warned_no_db = False
_pool_lock = asyncio.Lock()
# Why the last pool build failed, for /api/v1/system/status. Without this
# the operator sees an empty feed and has no way to tell an unreachable
# database from a market with nothing in it.
_last_pool_error: Optional[str] = None

# A failed pool build leaves _pool as None, so without a cooldown the very
# next caller tries to connect again — meaning one connection attempt per
# HTTP request, per scraper, per status check, indefinitely. Against
# rejected credentials that is a sustained authentication-failure storm,
# and Supabase's pooler answers it by tripping a circuit breaker
# ("ECIRCUITBREAKER: too many authentication failures, new connections are
# temporarily blocked") — which then keeps the database unreachable even
# once the password is corrected, because the storm never pauses long
# enough for the breaker to reset. Observed in production. Short enough to
# recover within a few seconds of a real fix; long enough that a bad
# credential costs ~2 attempts a minute instead of thousands.
POOL_RETRY_COOLDOWN_SECONDS = 30.0
_pool_retry_after = 0.0

# Supabase closes server-side connections that have been idle for a while.
# asyncpg does not know that has happened and will hand the dead connection
# to the next caller, which then fails — the symptom is an endpoint that
# returns 200, 200, then 500 for no visible reason. Recycling connections
# well before the server's idle cutoff prevents most of it, and
# with_connection() below recovers from the rest.
POOL_MAX_INACTIVE_SECONDS = 180.0
POOL_ACQUIRE_TIMEOUT = 15.0
COMMAND_TIMEOUT = 30.0

# Raised when a pooled connection turns out to be dead. Recreating the pool
# and retrying once clears it.
_CONNECTION_ERRORS = (
    asyncpg.exceptions.ConnectionDoesNotExistError,
    asyncpg.exceptions.InterfaceError,
    asyncpg.exceptions.TooManyConnectionsError,
    ConnectionError,
    OSError,
)


async def get_pool() -> Optional[asyncpg.Pool]:
    """Lazily creates a small connection pool against Supabase. Returns None
    (rather than raising) if DATABASE_URL isn't set, so callers can degrade
    gracefully instead of crashing the whole process."""
    global _pool, _warned_no_db, _last_pool_error, _pool_retry_after
    if _pool is not None:
        return _pool
    if not DATABASE_URL:
        if not _warned_no_db:
            logger.warning("[DB] DATABASE_URL not set — persistence disabled.")
            _warned_no_db = True
        return None
    if time.monotonic() < _pool_retry_after:
        return None
    async with _pool_lock:
        # Re-check inside the lock: several concurrent scrapers hit this on
        # a cold start and would otherwise each build their own pool.
        if _pool is not None:
            return _pool
        # Re-check the cooldown too — callers that queued on the lock while
        # another one was failing must not each fire their own attempt.
        if time.monotonic() < _pool_retry_after:
            return None
        kwargs: Dict[str, Any] = {
            "min_size": 1,
            "max_size": 5,
            "max_inactive_connection_lifetime": POOL_MAX_INACTIVE_SECONDS,
            "command_timeout": COMMAND_TIMEOUT,
        }
        if _is_transaction_pooler(DATABASE_URL):
            # Supabase's transaction pooler multiplexes one server-side
            # connection across clients, so it cannot keep per-session
            # prepared statements. asyncpg prepares statements by default
            # and would fail with "prepared statement _asyncpg_ already
            # exists" partway through a run. Disabling the statement cache
            # is what makes the pooler usable at all — and the pooler is
            # the right endpoint for short-lived free-tier dynos, whose
            # direct connections get dropped.
            kwargs["statement_cache_size"] = 0
            logger.info("[DB] Transaction pooler detected — prepared statement cache disabled.")
        try:
            _pool = await asyncpg.create_pool(DATABASE_URL, **kwargs)
            _last_pool_error = None
            _pool_retry_after = 0.0
        except Exception as e:
            _last_pool_error = _redact(f"{type(e).__name__}: {e}")
            _pool_retry_after = time.monotonic() + POOL_RETRY_COOLDOWN_SECONDS
            logger.error(
                f"[DB] Failed to create connection pool ({_last_pool_error}); "
                f"backing off {POOL_RETRY_COOLDOWN_SECONDS:.0f}s before retrying."
            )
            return None
    return _pool


def _redact(text: str) -> str:
    """Strips credentials out of a connection error before it can be
    returned over HTTP — asyncpg happily echoes the DSN in some parse
    errors, and the DSN carries the database password."""
    import re
    return re.sub(r"(?i)(postgres(?:ql)?://)[^\s'\"]*", r"\1<redacted>", text)


async def connectivity() -> Dict[str, Any]:
    """Whether persistence is configured AND actually reachable right now.

    Every read in this module returns None/empty for both "no database"
    and "database says nothing", which is correct for degrading gracefully
    but leaves an operator unable to tell an outage from an empty market —
    the exact ambiguity that made a silently-unconfigured deploy look like
    a working site with no opportunities in it. This answers the question
    directly, and is cheap enough to run on the status endpoint.
    """
    if not DATABASE_URL:
        return {"configured": False, "reachable": False, "detail": "DATABASE_URL is not set"}
    if time.monotonic() < _pool_retry_after and _pool is None:
        retry_in = round(_pool_retry_after - time.monotonic())
        return {
            "configured": True,
            "reachable": False,
            "detail": f"{_last_pool_error or 'connection failed'} (backing off, retrying in ~{retry_in}s)",
        }
    pool = await get_pool()
    if pool is None:
        return {"configured": True, "reachable": False, "detail": _last_pool_error or "connection pool unavailable"}
    try:
        async with pool.acquire(timeout=POOL_ACQUIRE_TIMEOUT) as conn:
            await conn.execute("SELECT 1")
        return {"configured": True, "reachable": True, "detail": None}
    except Exception as e:
        return {"configured": True, "reachable": False, "detail": _redact(f"{type(e).__name__}: {e}")}


async def is_available() -> bool:
    """Fast check used on the read path: is there a usable pool at all?"""
    return await get_pool() is not None


def _is_transaction_pooler(url: str) -> bool:
    """Supabase exposes the transaction pooler on port 6543, and its pooler
    hosts are *.pooler.supabase.com. Detected rather than configured so the
    connection string can be switched in the dashboard without a redeploy."""
    return ":6543" in url or "pooler.supabase.com" in url


async def _reset_pool() -> None:
    global _pool, _pool_retry_after
    # Clearing the cooldown is deliberate: this path means we *had* a
    # working pool whose connection went stale, which is a different
    # failure from credentials being refused, and deserves one immediate
    # rebuild. If that rebuild also fails, get_pool() arms a fresh cooldown.
    _pool_retry_after = 0.0
    async with _pool_lock:
        if _pool is not None:
            try:
                await asyncio.wait_for(_pool.close(), timeout=5)
            except Exception:
                _pool.terminate()
            _pool = None


@asynccontextmanager
async def with_connection():
    """Yields a live connection, transparently rebuilding the pool once if
    the one it got turns out to be dead. Yields None when no database is
    configured, so every caller keeps its existing degrade-gracefully path.
    """
    pool = await get_pool()
    if pool is None:
        yield None
        return
    try:
        async with pool.acquire(timeout=POOL_ACQUIRE_TIMEOUT) as conn:
            yield conn
        return
    except _CONNECTION_ERRORS as e:
        logger.warning(f"[DB] Stale/failed connection ({type(e).__name__}); rebuilding pool and retrying once.")

    await _reset_pool()
    pool = await get_pool()
    if pool is None:
        yield None
        return
    async with pool.acquire(timeout=POOL_ACQUIRE_TIMEOUT) as conn:
        yield conn


async def upsert_opportunity(record: Dict[str, Any]) -> bool:
    """Insert or refresh an opportunity by source_id. Returns True only if
    this is a brand-new row (used to gate matching/alerting on genuinely new
    signals, not every re-scrape of an already-seen listing)."""
    async with with_connection() as conn:
        if conn is None:
            return True  # no persistence configured — treat every signal as new
        query = """
            INSERT INTO opportunities (
                source_id, source_type, category, sub_category, county, locality,
                entity_name, project_title, estimated_value_ron, caen_codes, cpv_code,
                published_date, action_deadline, raw_description, executive_summary,
                sales_pitch_angle, funding_source, opportunity_score, source_url,
                document_url, metadata, last_seen_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                $16, $17, $18, $19, $20, $21, now()
            )
            ON CONFLICT (source_id) DO UPDATE SET
                estimated_value_ron = EXCLUDED.estimated_value_ron,
                action_deadline = EXCLUDED.action_deadline,
                opportunity_score = EXCLUDED.opportunity_score,
                metadata = EXCLUDED.metadata,
                last_seen_at = now()
            RETURNING (xmax = 0) AS inserted
        """
        row = await conn.fetchrow(
            query,
            record.get("source_id"),
            record.get("source_type"),
            record.get("category"),
            record.get("sub_category"),
            record.get("county"),
            record.get("locality"),
            record.get("entity_name"),
            record.get("project_title"),
            record.get("estimated_value_ron") or record.get("financial_value_ron") or 0,
            record.get("caen_codes") or [],
            record.get("cpv_code"),
            _parse_date(record.get("published_date")),
            _parse_date(record.get("action_deadline")),
            record.get("raw_description"),
            record.get("executive_summary"),
            record.get("sales_pitch_angle"),
            record.get("funding_source"),
            record.get("opportunity_score"),
            record.get("source_url"),
            record.get("document_url"),
            _to_jsonb(record.get("metadata") or {}),
        )
    return bool(row["inserted"]) if row else True


def _parse_date(value: Any) -> Optional[date]:
    """asyncpg requires real datetime.date objects for DATE columns — it
    does not auto-cast strings the way some other drivers do."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _to_jsonb(value: Dict[str, Any]) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, default=str)


async def get_recent_opportunities(
    limit: int = 300,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    counties: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    min_value_ron: Optional[float] = None,
    max_value_ron: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Reads opportunities, optionally narrowed to a market-analysis slice.

    Every filter is optional and additive (AND'd together) so the market
    analysis endpoint can build exactly the query the client asked for —
    "only Health projects in Cluj > 1M RON" — without a separate query
    method per combination. Date filtering runs against
    COALESCE(published_date, last_seen_at::date): many sources (CNI,
    PNRR calls) never publish a date at all, and dropping those rows
    silently out of every date-bounded report would make "accurate"
    reporting quietly incomplete for exactly the sources that already
    have the weakest metadata.
    """
    conditions: List[str] = []
    params: List[Any] = []

    def _add(condition_tpl: str, value: Any) -> None:
        params.append(value)
        conditions.append(condition_tpl.format(n=len(params)))

    if start_date is not None:
        _add("COALESCE(published_date, last_seen_at::date) >= ${n}", start_date)
    if end_date is not None:
        _add("COALESCE(published_date, last_seen_at::date) <= ${n}", end_date)
    if counties:
        _add("county = ANY(${n}::text[])", list(counties))
    if categories:
        _add("category = ANY(${n}::text[])", list(categories))
    if min_value_ron is not None:
        _add("estimated_value_ron >= ${n}", min_value_ron)
    if max_value_ron is not None:
        _add("estimated_value_ron <= ${n}", max_value_ron)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    query = f"SELECT * FROM opportunities {where_clause} ORDER BY last_seen_at DESC LIMIT ${len(params)}"

    async with with_connection() as conn:
        if conn is None:
            return []
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


async def is_source_due(source_name: str, poll_interval_minutes: int) -> bool:
    async with with_connection() as conn:
        if conn is None:
            return True
        row = await conn.fetchrow(
            "SELECT last_run_at FROM source_run_log WHERE source_name = $1", source_name
        )
    if row is None or row["last_run_at"] is None:
        return True
    elapsed = (datetime.now(timezone.utc) - row["last_run_at"]).total_seconds() / 60
    return elapsed >= poll_interval_minutes


async def record_source_run(
    source_name: str,
    status: str,
    records: int,
    error: Optional[str] = None,
    poll_interval_minutes: int = 360,
) -> None:
    async with with_connection() as conn:
        if conn is None:
            return
        if status == "SUCCESS":
            await conn.execute(
                """
                INSERT INTO source_run_log (source_name, poll_interval_minutes, last_run_at,
                    last_success_at, last_error, consecutive_failures, records_last_run)
                VALUES ($1, $2, now(), now(), NULL, 0, $3)
                ON CONFLICT (source_name) DO UPDATE SET
                    last_run_at = now(),
                    last_success_at = now(),
                    last_error = NULL,
                    consecutive_failures = 0,
                    records_last_run = EXCLUDED.records_last_run
                """,
                source_name, poll_interval_minutes, records,
            )
        else:
            await conn.execute(
                """
                INSERT INTO source_run_log (source_name, poll_interval_minutes, last_run_at,
                    last_error, consecutive_failures, records_last_run)
                VALUES ($1, $2, now(), $3, 1, 0)
                ON CONFLICT (source_name) DO UPDATE SET
                    last_run_at = now(),
                    last_error = EXCLUDED.last_error,
                    consecutive_failures = source_run_log.consecutive_failures + 1
                """,
                source_name, poll_interval_minutes, error,
            )


async def get_circuit_state(source_name: str) -> str:
    async with with_connection() as conn:
        if conn is None:
            return "closed"
        row = await conn.fetchrow(
            "SELECT circuit_state, circuit_opened_at FROM source_run_log WHERE source_name = $1",
            source_name,
        )
    if row is None:
        return "closed"
    if row["circuit_state"] == "open" and row["circuit_opened_at"]:
        cooldown_elapsed = (datetime.now(timezone.utc) - row["circuit_opened_at"]).total_seconds() / 60
        if cooldown_elapsed >= 30:
            await half_open_circuit(source_name)
            return "half_open"
    return row["circuit_state"]


async def open_circuit(source_name: str) -> None:
    async with with_connection() as conn:
        if conn is None:
            return
        await conn.execute(
            """
            UPDATE source_run_log SET circuit_state = 'open', circuit_opened_at = now()
            WHERE source_name = $1
            """,
            source_name,
        )
    logger.warning(f"[CircuitBreaker] OPEN for source={source_name}")


async def half_open_circuit(source_name: str) -> None:
    async with with_connection() as conn:
        if conn is None:
            return
        await conn.execute(
            "UPDATE source_run_log SET circuit_state = 'half_open' WHERE source_name = $1",
            source_name,
        )


async def close_circuit(source_name: str) -> None:
    async with with_connection() as conn:
        if conn is None:
            return
        await conn.execute(
            "UPDATE source_run_log SET circuit_state = 'closed', circuit_opened_at = NULL WHERE source_name = $1",
            source_name,
        )


async def has_alert_been_dispatched(tenant_id: str, source_id: str, channel: str) -> bool:
    async with with_connection() as conn:
        if conn is None:
            return False
        row = await conn.fetchrow(
            """
            SELECT 1 FROM tenant_alert_dispatch_log
            WHERE tenant_id = $1 AND source_id = $2 AND channel = $3
            """,
            tenant_id, source_id, channel,
        )
    return row is not None


async def record_alert_dispatch(tenant_id: str, source_id: str, channel: str) -> None:
    async with with_connection() as conn:
        if conn is None:
            return
        await conn.execute(
            """
            INSERT INTO tenant_alert_dispatch_log (tenant_id, source_id, channel)
            VALUES ($1, $2, $3)
            ON CONFLICT (tenant_id, source_id, channel) DO NOTHING
            """,
            tenant_id, source_id, channel,
        )


async def start_tick() -> Optional[int]:
    async with with_connection() as conn:
        if conn is None:
            return None
        row = await conn.fetchrow(
            "INSERT INTO system_ticks (started_at) VALUES (now()) RETURNING id"
        )
    return row["id"] if row else None


async def finish_tick(tick_id: Optional[int], sources_run: int, new_count: int, errors: int) -> None:
    if tick_id is None:
        return
    async with with_connection() as conn:
        if conn is None:
            return
        await conn.execute(
            """
            UPDATE system_ticks SET completed_at = now(), sources_run = $2,
                new_opportunities = $3, errors = $4
            WHERE id = $1
            """,
            tick_id, sources_run, new_count, errors,
        )


async def get_last_successful_tick() -> Optional[datetime]:
    async with with_connection() as conn:
        if conn is None:
            return None
        row = await conn.fetchrow(
            "SELECT completed_at FROM system_ticks WHERE errors = 0 AND completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 1"
        )
    return row["completed_at"] if row else None


# ---------------------------------------------------------------------------
# Deal pipeline persistence (pipeline_schema.sql). workflow_engine.py falls
# back to its in-memory dict whenever a function here returns the "not
# available" sentinel (None for reads, False for the write) — either because
# DATABASE_URL isn't set, or because pipeline_schema.sql hasn't been applied
# yet (asyncpg.exceptions.UndefinedTableError), so a fresh deploy degrades to
# ephemeral tracking instead of 500ing.
# ---------------------------------------------------------------------------

def _deal_row_to_dict(row: Any) -> Dict[str, Any]:
    d = dict(row)
    for key in ("estimated_value_ron", "target_margin_pct", "proposed_price"):
        if isinstance(d.get(key), Decimal):
            d[key] = float(d[key])
    for key in ("created_at", "updated_at"):
        if isinstance(d.get(key), datetime):
            d[key] = d[key].isoformat()
    return d


async def _fetch_stage_history(conn, deal_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    if not deal_ids:
        return {}
    rows = await conn.fetch(
        "SELECT deal_id, from_stage, to_stage, changed_at FROM deal_stage_history "
        "WHERE deal_id = ANY($1::text[]) ORDER BY changed_at ASC",
        deal_ids,
    )
    history: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        at = row["changed_at"]
        history.setdefault(row["deal_id"], []).append({
            "from": row["from_stage"],
            "to": row["to_stage"],
            "at": at.isoformat() if isinstance(at, datetime) else at,
        })
    return history


async def get_deals_for_tenant(tenant_id: str, product_id: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """None means "couldn't read from Postgres" (caller should fall back to
    the in-memory dict) — a real, empty pipeline is returned as []."""
    async with with_connection() as conn:
        if conn is None:
            return None
        try:
            if product_id:
                rows = await conn.fetch(
                    "SELECT * FROM product_bidding_deals WHERE tenant_id = $1 AND product_id = $2 ORDER BY created_at",
                    tenant_id, product_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM product_bidding_deals WHERE tenant_id = $1 ORDER BY created_at",
                    tenant_id,
                )
            deals = [_deal_row_to_dict(r) for r in rows]
            history = await _fetch_stage_history(conn, [d["deal_id"] for d in deals])
            for d in deals:
                d["stage_history"] = history.get(d["deal_id"], [])
            return deals
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] product_bidding_deals not found — run pipeline_schema.sql. Falling back to in-memory pipeline.")
            return None


async def add_deal(deal: Dict[str, Any]) -> bool:
    async with with_connection() as conn:
        if conn is None:
            return False
        try:
            await conn.execute(
                """
                INSERT INTO product_bidding_deals (
                    deal_id, tenant_id, product_id, opportunity_id, project_title, stage,
                    assigned_to, target_margin_pct, estimated_value_ron, notes, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                deal["deal_id"], deal["tenant_id"], deal.get("product_id"), deal.get("opportunity_id"),
                deal.get("project_title", ""), deal.get("stage", "discovery"), deal.get("assigned_to"),
                deal.get("target_margin_pct"), deal.get("estimated_value_ron") or 0.0, deal.get("notes", ""),
                _parse_timestamp(deal.get("created_at")),
            )
            return True
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] product_bidding_deals not found — run pipeline_schema.sql. Falling back to in-memory pipeline.")
            return False


async def get_deal(tenant_id: str, deal_id: str) -> Optional[Dict[str, Any]]:
    async with with_connection() as conn:
        if conn is None:
            return None
        try:
            row = await conn.fetchrow(
                "SELECT * FROM product_bidding_deals WHERE tenant_id = $1 AND deal_id = $2",
                tenant_id, deal_id,
            )
        except asyncpg.exceptions.UndefinedTableError:
            return None
    if row is None:
        return None
    deal = _deal_row_to_dict(row)
    async with with_connection() as conn:
        if conn is not None:
            deal["stage_history"] = (await _fetch_stage_history(conn, [deal_id])).get(deal_id, [])
    return deal


async def update_deal(
    tenant_id: str,
    deal_id: str,
    new_stage: str,
    notes: Optional[str],
    proposed_price: Optional[float],
    updated_at: str,
) -> Optional[Dict[str, Any]]:
    async with with_connection() as conn:
        if conn is None:
            return None
        try:
            row = await conn.fetchrow(
                """
                UPDATE product_bidding_deals
                SET stage = $3,
                    notes = COALESCE($4, notes),
                    proposed_price = COALESCE($5, proposed_price),
                    updated_at = $6
                WHERE tenant_id = $1 AND deal_id = $2
                RETURNING *
                """,
                tenant_id, deal_id, new_stage, notes, proposed_price, _parse_timestamp(updated_at),
            )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] product_bidding_deals not found — run pipeline_schema.sql. Falling back to in-memory pipeline.")
            return None
    if row is None:
        return None
    return _deal_row_to_dict(row)


async def record_stage_transition(deal_id: str, from_stage: Optional[str], to_stage: str, at: str) -> None:
    async with with_connection() as conn:
        if conn is None:
            return
        try:
            await conn.execute(
                "INSERT INTO deal_stage_history (deal_id, from_stage, to_stage, changed_at) VALUES ($1, $2, $3, $4)",
                deal_id, from_stage, to_stage, _parse_timestamp(at),
            )
        except asyncpg.exceptions.UndefinedTableError:
            pass


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Deal timestamps are generated as datetime.now().isoformat() strings
    in workflow_engine.py; asyncpg needs real datetime objects for
    TIMESTAMPTZ columns, same reasoning as _parse_date() above."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
