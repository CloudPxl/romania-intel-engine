import asyncio
import os
import re
import time
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import asyncpg

from text_utils import fold

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
            # Was 5 — shared by every concurrent request, the ingestion
            # tick, and the document worker at once. Fine for a single
            # developer; a 6th simultaneous DB-touching request (trivial
            # once a handful of users' dashboards overlap) just
            # queued silently behind it instead of erroring. Still the
            # same free Supabase project — this only raises the client-
            # side ceiling, so it's worth confirming Supabase's own
            # connection cap for this project isn't lower than this.
            "max_size": 20,
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

    # The retry deliberately wraps only `acquire()`, never the caller's own
    # query. An @asynccontextmanager may yield exactly once: when the body
    # raises, contextlib throws that exception back in at the `yield`, and
    # yielding a second time makes contextlib raise
    # `RuntimeError: generator didn't stop after athrow()` — masking the real
    # error rather than retrying it. Wrapping the yield in try/except (as this
    # did before) therefore turned an ordinary stale-connection error into an
    # unhandled RuntimeError at every call site — including, at the time,
    # the tenant-membership guard, which had no broad except of its own and
    # would 500 instead of cleanly allowing or denying.
    try:
        conn = await pool.acquire(timeout=POOL_ACQUIRE_TIMEOUT)
    except _CONNECTION_ERRORS as e:
        logger.warning(f"[DB] Stale/failed connection ({type(e).__name__}); rebuilding pool and retrying once.")
        await _reset_pool()
        pool = await get_pool()
        if pool is None:
            yield None
            return
        conn = await pool.acquire(timeout=POOL_ACQUIRE_TIMEOUT)

    try:
        yield conn
    finally:
        await pool.release(conn)


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
                published_date, action_deadline, executive_summary,
                sales_pitch_angle, funding_source, opportunity_score, source_url,
                document_url, metadata, search_blob, last_seen_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                $15, $16, $17, $18, $19, $20, $21, now()
            )
            ON CONFLICT (source_id) DO UPDATE SET
                estimated_value_ron = EXCLUDED.estimated_value_ron,
                action_deadline = EXCLUDED.action_deadline,
                opportunity_score = EXCLUDED.opportunity_score,
                metadata = EXCLUDED.metadata,
                search_blob = EXCLUDED.search_blob,
                last_seen_at = now()
            RETURNING (xmax = 0) AS inserted
        """
        # `executive_summary` is where the descriptive text actually lives.
        # refine_signal maps the source's raw_description into it and never
        # emits a `raw_description` key of its own, which is why the column
        # of that name was NULL on every row ever written and has now been
        # dropped. The search blob must read the same four fields the
        # Python matcher reads, or SQL ranking and Python alerting would
        # disagree about what a keyword matches.
        summary = record.get("executive_summary")
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
            summary,
            record.get("sales_pitch_angle"),
            record.get("funding_source"),
            record.get("opportunity_score"),
            record.get("source_url"),
            record.get("document_url"),
            _to_jsonb(record.get("metadata") or {}),
            build_search_blob(record),
        )
    return bool(row["inserted"]) if row else True


def build_search_blob(record: Dict[str, Any]) -> str:
    """The pre-folded haystack the ranked feed matches keywords against.

    Folded here, on write, with the same text_utils.fold() the Python
    matcher uses — so a keyword either matches in both places or in
    neither. Doing it in SQL instead (unaccent() at query time) would need
    the extension, defeat any index, and disagree with fold() on the
    legacy cedilla forms (ş/ţ) that Romanian institutional sites emit
    alongside the correct comma-below ones.

    The field list is deliberately the same one matching_engine reads.
    Exported (not underscore-private) so the matcher can build the same
    string for an in-memory signal that has not been persisted yet.
    """
    parts = (
        record.get("project_title"),
        record.get("executive_summary"),
        record.get("sub_category"),
        record.get("entity_name"),
    )
    return fold(" ".join(str(p) for p in parts if p))


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
    # Case-insensitive on both sides, because api.py:_apply_feed_filters —
    # the same filters re-applied in Python against the file cache when
    # Postgres is down — lower-cases both sides too. With an exact-case
    # comparison here, `?counties=cluj` matched nothing while the database
    # was healthy and started matching the moment it degraded, which reads
    # as an intermittently broken filter. County values are written by the
    # scrapers in whatever case the source published ("Cluj", "CLUJ"), so
    # the forgiving comparison is also the correct one.
    # scraper_matrix_schema.sql carries lower(county)/lower(category)
    # expression indexes for these predicates; a plain btree on the bare
    # column cannot serve them.
    if counties:
        _add("lower(county) = ANY(${n}::text[])", [str(c).lower() for c in counties])
    if categories:
        _add("lower(category) = ANY(${n}::text[])", [str(c).lower() for c in categories])
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


# --- The ranked feed ------------------------------------------------------
#
# A SOFT filter, deliberately: the feed returns the whole market and sorts
# it, rather than hiding what does not match. A hard filter on a narrow
# keyword list produces an empty dashboard, which reads as a broken product
# rather than as a quiet market — and it hides the adjacent work a bidder
# would actually have wanted to see.
#
# These weights order the feed ONLY. They are not the alert threshold:
# matching_engine keeps a hard keyword-evidence gate for alerting, because
# "everything matches a little" is fine for a ranked page and unacceptable
# for an inbox. The two answer different questions and are meant to differ.
RELEVANCE_WEIGHTS = {
    "keyword": 50,   # the strongest signal — the user typed these words
    "county": 20,    # right geography, wrong subject is still worth seeing
    "domain": 15,
    "value": 10,     # clears their minimum contract size
    "excluded": -100,  # sinks below everything; never removed
}

# Mirrors text_utils.fold()'s Romanian map for the one column that is not
# pre-folded. county is short and low-cardinality, so calling this per row
# is cheap; the alternative is another stored column for no real gain.
_PG_FOLD = "translate(lower({col}), 'ăĂâÂîÎșȘşŞțȚţŢ', 'aaaaiisssstttt')"


def _pg_word_patterns(terms: Optional[List[str]]) -> List[str]:
    """Folded whole-word POSIX patterns for `search_blob ~ ANY(...)`.

    Whole-word matters as much as the folding, and for the same reason
    text_utils.contains_term says so: a substring test lets "sala" match
    "salariu" and "apa" match "apartament", which is how an unrelated
    contract ends up at the top of someone's feed. Postgres spells the
    word boundary \\m ... \\M where Python spells it \\b.
    """
    patterns: List[str] = []
    for term in terms or []:
        parts = re.findall(r"[a-z0-9]+", fold(str(term)))
        if parts:
            patterns.append(r"\m" + r"\s+".join(parts) + r"\M")
    return patterns


async def get_ranked_opportunities(
    profile: Dict[str, Any], limit: int = 300
) -> List[Dict[str, Any]]:
    """The whole market, ordered by how well it fits this user.

    Returns each row with a `relevance` score plus the individual boolean
    hits that produced it, so the caller can explain the ranking in the UI
    without re-running any matching in Python.
    """
    keywords = _pg_word_patterns(profile.get("keywords"))
    excludes = _pg_word_patterns(profile.get("exclude_keywords"))
    counties = [fold(str(c)) for c in (profile.get("target_counties") or []) if str(c).strip()]
    domain = (profile.get("domain") or "").strip().lower() or None
    min_value = float(profile.get("min_value_ron") or 0)

    w = RELEVANCE_WEIGHTS
    query = f"""
        SELECT *,
            (COALESCE(search_blob, '') ~ ANY($1::text[])) AS kw_hit,
            ({_PG_FOLD.format(col='county')} = ANY($2::text[])) AS county_hit,
            ($3::text IS NOT NULL AND lower(category) = $3) AS domain_hit,
            ($4::numeric > 0 AND estimated_value_ron >= $4) AS value_hit,
            (COALESCE(search_blob, '') ~ ANY($5::text[])) AS excluded_hit,
            (
                CASE WHEN COALESCE(search_blob, '') ~ ANY($1::text[]) THEN {w['keyword']} ELSE 0 END
              + CASE WHEN {_PG_FOLD.format(col='county')} = ANY($2::text[]) THEN {w['county']} ELSE 0 END
              + CASE WHEN $3::text IS NOT NULL AND lower(category) = $3 THEN {w['domain']} ELSE 0 END
              + CASE WHEN $4::numeric > 0 AND estimated_value_ron >= $4 THEN {w['value']} ELSE 0 END
              + CASE WHEN COALESCE(search_blob, '') ~ ANY($5::text[]) THEN {w['excluded']} ELSE 0 END
              + COALESCE(opportunity_score, 0)
            ) AS relevance
        FROM opportunities
        ORDER BY relevance DESC, last_seen_at DESC
        LIMIT $6
    """
    # `~ ANY('{}')` on an empty array is false for every row, so a user who
    # has set no keywords simply gets an unweighted feed rather than an
    # error or an empty one.
    async with with_connection() as conn:
        if conn is None:
            return []
        rows = await conn.fetch(query, keywords, counties, domain, min_value, excludes, limit)
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


async def has_alert_been_dispatched(user_id: str, source_id: str, channel: str) -> bool:
    """False when there is no database — so an outage re-sends an alert
    rather than dropping it. Duplicates are recoverable; a lead nobody was
    told about is not."""
    async with with_connection() as conn:
        if conn is None:
            return False
        try:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM alert_dispatch_log
                WHERE user_id = $1 AND source_id = $2 AND channel = $3
                """,
                user_id, source_id, channel,
            )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] alert_dispatch_log not found — run schema.sql.")
            return False
    return row is not None


async def record_alert_dispatch(user_id: str, source_id: str, channel: str) -> None:
    async with with_connection() as conn:
        if conn is None:
            return
        try:
            await conn.execute(
                """
                INSERT INTO alert_dispatch_log (user_id, source_id, channel)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, source_id, channel) DO NOTHING
                """,
                user_id, source_id, channel,
            )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] alert_dispatch_log not found — run schema.sql.")


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


# Every deal read and write below is scoped by (user_id, deal_id), never
# by deal_id alone. That is not redundant now that the user comes from the
# JWT: deal ids are guessable (`DEAL-<10 hex>`) and arrive in a request
# body, so without the owner in the WHERE clause any authenticated caller
# could read or advance a stranger's deal by guessing an id. This pair is
# what replaces the deleted require_tenant_membership for this table.


async def get_deals_for_user(user_id: str) -> Optional[List[Dict[str, Any]]]:
    """None means "couldn't read from Postgres" (caller should fall back to
    the in-memory dict) — a real, empty pipeline is returned as []."""
    async with with_connection() as conn:
        if conn is None:
            return None
        try:
            rows = await conn.fetch(
                "SELECT * FROM saved_deals WHERE user_id = $1 ORDER BY created_at",
                user_id,
            )
            deals = [_deal_row_to_dict(r) for r in rows]
            history = await _fetch_stage_history(conn, [d["deal_id"] for d in deals])
            for d in deals:
                d["stage_history"] = history.get(d["deal_id"], [])
            return deals
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] saved_deals not found — run schema.sql. Falling back to in-memory pipeline.")
            return None


async def add_deal(deal: Dict[str, Any]) -> bool:
    async with with_connection() as conn:
        if conn is None:
            return False
        try:
            await conn.execute(
                """
                INSERT INTO saved_deals (
                    deal_id, user_id, opportunity_id, project_title, stage,
                    target_margin_pct, estimated_value_ron, notes, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                deal["deal_id"], deal["user_id"], deal.get("opportunity_id"),
                deal.get("project_title", ""), deal.get("stage", "discovery"),
                deal.get("target_margin_pct"), deal.get("estimated_value_ron") or 0.0,
                deal.get("notes", ""), _parse_timestamp(deal.get("created_at")),
            )
            return True
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] saved_deals not found — run schema.sql. Falling back to in-memory pipeline.")
            return False


async def get_deal(user_id: str, deal_id: str) -> Optional[Dict[str, Any]]:
    async with with_connection() as conn:
        if conn is None:
            return None
        try:
            row = await conn.fetchrow(
                "SELECT * FROM saved_deals WHERE user_id = $1 AND deal_id = $2",
                user_id, deal_id,
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
    user_id: str,
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
                UPDATE saved_deals
                SET stage = $3,
                    notes = COALESCE($4, notes),
                    proposed_price = COALESCE($5, proposed_price),
                    updated_at = $6
                WHERE user_id = $1 AND deal_id = $2
                RETURNING *
                """,
                user_id, deal_id, new_stage, notes, proposed_price, _parse_timestamp(updated_at),
            )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] saved_deals not found — run schema.sql. Falling back to in-memory pipeline.")
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


# ---------------------------------------------------------------------------
# The user profile — the core entity.
#
# There is no tenant, no organisation and no product line. A person signs
# up, sets their own matching criteria, and owns their own data. The
# previous model wrapped that in a tenants -> tenant_products ->
# user_profiles chain that never held more than one row at each level, and
# cost an entire authorization layer to police a {tenant_id} path param
# that could only ever be your own.
# ---------------------------------------------------------------------------

# The columns every profile read returns. Kept in one place because four
# separate queries below select them and drifting between those is how a
# KeyError reaches a route handler.
_PROFILE_COLUMNS = (
    "id, email, display_name, domain, target_counties, keywords, "
    "exclude_keywords, min_value_ron, company_name, cui, alert_email, "
    "telegram_chat_id, min_alert_score, onboarded_at"
)


def _profile_row_to_dict(row: Any) -> Dict[str, Any]:
    """Normalises a profile row for JSON and for the matcher: arrays become
    real lists, NUMERIC becomes float, UUID and timestamps become strings."""
    if row is None:
        return {}
    d = dict(row)
    if d.get("id") is not None:
        d["id"] = str(d["id"])
    for key in ("target_counties", "keywords", "exclude_keywords"):
        d[key] = list(d.get(key) or [])
    d["min_value_ron"] = float(d.get("min_value_ron") or 0.0)
    if d.get("min_alert_score") is not None:
        d["min_alert_score"] = float(d["min_alert_score"])
    if isinstance(d.get("onboarded_at"), datetime):
        d["onboarded_at"] = d["onboarded_at"].isoformat()
    return d


async def get_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """None means "no row for this user" OR "couldn't reach Postgres".

    Both are treated as "not signed up yet" by the routes. Unlike the old
    membership check this is no longer a security boundary — no request can
    name anyone else's profile, because the id comes from the verified JWT
    and never from the URL — so returning None here denies nothing; it just
    sends the caller to onboarding.
    """
    async with with_connection() as conn:
        if conn is None:
            return None
        try:
            row = await conn.fetchrow(
                f"SELECT {_PROFILE_COLUMNS} FROM user_profiles WHERE id = $1", user_id
            )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] user_profiles not found — run schema.sql.")
            return None
    return _profile_row_to_dict(row) if row else None


async def get_onboarded_profiles() -> List[Dict[str, Any]]:
    """Every profile the ingestion tick should match new signals against.

    Read ONCE per tick into a local, never cached in a module-level dict.
    The previous design kept exactly such a cache (TENANT_ORGANIZATIONS)
    and had to be mutated in place with .clear()/.update() forever after,
    because two modules had bound the object by reference at import time —
    reassigning it would have left them iterating stale config with no
    error. A local passed down the call chain has none of that hazard, and
    one SELECT against a tick that already runs for 100-370s is free.
    """
    async with with_connection() as conn:
        if conn is None:
            return []
        try:
            rows = await conn.fetch(
                f"SELECT {_PROFILE_COLUMNS} FROM user_profiles "
                "WHERE onboarded_at IS NOT NULL ORDER BY created_at"
            )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] user_profiles not found — run schema.sql.")
            return []
    return [_profile_row_to_dict(r) for r in rows]


async def upsert_user_profile_email(user_id: str, email: str) -> Optional[Dict[str, Any]]:
    """Called from /api/v1/auth/sync on every login. Creates the bare row if
    this is a new person; never sets matching criteria, so a genuinely new
    user lands with onboarded_at NULL and is sent to the onboarding form.

    One human can hold SEVERAL Supabase auth identities for one email:
    signing in with Google and with a magic link can mint different
    auth.users rows (whether they're linked is a project-level Supabase
    setting, not something this app controls), and re-signing up after an
    account deletion mints another. `user_profiles.id` IS that auth id, so
    the same person can arrive with an id this table has never seen while
    their email is already on a row.

    That case used to be a hard 500 on EVERY login, taking the whole
    product down: the statement was a bare `INSERT ... ON CONFLICT (id)`,
    which handles only an id collision, so a second identity for a known
    email sailed past it and hit the `user_profiles_email_key` unique
    index. The API returned 500, the frontend could not decode it, and the
    user got an infinite sign-in loop.

    So the email, not the auth id, is treated as the identity: it is
    verified by Supabase in both flows, which makes "same email" a
    trustworthy "same person". An existing row is re-pointed onto the
    current auth identity rather than duplicated, so the user keeps their
    criteria and their saved deals instead of being asked to start over.

    KEEP THIS LOGIC. It reads like tenant-era plumbing and is not — it is
    the fix for a live outage, and tests/test_auth_sync_identity.py is its
    only guard.
    """
    async with with_connection() as conn:
        if conn is None:
            return None
        try:
            async with conn.transaction():
                # Serialises two concurrent logins for the same person
                # (double-submit, a client retry, two tabs) so they can't
                # both decide to insert. Keyed on the email, since that is
                # the identity this function resolves.
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext(lower($1)))", email)

                row = await conn.fetchrow(
                    f"SELECT {_PROFILE_COLUMNS} FROM user_profiles WHERE id = $1", user_id
                )
                if row is not None:
                    if row["email"] != email:
                        await conn.execute(
                            "UPDATE user_profiles SET email = $1, updated_at = now() WHERE id = $2",
                            email, user_id,
                        )
                    return {**_profile_row_to_dict(row), "email": email}

                # No row for this auth identity. Adopt one already held by
                # this email, preferring a completed profile so someone with
                # both a stale empty row and a real one keeps the real one.
                existing = await conn.fetchrow(
                    f"""
                    SELECT {_PROFILE_COLUMNS} FROM user_profiles
                    WHERE lower(email) = lower($1)
                    ORDER BY (onboarded_at IS NULL), created_at
                    LIMIT 1
                    """,
                    email,
                )
                if existing is not None:
                    await conn.execute(
                        "UPDATE user_profiles SET id = $1, email = $2, updated_at = now() WHERE id = $3",
                        user_id, email, existing["id"],
                    )
                    logger.info(
                        f"[DB] Re-pointed the profile for {email} onto a new Supabase auth identity."
                    )
                    return {**_profile_row_to_dict(existing), "id": user_id, "email": email}

                row = await conn.fetchrow(
                    f"""
                    INSERT INTO user_profiles (id, email)
                    VALUES ($1, $2)
                    RETURNING {_PROFILE_COLUMNS}
                    """,
                    user_id, email,
                )
                return _profile_row_to_dict(row) if row else None
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] user_profiles not found — run schema.sql.")
            return None


# Signup is self-serve: anyone with a free Supabase account (Google OAuth
# or a magic-link email, no cost and no human review) can complete
# onboarding, and nothing stops one person scripting many accounts. Every
# completed profile is one more iteration of the tick's per-signal
# matching loop, and unbounded growth there degrades ingestion latency for
# everyone, not just the abuser. The cap is deliberately generous — the
# goal is to catch scripted farming, not to constrain real adoption — and
# there is nothing principled about the number beyond "obviously more than
# legitimate usage, obviously less than a script would create".
#
# The env var keeps its old name so the value already set on the deployed
# service continues to apply; renaming it in code alone would silently
# reset the cap to the default on the next restart.
MAX_USER_PROFILES = int(os.getenv("MAX_SELF_PROVISIONED_TENANTS", "300"))


class UserCapacityError(Exception):
    """Raised by complete_onboarding when MAX_USER_PROFILES is reached.

    A real exception rather than folding into this module's `return None`
    convention: None already means two ordinary, expected outcomes here (no
    database; already onboarded). Hitting the cap is an operational anomaly
    worth the operator finding out about — api.py fires an admin alert on
    it — so it must be distinguishable from the routine cases.
    """


async def complete_onboarding(
    user_id: str,
    email: str,
    display_name: Optional[str],
    domain: str,
    target_counties: List[str],
    min_value_ron: float,
    keywords: List[str],
    exclude_keywords: List[str],
) -> Optional[Dict[str, Any]]:
    """Turns a bare signed-in row into a configured profile.

    Returns the profile on success, None when there is no database or the
    user has already onboarded (the route turns the latter into a 409 and
    points them at PUT /api/v1/me/profile instead). Raises
    UserCapacityError at the cap.
    """
    async with with_connection() as conn:
        if conn is None:
            return None
        try:
            async with conn.transaction():
                # Closes a real race: under READ COMMITTED two concurrent
                # onboarding calls for one user (double-submit, a client
                # retry) could both read "not onboarded yet" and both
                # proceed. Transaction-scoped, so it releases on commit.
                await conn.fetchval("SELECT pg_advisory_xact_lock(hashtext($1))", user_id)

                existing = await conn.fetchrow(
                    "SELECT onboarded_at FROM user_profiles WHERE id = $1", user_id
                )
                if existing is not None and existing["onboarded_at"] is not None:
                    return None

                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM user_profiles WHERE onboarded_at IS NOT NULL"
                )
                if count is not None and count >= MAX_USER_PROFILES:
                    raise UserCapacityError(
                        f"{count} profiles already exist (cap {MAX_USER_PROFILES})."
                    )

                row = await conn.fetchrow(
                    f"""
                    INSERT INTO user_profiles (
                        id, email, display_name, domain, target_counties,
                        min_value_ron, keywords, exclude_keywords,
                        alert_email, min_alert_score, onboarded_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $2, 7.5, now())
                    ON CONFLICT (id) DO UPDATE SET
                        email = EXCLUDED.email,
                        display_name = EXCLUDED.display_name,
                        domain = EXCLUDED.domain,
                        target_counties = EXCLUDED.target_counties,
                        min_value_ron = EXCLUDED.min_value_ron,
                        keywords = EXCLUDED.keywords,
                        exclude_keywords = EXCLUDED.exclude_keywords,
                        -- Alerts default to the signup address, but never
                        -- overwrite one the user has already chosen.
                        alert_email = COALESCE(user_profiles.alert_email, EXCLUDED.alert_email),
                        onboarded_at = now(),
                        updated_at = now()
                    RETURNING {_PROFILE_COLUMNS}
                    """,
                    user_id, email, display_name, domain, target_counties,
                    min_value_ron, keywords, exclude_keywords,
                )
                return _profile_row_to_dict(row) if row else None
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] user_profiles not found — run schema.sql.")
            return None


async def update_profile(user_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Partial update of whatever the caller actually sent.

    Built dynamically rather than as one fixed UPDATE so that editing only
    the keyword list cannot blank out the county list — a PUT that always
    wrote every column would do exactly that for any client sending a
    partial body.
    """
    allowed = (
        "display_name", "domain", "target_counties", "keywords",
        "exclude_keywords", "min_value_ron", "company_name", "cui",
    )
    sets: List[str] = []
    params: List[Any] = [user_id]
    for key in allowed:
        if key in fields:
            params.append(fields[key])
            sets.append(f"{key} = ${len(params)}")
    if not sets:
        return await get_profile(user_id)

    async with with_connection() as conn:
        if conn is None:
            return None
        try:
            row = await conn.fetchrow(
                f"""
                UPDATE user_profiles SET {', '.join(sets)}, updated_at = now()
                WHERE id = $1
                RETURNING {_PROFILE_COLUMNS}
                """,
                *params,
            )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] user_profiles not found — run schema.sql.")
            return None
    return _profile_row_to_dict(row) if row else None


async def update_alert_settings(
    user_id: str,
    alert_email: str,
    min_alert_score: float,
    telegram_chat_id: Optional[str] = None,
) -> bool:
    """Where automated alerts go and at what score they fire.

    telegram_chat_id None means "leave whatever is stored alone" (the
    caller didn't submit the field); an empty string clears it to SQL NULL,
    so notifier.py's `if not chat_id` skip works rather than the dispatcher
    trying to send to "".
    """
    async with with_connection() as conn:
        if conn is None:
            return False
        try:
            if telegram_chat_id is None:
                await conn.execute(
                    "UPDATE user_profiles SET alert_email = $1, min_alert_score = $2, "
                    "updated_at = now() WHERE id = $3",
                    alert_email, min_alert_score, user_id,
                )
            else:
                await conn.execute(
                    "UPDATE user_profiles SET alert_email = $1, min_alert_score = $2, "
                    "telegram_chat_id = $3, updated_at = now() WHERE id = $4",
                    alert_email, min_alert_score, telegram_chat_id.strip() or None, user_id,
                )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] user_profiles not found — run schema.sql.")
            return False
    return True


async def delete_own_account(user_id: str) -> bool:
    """GDPR erasure of everything this app owns for one person.

    A single DELETE is now sufficient: saved_deals and alert_dispatch_log
    both carry `REFERENCES user_profiles(id) ON DELETE CASCADE`, and
    deal_stage_history cascades from saved_deals, so the database does the
    cleanup rather than a hand-maintained list of statements that drifts
    every time a table is added.

    Does NOT remove the Supabase Auth identity itself — see
    security.delete_supabase_auth_identity for that half. Note the reverse
    direction is also wired: user_profiles.id references auth.users with
    ON DELETE CASCADE, so deleting the auth user removes all of this too.
    """
    async with with_connection() as conn:
        if conn is None:
            return False
        try:
            result = await conn.execute("DELETE FROM user_profiles WHERE id = $1", user_id)
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("[DB] user_profiles not found — run schema.sql.")
            return False
    # asyncpg returns the command tag, e.g. "DELETE 1" / "DELETE 0".
    return result.rsplit(" ", 1)[-1] != "0"
