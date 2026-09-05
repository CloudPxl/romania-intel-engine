import os
import csv
import io
import asyncio
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
from typing import Any, Dict, List, Literal, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db
import document_extractions
import procurement_notices
from workers import document_tasks
from matching_engine import RelevanceEngine
from workflow_engine import ConcurrentWorkflowEngine
from billing import StripeBillingEngine
from scrapers.orchestrator import OpportunityOrchestrator, TICK_DEADLINE_SECONDS
from cache_engine import global_cache, newsletter_store
from notifier import LeadAlertDispatcher
from security import (
    SecurityGuard, require_auth,
    enforce_onboarding_rate_limit, delete_supabase_auth_identity,
    # Imported by reference for the /api/v1/system/status diagnostic below.
    # security.py only ever mutates this dict in place, never rebinds it,
    # so the reference stays live.
    RATE_LIMIT_STORE, RATE_LIMIT_REQUESTS,
)

from addons.caiet_analyzer import CaietDeSarciniAnalyzer, TextExtractionError
from addons.win_probability import WinProbabilityEngine
from addons.competitor_tracker import CompetitorTrackerEngine
from ai_copilot import ProcurementAICopilot
from routers import eligibility, drafting, analysis, legal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RO-INTEL-API")

scheduler = AsyncIOScheduler()
copilot_engine = ProcurementAICopilot()
orchestrator = OpportunityOrchestrator()

TICK_SECRET = os.getenv("TICK_SECRET", "")

# How long without a completed tick before ingestion counts as stale.
#
# The heartbeat asks GitHub Actions for a tick every 5 minutes, but
# scheduled workflow delivery there is explicitly best-effort: GitHub
# delays and drops cron runs under load, and hour-long gaps are normal on
# a */5 schedule. A 20-minute threshold therefore flagged healthy systems
# as broken purely because the scheduler was late, which is the fastest
# way to teach someone to ignore the alert. This is set to catch genuine
# stoppages (the kind that went unnoticed for four days) rather than
# ordinary scheduler jitter.
STALENESS_THRESHOLD_MINUTES = float(os.getenv("STALENESS_THRESHOLD_MINUTES", "180"))

# The feed shows the whole market ranked, but three consumers must not
# receive all of it: the 72h briefing, the copilot's context window and
# the CSV export would each turn from "my qualified leads" into "the
# entire database, sorted". On the relevance scale in db.RELEVANCE_WEIGHTS
# this clears anything with no evidence behind it — a county hit alone
# (+20) passes, an unmatched row (score = its 0-10 opportunity_score) does
# not.
BRIEFING_RELEVANCE_FLOOR = float(os.getenv("BRIEFING_RELEVANCE_FLOOR", "15"))

async def background_scraping_job():
    """The in-process 6-hourly ingestion run (plus one at startup).

    Goes through the same locked tick path as /api/v1/system/tick rather
    than orchestrator.run_pipeline(), which it used to call. run_pipeline
    differs in four ways that all turned out to matter here:

      - it never calls db.finish_tick(), so this job could do a full
        ingestion run and /api/v1/system/status would still report
        is_stale — the health signal simply did not see it;
      - it ignores each scraper's own poll_interval_minutes, so every
        6-hour cycle (and every restart) re-scraped all ~20 live sources
        whether or not they were due;
      - it has no soft deadline, unlike run_tick's TICK_DEADLINE_SECONDS;
      - it is not covered by _tick_lock, so it could run concurrently with
        a heartbeat-triggered tick, both competing for the same
        rate-limited sources and the same connection pool — the exact
        pile-up _tick_lock was introduced to prevent, reached by a
        different door.

    run_tick also alerts per user (dispatch_lead_alert_to_user, deduped
    via db.has_alert_been_dispatched) instead of the legacy
    dispatch_high_priority_alert this used to call.
    """
    if _tick_lock.locked():
        # A heartbeat tick is already running; a second concurrent pass
        # would just contend for the same sources. Same no-op the
        # /api/v1/system/tick route applies.
        logger.info("[24/7 DAEMON] Tick already in progress — skipping this cycle.")
        return

    logger.info("[24/7 DAEMON] Ingesting and qualifying pre-SEAP signals...")
    await _run_tick_locked()

    # Refresh the degraded-mode file snapshot from Postgres (the
    # authoritative store) rather than from one run's in-memory leads, so
    # it reflects everything ingested, not just what this tick touched.
    try:
        feed = await _load_feed()
        leads = feed.get("leads", [])
        if leads:
            newsletter_store.save(leads)
        global_cache.invalidate()
        logger.info(f"[24/7 DAEMON] Pipeline synchronized ({len(leads)} leads cached).")
    except Exception as e:
        logger.error(f"[24/7 DAEMON] Post-tick cache refresh failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(background_scraping_job, "interval", hours=6)
    scheduler.start()
    document_tasks.start_workers()
    asyncio.create_task(background_scraping_job())
    logger.info("[SYSTEM] RO-INTEL Enterprise API active.")
    yield
    scheduler.shutdown()

app = FastAPI(title="RO-INTEL Enterprise Procurement Engine", version="2.4.1", lifespan=lifespan)

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://ro-intel.xyz",
    "https://www.ro-intel.xyz",
    "https://romania-intel-frontend.vercel.app",
]
ALLOWED_ORIGIN_REGEX = r"https://.*\.vercel\.app"

app.include_router(eligibility.router)
app.include_router(drafting.router)
app.include_router(analysis.router)
app.include_router(analysis.me_router)
app.include_router(legal.router)


def _cors_headers(request: Request) -> Dict[str, str]:
    """Access-Control headers for a response built *outside* CORSMiddleware.

    Only ServerErrorMiddleware's path needs this (see
    unhandled_exception_handler) — everything else is produced inside the
    middleware chain and gets these headers added for it.
    """
    origin = request.headers.get("origin")
    if not origin:
        return {}
    if origin not in ALLOWED_ORIGINS and not re.fullmatch(ALLOWED_ORIGIN_REGEX, origin):
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort handler for an exception that escaped every middleware.

    Registering a handler for `Exception` does NOT place it inside the
    normal chain the way a per-status handler would: Starlette pulls it
    out in build_middleware_stack() and hands it to ServerErrorMiddleware,
    which is unconditionally the OUTERMOST layer — outside CORSMiddleware.
    So this response has to carry its own CORS headers or the browser
    silently discards it (verified empirically: without them, a real 500
    reaches JS as a bare "Failed to fetch", indistinguishable from the
    server being down — which is exactly how a routine backend bug got
    misdiagnosed as an outage). catch_exceptions_middleware below handles
    the common case from *inside* CORS; this covers what it can't reach.
    """
    logger.error(f"[UNHANDLED] {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "A apărut o eroare neașteptată pe server. Reîncercați sau contactați suportul dacă persistă."},
        headers=_cors_headers(request),
    )


# --- Middleware ------------------------------------------------------------
#
# ORDER IS LOAD-BEARING and reads bottom-up: add_middleware() inserts at
# index 0, so the LAST one registered is the OUTERMOST layer. CORSMiddleware
# must therefore be registered LAST, so that every response produced by the
# layers below it — including a short-circuited 429 and a caught 500 — passes
# back out through it and picks up Access-Control-Allow-Origin.
#
# This was the actual cause of a total login outage: rate_limit_middleware
# was registered after CORSMiddleware, which put it OUTSIDE CORS, so its 429
# went to the browser with no CORS headers. fetch() then rejected with a bare
# network error instead of a readable 429, AuthContext fell through to its
# "serverul nu răspunde" fallback, and every user saw an apparent outage while
# the API was in fact healthy and answering correctly.


@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    """Converts any unhandled route exception into a readable JSON 500.

    Registered FIRST, so it ends up innermost — inside CORSMiddleware —
    which is the whole point: a response returned from here still flows
    back out through CORS and stays readable to the browser, unlike the
    app-level Exception handler above.
    """
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(f"[UNHANDLED] {request.method} {request.url.path}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "A apărut o eroare neașteptată pe server. Reîncercați sau contactați suportul dacă persistă."},
        )


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Global, IP-based — safe to enable unconditionally since it requires
    # no client-side change (unlike SecurityGuard.verify_access_token,
    # which needs the frontend to start sending a bearer token before it can
    # be enforced on any route without breaking it). Exempted from itself:
    # the GitHub Actions heartbeat and health checks should never be able to
    # lock themselves out.
    if request.url.path not in ("/health", "/api/v1/system/status"):
        try:
            SecurityGuard.enforce_rate_limit(request)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
        except Exception as e:
            # The limiter is infrastructure, not the request's purpose —
            # a bug in it must never take down the API it protects.
            logger.error(f"[RateLimit] Limiter failed open on {request.url.path}: {e}", exc_info=True)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AuthSyncRequest(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None

# The five domains the frontend's CATEGORIES constant offers — kept as a
# plain set here rather than imported, since the frontend list is the
# presentation layer and this is just a validity check.
VALID_DOMAINS = {"infrastructura", "sanatate", "energie", "aparare", "digitalizare"}

class OnboardingRequest(BaseModel):
    display_name: Optional[str] = None
    domain: str
    target_counties: List[str] = []
    min_value_ron: float = 0.0
    keywords: List[str] = []
    exclude_keywords: List[str] = []
    # The full customization surface — matching criteria AND how the user
    # gets notified — is set in one sitting now, rather than requiring a
    # second visit to the criteria editor just to turn on alerts. Same
    # defaults as AlertSettingsRequest below; validated by the same shared
    # helper (_validate_alert_fields) so the two routes can't drift.
    # PUT /api/v1/me/profile also accepts this model but ignores both —
    # editing alert settings after onboarding still goes through the
    # dedicated PUT /api/v1/me/alert-settings route.
    min_alert_score: float = 7.5
    telegram_chat_id: Optional[str] = None
    # Only meaningful on the initial POST /api/v1/me/onboarding (see the
    # check there) — an existing user re-editing their criteria via
    # PUT /api/v1/me/profile isn't asked to re-accept anything, so this
    # field is simply ignored on that route rather than duplicated onto a
    # second request model.
    consent_accepted: bool = False

# Self-serve callers submit these fields directly — there is no admin
# reviewing the payload before it's written. None of these caps constrain
# real usage; they exist so one garbage or malicious payload can't blow
# up matching_terms()'s regex scan — run once per *ingested signal*, for
# every onboarded profile (orchestrator.py: run_tick) — or write an
# unreasonably large row. target_counties and
# keywords are deliberately NOT validated against a fixed vocabulary
# (e.g. a real județ list): counties_match()/matching_terms() already
# degrade a typo'd or unrecognised value gracefully rather than failing —
# a bad county just never earns the +1.6 geography bonus (matching_engine.py),
# it does not zero out the match. A bad *keyword* is a harsher case
# (keyword evidence is a mandatory gate for alerting — see
# matching_engine.RelevanceEngine.evaluate), but validating "real Romanian procurement vocabulary" isn't
# something a fixed list can do reliably, and that risk is best addressed
# in the signup UI (out of scope here — frontend), not by rejecting
# free-text server-side.
MAX_ONBOARDING_LIST_ITEMS = 60
MAX_ONBOARDING_COUNTIES = 42  # 41 județe + București
MAX_ONBOARDING_STRING_LENGTH = 80
MAX_DISPLAY_NAME_LENGTH = 120
MAX_MIN_VALUE_RON = 1_000_000_000_000.0  # 1 trilion RON — past this it's not a real budget floor


def _validate_onboarding_payload(payload: "OnboardingRequest") -> None:
    """Shared sanity checks for both POST /api/v1/me/onboarding and
    PUT /api/v1/me/profile. See the caps above for why each one exists."""
    def _check_list(values: List[str], max_items: int, field_label: str) -> None:
        if len(values) > max_items:
            raise HTTPException(
                status_code=400,
                detail=f"Prea multe valori la {field_label} (maxim {max_items}).",
            )
        for v in values:
            if len(v) > MAX_ONBOARDING_STRING_LENGTH:
                raise HTTPException(
                    status_code=400,
                    detail=f"O valoare la {field_label} este prea lungă (maxim {MAX_ONBOARDING_STRING_LENGTH} caractere).",
                )

    _check_list(payload.keywords, MAX_ONBOARDING_LIST_ITEMS, "cuvinte-cheie")
    _check_list(payload.exclude_keywords, MAX_ONBOARDING_LIST_ITEMS, "cuvinte-cheie de excludere")
    _check_list(payload.target_counties, MAX_ONBOARDING_COUNTIES, "județe")
    if payload.display_name and len(payload.display_name) > MAX_DISPLAY_NAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Numele este prea lung (maxim {MAX_DISPLAY_NAME_LENGTH} caractere).",
        )
    if payload.min_value_ron < 0 or payload.min_value_ron > MAX_MIN_VALUE_RON:
        raise HTTPException(status_code=400, detail="Valoarea minimă a bugetului nu este validă.")

def _validated_domain(payload: "OnboardingRequest") -> str:
    """Shared by onboarding and the later profile edit."""
    domain = payload.domain.strip().lower()
    if domain not in VALID_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail=f"Domeniu invalid. Alegeți dintre: {', '.join(sorted(VALID_DOMAINS))}.",
        )
    if not payload.keywords:
        raise HTTPException(
            status_code=400,
            detail="Adăugați cel puțin un cuvânt-cheie, altfel nu veți primi nicio oportunitate relevantă.",
        )
    return domain


def _validate_alert_fields(min_alert_score: float, telegram_chat_id: Optional[str]) -> Optional[str]:
    """Shared by PUT /api/v1/me/alert-settings and onboarding — both accept
    the same two fields and must reject the same bad input the same way,
    rather than two hand-copied checks drifting apart.

    Returns the normalized (stripped) chat id.
    """
    if min_alert_score < 0 or min_alert_score > 10:
        raise HTTPException(status_code=400, detail="Pragul de alertă trebuie să fie între 0 și 10.")
    chat_id = telegram_chat_id
    if chat_id is not None:
        chat_id = chat_id.strip()
        # Telegram chat ids are numeric (negative for groups/channels). A
        # @username is the single most likely thing to be pasted here and
        # is NOT accepted by the Bot API's sendMessage chat_id, so reject
        # it with an explanation rather than storing a value that would
        # silently fail on every future alert.
        if chat_id and not re.fullmatch(r"-?\d{1,20}", chat_id):
            raise HTTPException(
                status_code=400,
                detail="ID-ul de chat Telegram trebuie să fie numeric (ex: 123456789), nu un @nume de utilizator.",
            )
    return chat_id


class AlertSettingsRequest(BaseModel):
    alert_email: EmailStr
    min_alert_score: float = 7.5
    # Omitted entirely -> leave whatever is stored untouched. Empty string
    # -> clear it. A Telegram chat id is a numeric string (negative for
    # groups), obtained from the bot; it is not a @username.
    telegram_chat_id: Optional[str] = None

class ProformaRequest(BaseModel):
    plan_id: str
    company_name: str
    cui_fiscal: str
    billing_email: EmailStr
    billing_address: Optional[str] = "Romania"

class CopilotTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class CopilotQueryRequest(BaseModel):
    query: str
    # Prior turns, oldest first. Bounded here as well as in ai_copilot's
    # character budget: the transcript is client-supplied, so an unbounded
    # list would let one caller push arbitrarily many turns into every
    # provider call. 12 turns is ~6 exchanges, more than the model is
    # given (it takes the last 8) and far more than a question needs.
    history: List[CopilotTurn] = Field(default_factory=list, max_length=12)

class PipelineAddRequest(BaseModel):
    lead_data: dict

class PipelineUpdateRequest(BaseModel):
    new_stage: str
    notes: Optional[str] = None
    proposed_price: Optional[float] = None

class EmailAlertRequest(BaseModel):
    lead_data: dict
    recipient_email: EmailStr

class CompetitorAnalysisRequest(BaseModel):
    category: str
    county: str
    budget_ron: float

class CaietAnalysisRequest(BaseModel):
    project_title: str
    # specification_text stays the primary field so every existing caller
    # (the frontend's synchronous caiet scanner) keeps working unchanged.
    # doc_id/notice_id are additive: when specification_text is omitted, the
    # route instead pulls already-extracted text out of document_extractions
    # (workers/document_tasks.py's async ingestion result) via
    # CaietDeSarciniAnalyzer.load_extracted_text().
    specification_text: Optional[str] = None
    doc_id: Optional[str] = None
    notice_id: Optional[str] = None

class WinProbabilityRequest(BaseModel):
    estimated_budget_ron: float
    proposed_price_ron: float
    has_local_partnership: Optional[bool] = False
    lead_time_days: Optional[int] = 30

@app.get("/")
def root_index():
    # Reads the single source of truth rather than a second hardcoded copy
    # that silently drifts — this string is how a deploy gets verified.
    return {"engine": "RO-INTEL Enterprise Procurement Engine", "status": "online", "version": app.version}

@app.get("/health")
def health_check():
    return {"status": "healthy", "cache": "online"}

_tick_lock = asyncio.Lock()


async def _run_tick_locked() -> None:
    async with _tick_lock:
        try:
            # run_tick enforces its own soft deadline (TICK_DEADLINE_SECONDS)
            # and records the tick before returning. This outer timeout is
            # only a backstop for a hang below that layer, so it must stay
            # comfortably above the soft deadline — if it fired first it
            # would cancel the tick mid-write and leave the run unrecorded,
            # which is the failure mode the soft deadline exists to prevent.
            result = await asyncio.wait_for(orchestrator.run_tick(), timeout=TICK_DEADLINE_SECONDS + 60)
            logger.info(f"[Tick] Background run complete: {result}")
        except Exception as e:
            logger.error(f"[Tick] Background run failed: {e}")


@app.post("/api/v1/system/tick")
async def system_tick(x_tick_secret: Optional[str] = Header(None)):
    """Driven by the free GitHub Actions heartbeat (and any external pinger)
    instead of relying on the Render dyno's own uptime — see
    .github/workflows/heartbeat.yml. Runs only scrapers whose own polling
    interval has elapsed (db.is_source_due) and streams matches/alerts per
    signal (scrapers/orchestrator.py:run_tick).

    Dispatches the tick as a background task and returns immediately
    rather than awaiting it, instead of the previous behavior of blocking
    for the full run (observed live: 100-370+ seconds). The heartbeat's
    curl call has to declare some finite timeout, and a genuinely slow
    tick blowing past it doesn't cancel the run server-side (it keeps
    executing) — it just makes curl retry, which re-POSTs here and starts
    a *second* full tick on top of the first, competing for the same
    rate-limited scrapers and DB connections and making both slower. The
    lock below ensures a retry (or an overlapping cron firing) gets an
    instant "already running" instead of piling on a concurrent run.
    """
    if not TICK_SECRET or x_tick_secret != TICK_SECRET:
        raise HTTPException(status_code=401, detail="unauthorized")

    if _tick_lock.locked():
        return {"status": "already_running", "detail": "A tick is already in progress; this request was a no-op."}

    asyncio.create_task(_run_tick_locked())
    return {"status": "started", "detail": "Tick dispatched in the background."}

# POST /api/v1/admin/reload-tenants used to live here. It existed only to
# prime an in-process config cache after an admin provisioned a client by
# hand; the tick now reads profiles straight from Postgres each run, so a
# new signup is live the moment it commits and there is nothing to reload.


@app.get("/api/v1/system/status")
async def system_status():
    # The heartbeat parses this response, and a 500 here fails the whole
    # workflow run — so a database blip must not take the watchdog down
    # with it. Report the degradation instead of raising.
    try:
        last = await db.get_last_successful_tick()
    except Exception as e:
        logger.error(f"[Status] Could not read last tick: {e}")
        return {
            "last_tick_completed_at": None,
            "minutes_since_last_tick": None,
            "is_stale": True,
            "degraded": True,
            "detail": "database unavailable",
        }
    minutes_since = (datetime.now(timezone.utc) - last).total_seconds() / 60 if last else None

    # `last` is None both when no tick has ever succeeded and when there is
    # no reachable database to have recorded one — and the heartbeat's
    # freshness check fails identically either way, which is how an
    # unconfigured DATABASE_URL presented as "ingestion is stale" with no
    # hint that the real problem was one layer down. Report which it is.
    database = await db.connectivity()
    return {
        "last_tick_completed_at": last.isoformat() if last else None,
        "minutes_since_last_tick": minutes_since,
        "is_stale": minutes_since is None or minutes_since > STALENESS_THRESHOLD_MINUTES,
        "database": database,
        # Distinct callers currently inside the rate-limit window. A count
        # only — never the addresses themselves, since this route is public.
        # Worth surfacing because a value pinned at 1 while several people
        # are using the site is the signature of security.client_ip failing
        # to see past the proxy, which collapses every visitor into one
        # shared budget and locks them all out together once it trips.
        "rate_limit": {
            "tracked_clients": len(RATE_LIMIT_STORE),
            "limit_per_window": RATE_LIMIT_REQUESTS,
        },
        **(
            {"detail": "no tick recorded because persistence is unavailable — check DATABASE_URL"}
            if last is None and not database["reachable"]
            else {}
        ),
    }


@app.get("/api/v1/system/sources")
async def system_sources():
    """Per-source ingestion health — the row-level counterpart to
    /system/status's single fleet-wide is_stale number. source_run_log
    already tracks this (last success, consecutive failures, circuit
    state, zero-result streak); this is the first route that reads it.
    Public and degrade-not-500 for the same reason /system/status is: no
    user data, and a DB blip must not take down whoever is watching it."""
    try:
        rows = await db.get_source_health()
    except Exception as e:
        logger.error(f"[SystemSources] Could not read source_run_log: {e}")
        return {"sources": [], "undelivered_admin_alerts": [], "degraded": True, "detail": "database unavailable"}

    def _health(row: Dict[str, Any]) -> str:
        if row["circuit_state"] == "open":
            return "broken"
        if row["circuit_state"] == "half_open" or row.get("stale_alert_fired_at") is not None:
            return "degraded"
        return "healthy"

    sources = [
        {
            "source_name": r["source_name"],
            "poll_interval_minutes": r["poll_interval_minutes"],
            "last_run_at": r["last_run_at"].isoformat() if r["last_run_at"] else None,
            "last_success_at": r["last_success_at"].isoformat() if r["last_success_at"] else None,
            "last_error": r["last_error"],
            "consecutive_failures": r["consecutive_failures"],
            "circuit_state": r["circuit_state"],
            "records_last_run": r["records_last_run"],
            "consecutive_zero_result_runs": r.get("consecutive_zero_result_runs", 0),
            "health": _health(r),
        }
        for r in rows
    ]

    try:
        alerts = await db.get_recent_system_alerts(limit=20)
    except Exception as e:
        logger.error(f"[SystemSources] Could not read system_alerts: {e}")
        alerts = []

    return {
        "sources": sources,
        "undelivered_admin_alerts": [
            {"created_at": a["created_at"].isoformat(), "message": a["message"]} for a in alerts
        ],
    }

def _row_to_lead(row: Dict[str, Any]) -> Dict[str, Any]:
    """Converts a Postgres row into the JSON-serialisable lead shape the API
    already returns from the file cache.

    Three conversions are mandatory, not cosmetic — without them FastAPI
    raises while encoding and the endpoint 500s:
      * NUMERIC (estimated_value_ron, opportunity_score) arrives as
        decimal.Decimal, which the default JSON encoder cannot serialise.
      * DATE/TIMESTAMP arrive as date/datetime objects.
      * JSONB arrives as a raw string, while every consumer expects a dict.
    """
    lead: Dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, Decimal):
            lead[key] = float(value)
        elif isinstance(value, (datetime, date)):
            lead[key] = value.isoformat()
        else:
            lead[key] = value

    metadata = lead.get("metadata")
    if isinstance(metadata, str):
        try:
            lead["metadata"] = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            lead["metadata"] = {}

    # The DB column is estimated_value_ron; the API contract and the
    # frontend both read financial_value_ron.
    if lead.get("financial_value_ron") is None:
        lead["financial_value_ron"] = lead.get("estimated_value_ron") or 0.0
    return lead


def _apply_feed_filters(leads: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Applies the same market-analysis filters Postgres would apply, in
    Python, against the on-disk fallback cache — so a filtered report
    degrades to "same filters, stale data" when the database is down,
    rather than silently ignoring the filters and returning everything."""
    start_date, end_date = filters.get("start_date"), filters.get("end_date")
    counties = {c.lower() for c in filters.get("counties") or []}
    categories = {c.lower() for c in filters.get("categories") or []}
    min_value_ron, max_value_ron = filters.get("min_value_ron"), filters.get("max_value_ron")

    def _keep(lead: Dict[str, Any]) -> bool:
        if counties and (lead.get("county") or "").lower() not in counties:
            return False
        if categories and (lead.get("category") or "").lower() not in categories:
            return False
        value = lead.get("financial_value_ron") or 0
        if min_value_ron is not None and value < min_value_ron:
            return False
        if max_value_ron is not None and value > max_value_ron:
            return False
        if start_date or end_date:
            raw = lead.get("published_date") or lead.get("last_seen_at")
            lead_date = str(raw)[:10] if raw else None
            if not lead_date:
                return False
            if start_date and lead_date < str(start_date):
                return False
            if end_date and lead_date > str(end_date):
                return False
        return True

    return [l for l in leads if _keep(l)]


async def _load_feed(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Reads the durable copy first, falling back to the on-disk cache.

    newsletter_store writes to Render's ephemeral disk, so it is wiped on
    every deploy and restart — the feed was returning 0 entries after a
    redeploy until the background job had re-scraped everything, even
    though the same opportunities were sitting safely in Postgres the
    whole time. Postgres is the source of truth; the file stays as a
    fallback for when DATABASE_URL is not configured (local runs).

    Keeps NewsletterStore's {updated_at, count, leads} shape either way —
    routers/analysis.py and the frontend both read `leads` off this.

    `filters` (start_date, end_date, counties, categories, min_value_ron,
    max_value_ron — all optional) is pushed down into the Postgres query
    itself via db.get_recent_opportunities, so a customized market-analysis
    request queries only the slice it asked for rather than fetching
    everything and filtering client-side. It is always read fresh here —
    this function carries no in-memory TTL of its own — so market analysis
    genuinely re-queries the database on every call, per the standing
    requirement that strategy/market analysis pull live data every time
    they're engaged.
    """
    filters = dict(filters or {})
    limit = filters.pop("limit", 500)
    db_failed = False
    try:
        rows = await db.get_recent_opportunities(limit=limit, **filters)
        # An unset or unreachable DATABASE_URL is not an exception here —
        # db.py degrades by returning nothing — so without this check a
        # total persistence outage reached the UI as a perfectly calm
        # "0 opportunities", indistinguishable from a quiet market. That
        # is precisely the distinction `degraded` exists to carry.
        if not rows and not await db.is_available():
            db_failed = True
    except Exception as e:
        logger.error(f"[Feed] Postgres read failed, falling back to file cache: {e}")
        rows = []
        db_failed = True

    if not rows and db_failed:
        # Only fall back to the (possibly stale) file cache when Postgres
        # itself was unreachable. Previously this triggered on `not rows`
        # alone, so a perfectly healthy query that legitimately matched
        # zero opportunities (a narrow market-analysis filter, or a fresh
        # database with nothing ingested yet) silently returned whatever
        # was sitting in the on-disk cache instead — violating the "market
        # analysis always reflects the current database" guarantee
        # routers/analysis.py's docstring makes for this exact function.
        fallback = newsletter_store.load()
        if filters:
            fallback["leads"] = _apply_feed_filters(fallback.get("leads", []), filters)[:limit]
            fallback["count"] = len(fallback["leads"])
        # An empty feed caused by an unreachable database is not the same
        # thing as a market with no opportunities, and the caller cannot
        # tell them apart from the payload alone. Say which it is, so the
        # UI can show a warning instead of an empty state that looks like
        # a real (and alarming) result.
        fallback["degraded"] = True
        fallback["detail"] = "database unavailable — showing last cached snapshot"
        fallback.setdefault("source", "file-cache")
        return fallback

    leads = [_row_to_lead(row) for row in rows]

    newest = max((r.get("last_seen_at") for r in rows if r.get("last_seen_at")), default=None)
    return {
        "updated_at": newest.isoformat() if newest is not None and not isinstance(newest, str) else newest,
        "count": len(leads),
        "leads": leads,
        "source": "postgres",
    }


@app.get("/api/v1/newsletter/feed")
async def get_newsletter_feed(_user: dict = Depends(require_auth)):
    # The raw, ungated, unfiltered feed — every qualified lead the system
    # holds. This is the product itself, so it is authenticated rather
    # than public; the anonymous-facing view is the aggregate-only
    # /api/v1/analysis/market-trends.
    return await _load_feed()

@app.post("/api/v1/auth/sync")
async def sync_user_auth(payload: AuthSyncRequest, user: dict = Depends(require_auth)):
    # Identity comes from the verified token, never from the request body.
    # The body used to be the only source, so anyone could POST an
    # arbitrary email and be handed a profile back for it.
    email = user.get("email") or payload.email

    # Creates the bare row on a first-ever sign-in and reads back whatever
    # criteria this person already has. Never sets criteria itself — that
    # is onboarding — so a genuinely new user comes back with
    # onboarded_at None and the frontend shows them the setup form.
    profile = await db.upsert_user_profile_email(user["user_id"], email)

    return {
        "status": "synced",
        "user": {
            "user_id": user.get("user_id"),
            "email": email,
            "full_name": (profile or {}).get("display_name")
            or payload.full_name
            or email.split("@")[0].title(),
            # False both for a brand-new signup and when the database could
            # not be reached. The frontend treats it the same way either
            # way — show onboarding — which is honest: without a profile
            # there is nothing to personalise, and the public market view
            # stays available regardless.
            "onboarded": bool(profile and profile.get("onboarded_at")),
            "avatar_url": payload.avatar_url,
        },
        "profile": profile,
    }

@app.delete("/api/v1/me")
async def delete_own_account_route(user: dict = Depends(require_auth)):
    """Self-serve GDPR erasure — this identity's own account, on their own
    request, no admin involved. Splits into two independent halves and is
    honest when only one succeeds: db.delete_own_account removes the
    profile row, and the database cascades everything keyed to it (saved
    deals, their stage history, the alert dispatch log); a separate call
    then asks Supabase to remove the auth.users row, which is the actual
    login credential and something only Supabase's Admin API can touch.

    Returns 200 either way once the first half succeeds — a missing
    SUPABASE_SERVICE_ROLE_KEY (see security.py) is a real, expected state,
    not a failure the caller should have to handle specially. What changes
    is `auth_identity_deleted` in the response and, either way, an operator
    alert naming exactly which user_id/email to check."""
    deleted = await db.delete_own_account(user["user_id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Nu a fost găsit niciun cont de șters.")

    auth_identity_deleted = await delete_supabase_auth_identity(user["user_id"])

    try:
        note = "" if auth_identity_deleted else (
            "\n⚠️ SUPABASE_SERVICE_ROLE_KEY nu este configurat — identitatea Supabase Auth "
            "NU a fost ștearsă automat. Ștergeți manual din Supabase Dashboard -> Authentication -> Users."
        )
        await LeadAlertDispatcher.dispatch_admin_alert(
            f"🗑️ Cont șters pe RO-INTEL\nEmail: {user.get('email')}{note}"
        )
    except Exception as e:
        logger.error(f"[DeleteAccount] Operator notification failed: {e}")

    return {"status": "deleted", "auth_identity_deleted": auth_identity_deleted}

@app.get("/api/v1/me")
async def get_me(user: dict = Depends(require_auth)):
    """This user's own profile. There is no route for anyone else's — the
    id comes from the verified token, so there is no id to tamper with."""
    profile = await db.get_profile(user["user_id"])
    return {
        "user_id": user["user_id"],
        "email": user.get("email"),
        "onboarded": bool(profile and profile.get("onboarded_at")),
        "profile": profile,
    }


@app.post("/api/v1/me/onboarding")
async def complete_onboarding(
    payload: OnboardingRequest,
    user: dict = Depends(require_auth),
    _rl: None = Depends(enforce_onboarding_rate_limit),
):
    """Turns a signed-in identity into a configured profile.

    Self-serve with zero admin approval means zero admin visibility unless
    something here surfaces it — dispatch_admin_alert below is the only way
    the person running this business finds out a new account exists to
    follow up with (billing.py has no automatic payment collection, only
    manual proforma invoices).
    """
    if not payload.consent_accepted:
        raise HTTPException(
            status_code=400,
            detail="Trebuie să fiți de acord cu Termenii și Politica de Confidențialitate pentru a continua.",
        )
    domain = _validated_domain(payload)
    _validate_onboarding_payload(payload)
    chat_id = _validate_alert_fields(payload.min_alert_score, payload.telegram_chat_id)
    if not db.DATABASE_URL:
        raise HTTPException(
            status_code=503,
            detail="Baza de date nu este configurată — configurarea contului este indisponibilă momentan.",
        )

    email = user.get("email", "")
    display_name = (payload.display_name or "").strip()
    try:
        profile = await db.complete_onboarding(
            user["user_id"], email, display_name or None, domain,
            payload.target_counties, payload.min_value_ron,
            payload.keywords, payload.exclude_keywords,
            payload.min_alert_score, chat_id,
        )
    except db.UserCapacityError as e:
        logger.warning(f"[Onboarding] {e}")
        # Exactly the kind of thing the operator needs to know promptly —
        # the cap constant itself likely needs revisiting, not just this
        # one signup being rejected.
        try:
            await LeadAlertDispatcher.dispatch_admin_alert(
                f"⚠️ Plafonul de conturi a fost atins ({e}). "
                f"Următoarea înregistrare (user_id={user['user_id']}, email={email}) a fost refuzată."
            )
        except Exception as alert_err:
            logger.error(f"[Onboarding] Capacity-alert dispatch failed: {alert_err}")
        raise HTTPException(
            status_code=503,
            detail="Numărul maxim de conturi noi a fost atins momentan. Contactați echipa RO-INTEL pentru acces.",
        )
    if profile is None:
        raise HTTPException(status_code=409, detail="Contul dvs. este deja configurat.")

    # A /me/feed call issued before onboarding finished (e.g. the UI
    # peeking at the market while criteria don't exist yet) can leave a
    # pre-onboarding, unranked snapshot cached under this exact user_id.
    # Without dropping it, the first post-onboarding feed load can still
    # serve that stale entry instead of the newly-ranked one.
    global_cache.invalidate(prefix=f"feed:{user['user_id']}:")

    try:
        await LeadAlertDispatcher.dispatch_admin_alert(
            "🆕 Cont nou pe RO-INTEL\n"
            f"Nume: {display_name or email}\n"
            f"Email: {email}\n"
            f"Domeniu: {domain}"
        )
    except Exception as e:
        # A failed operator notification must never fail the signup itself
        # — the account is already real in the database at this point.
        logger.error(f"[Onboarding] Operator notification failed: {e}")

    return {"status": "provisioned", "profile": profile}


@app.put("/api/v1/me/profile")
async def update_my_profile(payload: OnboardingRequest, user: dict = Depends(require_auth)):
    """Lets an onboarded user change their own watch criteria later.

    Until now this route existed but nothing called it, so there was no way
    to edit your criteria after signup short of deleting the account.
    """
    domain = _validated_domain(payload)
    _validate_onboarding_payload(payload)
    profile = await db.update_profile(user["user_id"], {
        "display_name": (payload.display_name or "").strip() or None,
        "domain": domain,
        "target_counties": payload.target_counties,
        "min_value_ron": payload.min_value_ron,
        "keywords": payload.keywords,
        "exclude_keywords": payload.exclude_keywords,
    })
    if profile is None:
        raise HTTPException(status_code=503, detail="Nu s-a putut salva profilul — baza de date este indisponibilă.")

    # Without this, a changed county/keyword/domain can still rank via the
    # old criteria for up to 60s (get_my_feed's cache TTL) after saving.
    global_cache.invalidate(prefix=f"feed:{user['user_id']}:")

    return {"status": "updated", "profile": profile}


@app.put("/api/v1/me/alert-settings")
async def update_my_alert_settings(payload: AlertSettingsRequest, user: dict = Depends(require_auth)):
    """Where automated alerts actually go and at what score they fire.

    Split from the profile route on purpose: the Settings modal used to
    write a notification email/threshold to localStorage only, which looked
    saved but never touched the columns notifier.py actually reads, so a
    real signup kept getting alerts at their signup address forever no
    matter what they changed here.
    """
    chat_id = _validate_alert_fields(payload.min_alert_score, payload.telegram_chat_id)
    ok = await db.update_alert_settings(
        user["user_id"], payload.alert_email, payload.min_alert_score, chat_id
    )
    if not ok:
        raise HTTPException(status_code=503, detail="Nu s-au putut salva preferințele — baza de date este indisponibilă.")
    return {"status": "updated"}


@app.get("/api/v1/billing/plans")
def list_billing_plans():
    return StripeBillingEngine.get_plans()

@app.post("/api/v1/me/billing/proforma")
def generate_proforma(payload: ProformaRequest, _user: dict = Depends(require_auth)):
    return StripeBillingEngine.generate_proforma_invoice(
        plan_id=payload.plan_id,
        company_name=payload.company_name,
        cui_fiscal=payload.cui_fiscal,
        billing_email=payload.billing_email,
        billing_address=payload.billing_address
    )

@app.get("/api/v1/me/pipeline")
async def get_my_pipeline(user: dict = Depends(require_auth)):
    return {
        "stages": ConcurrentWorkflowEngine.get_stages(),
        "deals": await ConcurrentWorkflowEngine.get_pipeline_for_user(user["user_id"]),
    }

@app.get("/api/v1/me/pipeline/metrics")
async def get_my_pipeline_metrics(user: dict = Depends(require_auth)):
    return await ConcurrentWorkflowEngine.get_pipeline_metrics(user["user_id"])

@app.post("/api/v1/me/pipeline/deals")
async def add_pipeline_deal(payload: PipelineAddRequest, user: dict = Depends(require_auth)):
    return await ConcurrentWorkflowEngine.add_lead_to_pipeline(user["user_id"], payload.lead_data)

@app.patch("/api/v1/me/pipeline/deals/{deal_id}")
async def update_pipeline_deal(
    deal_id: str, payload: PipelineUpdateRequest, user: dict = Depends(require_auth)
):
    """The deal id is in the path, but ownership is still enforced in the
    query (db.update_deal scopes by user_id AND deal_id). Deal ids are
    guessable, so taking the caller's word that the deal is theirs would
    let any authenticated user advance a stranger's pipeline."""
    return await ConcurrentWorkflowEngine.update_deal_stage(
        user_id=user["user_id"],
        deal_id=deal_id,
        new_stage=payload.new_stage,
        notes=payload.notes,
        proposed_price=payload.proposed_price
    )

@app.delete("/api/v1/me/pipeline/deals/{deal_id}")
async def delete_pipeline_deal(deal_id: str, user: dict = Depends(require_auth)):
    """Same ownership rule as the PATCH above: the delete is scoped by
    (user_id, deal_id) in SQL, never by the path parameter alone."""
    result = await ConcurrentWorkflowEngine.remove_deal(user["user_id"], deal_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message", "Dosarul nu a fost găsit."))
    return result

@app.post("/api/v1/notifications/send-email-alert")
async def send_manual_email_alert(payload: EmailAlertRequest, _user: dict = Depends(require_auth)):
    success = await LeadAlertDispatcher.dispatch_email_alert(payload.lead_data, [payload.recipient_email])
    return {"status": "success" if success else "failed", "recipient": payload.recipient_email}

@app.post("/api/v1/addons/competitor-analysis")
async def analyze_competitor_landscape(payload: CompetitorAnalysisRequest, _user: dict = Depends(require_auth)):
    # Feed the engine the opportunities actually ingested, so the sector
    # view is computed from real data. It previously received nothing and
    # answered from a hardcoded benchmark table.
    feed, awards = await asyncio.gather(
        _load_feed(),
        # Real award outcomes for the same county, where any have been
        # ingested. Returns an explicit "not available + why" block rather
        # than raising when there is nothing, so the analysis degrades to
        # the market-only view instead of failing.
        procurement_notices.get_award_statistics(county=payload.county),
        return_exceptions=False,
    )
    return CompetitorTrackerEngine.analyze_landscape(
        payload.category,
        payload.county,
        payload.budget_ron,
        observed_opportunities=feed.get("leads", []),
        award_stats=awards,
    )

@app.post("/api/v1/addons/upload-caiet")
async def upload_and_analyze_caiet(file: UploadFile = File(...), project_title: str = Form(...), _user: dict = Depends(require_auth)):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Fișierul încărcat este gol.")
    try:
        extracted_text = CaietDeSarciniAnalyzer.extract_text_from_file(file_bytes, file.filename or "document")
    except TextExtractionError as e:
        # Deliberately an error rather than an analysis of whatever bytes we
        # could salvage: a scan that never read the document would otherwise
        # come back "no restrictive clauses found", which is worse than no
        # answer for someone deciding whether to bid.
        raise HTTPException(status_code=422, detail=str(e))
    if not extracted_text:
        # Parsed fine, but carries no text layer — a scanned document. That
        # is exactly what the async OCR pipeline exists for, so point at it
        # instead of reporting a generic failure.
        raise HTTPException(
            status_code=422,
            detail=(
                "Documentul nu conține text digital (probabil este scanat). "
                "Încărcați-l prin /api/v1/addons/upload-caiet-async pentru procesare OCR."
            ),
        )
    return CaietDeSarciniAnalyzer.analyze_specification_text(extracted_text, project_title)

@app.post("/api/v1/addons/upload-caiet-async")
async def upload_caiet_async(
    file: UploadFile = File(...),
    notice_id: Optional[str] = Form(None),
    _user: dict = Depends(require_auth),
):
    """Async counterpart to /upload-caiet for heavy scans (100+ page HCL
    municipal budget annexes, CNAIR technical annexes) that risk a request
    timeout if parsed inline. Accepts the upload, records a 'queued'
    document_extractions row, and dispatches the real work (PDF
    classification, then either instant text extraction or full
    render->OCR) via asyncio.create_task — the same fire-and-forget
    dispatch /api/v1/system/tick already uses — so this request thread never
    blocks on it. Poll GET /api/v1/addons/document-extractions/{doc_id} for
    the result, then feed doc_id into /api/v1/addons/analyze-caiet to run
    the actual risk/qualification scan once it's done.
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Fisierul incarcat este gol.")
    doc_id = str(uuid.uuid4())
    filename = file.filename or "document.pdf"
    await document_extractions.create_queued_extraction(doc_id, notice_id, filename)
    asyncio.create_task(document_tasks.enqueue_document(doc_id, notice_id, filename, file_bytes))
    return {"doc_id": doc_id, "status": "queued"}

@app.get("/api/v1/addons/document-extractions/{doc_id}")
async def get_document_extraction_route(doc_id: str, _user: dict = Depends(require_auth)):
    row = await document_extractions.get_extraction(doc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Extragerea documentului nu a fost gasita.")
    return row

@app.get("/api/v1/me/feed")
async def get_my_feed_route(
    category: Optional[str] = None,
    force_refresh: bool = False,
    user: dict = Depends(require_auth),
):
    return await get_my_feed(user["user_id"], category=category, force_refresh=force_refresh)


async def get_my_feed(
    user_id: str,
    category: Optional[str] = None,
    force_refresh: bool = False,
    min_relevance: Optional[float] = None,
):
    """The whole market, ranked so this user's matches come first.

    A SOFT filter, and that is the point. The previous version returned
    ONLY what matched a user's keywords, which meant a narrow profile saw
    an empty dashboard — indistinguishable from a broken product — and
    never saw the adjacent work a bidder would actually have wanted. Now
    nothing is hidden: db.get_ranked_opportunities scores every row and
    orders by it, so matches surface at the top and the general market
    continues below.

    Each lead carries a `match` object explaining its position, so the UI
    can badge the matched ones and say WHY (county, keyword) rather than
    presenting an unexplained order.

    `min_relevance` exists for the callers that must NOT receive the whole
    market — the CSV export and the 72h briefing, which would otherwise go
    from "my qualified leads" to "the entire database, sorted", which is
    noise rather than a product. Left None for the dashboard itself.
    """
    cache_key = f"feed:{user_id}:{category or 'all'}:{min_relevance or 0}"
    if not force_refresh:
        cached_data = global_cache.get(cache_key)
        if cached_data:
            return cached_data

    profile = await db.get_profile(user_id)

    if profile and profile.get("onboarded_at") and db.DATABASE_URL:
        rows = await db.get_ranked_opportunities(profile, limit=500)
        leads = [_ranked_row_to_lead(r) for r in rows]
        source, updated_at, degraded = "postgres", None, False
        if rows:
            newest = max((r.get("last_seen_at") for r in rows if r.get("last_seen_at")), default=None)
            updated_at = newest.isoformat() if hasattr(newest, "isoformat") else newest
        if not rows and not await db.is_available():
            degraded = True
    else:
        # No profile yet (or no database): there is nothing to rank
        # against, so serve the unranked market rather than nothing. A
        # user still in onboarding can look around, and the ranking simply
        # switches on once they have criteria.
        feed = await _load_feed()
        leads = [{**lead, "match": None} for lead in feed.get("leads", [])]
        source = feed.get("source", "file-cache")
        updated_at = feed.get("updated_at")
        degraded = bool(feed.get("degraded"))

    if category and category != "all":
        leads = [l for l in leads if l.get("category") == category]
    if min_relevance is not None:
        leads = [l for l in leads if (l.get("match") or {}).get("score", 0) >= min_relevance]

    payload = {
        "count": len(leads),
        "leads": leads,
        "data_source": source,
        "data_updated_at": updated_at,
    }
    if degraded:
        payload["degraded"] = True
        # Say so explicitly rather than quietly returning an unranked list
        # from a function whose contract is "ranked" — otherwise a database
        # outage looks exactly like the ranking having broken.
        payload["detail"] = "Baza de date nu a răspuns — ordinea după relevanță nu a putut fi calculată."
    global_cache.set(cache_key, payload, ttl_seconds=60)
    return payload


def _ranked_row_to_lead(row: Dict[str, Any]) -> Dict[str, Any]:
    """Splits a ranked SQL row into the lead payload plus its `match`
    explanation. The boolean hits come from the query itself, so nothing is
    re-matched in Python for 500 rows on every request."""
    reasons: List[str] = []
    if row.get("kw_hit"):
        reasons.append("cuvânt-cheie")
    if row.get("county_hit"):
        reasons.append("județ vizat")
    if row.get("domain_hit"):
        reasons.append("domeniu")
    if row.get("value_hit"):
        reasons.append("buget peste prag")
    excluded = bool(row.get("excluded_hit"))

    lead = _row_to_lead({k: v for k, v in row.items() if k not in _RANKING_KEYS})
    lead["match"] = {
        "score": float(row.get("relevance") or 0),
        # Any real evidence badges the card. Deliberately broader than the
        # alerting gate in matching_engine, which demands keyword evidence:
        # being shown a well-placed contract is cheap, being emailed about
        # one is not.
        "is_match": bool(reasons) and not excluded,
        "excluded": excluded,
        "reasons": reasons,
    }
    return lead


# Scoring columns the ranked query adds; stripped before the row is shaped
# into a lead so the payload keeps exactly the fields the frontend types.
_RANKING_KEYS = {
    "kw_hit", "county_hit", "domain_hit", "value_hit", "excluded_hit",
    "is_match", "relevance", "search_blob",
}


@app.get("/api/v1/analytics/market-report-72h")
async def get_72h_report(user: dict = Depends(require_auth)):
    # Ranked feed with a relevance floor, not the whole market: this is a
    # briefing, and summarising 500 loosely-ordered rows would produce
    # confident prose about things the reader never asked to see.
    feed_data = await get_my_feed(user["user_id"], min_relevance=BRIEFING_RELEVANCE_FLOOR)
    leads = feed_data.get("leads", [])
    return ProcurementAICopilot.generate_72h_macro_report(leads)

COPILOT_CHAT_DEADLINE_SECONDS = 35.0

@app.post("/api/v1/copilot/chat")
async def copilot_chat(payload: CopilotQueryRequest, user: dict = Depends(require_auth)):
    # answer_copilot_query's own per-provider httpx timeout (12s) should
    # already bound this to well under a minute even trying all three
    # configured providers in sequence — but a request was observed live
    # hanging for 90s+ with literally zero bytes returned, exactly
    # matching the client's own timeout rather than any bound inside this
    # call chain. That points at something below httpx's own timeout
    # enforcement (a stuck DNS resolution is the classic cause — a hung
    # getaddrinfo() call can bypass an asyncio/httpx timeout entirely).
    # Wrapping the whole handler in a hard deadline means this endpoint
    # can no longer hang indefinitely regardless of which layer is at
    # fault, and degrades to a real answer from the template fallback
    # path instead of leaving the caller with nothing at all.
    try:
        feed_data = await asyncio.wait_for(
            # Same floor as the briefing: the copilot only ever sees the
            # top slice of what it is given (leads[:25]), so handing it the
            # unfiltered market would fill that slice with noise.
            get_my_feed(user["user_id"], min_relevance=BRIEFING_RELEVANCE_FLOOR),
            timeout=10.0,
        )
        leads = feed_data.get("leads", [])
        reply = await asyncio.wait_for(
            copilot_engine.answer_copilot_query(
                payload.query,
                leads,
                history=[t.model_dump() for t in payload.history],
            ),
            timeout=COPILOT_CHAT_DEADLINE_SECONDS,
        )
        return {"reply": reply}
    except asyncio.TimeoutError:
        logger.error(f"[Copilot] Request exceeded {COPILOT_CHAT_DEADLINE_SECONDS}s deadline")
        return {
            "reply": (
                "Îmi pare rău, procesarea a durat prea mult și a fost întreruptă. "
                "Vă rog reîncercați — dacă problema persistă, este posibil ca un furnizor "
                "AI extern să răspundă lent momentan."
            ),
            "degraded": True,
        }

@app.post("/api/v1/addons/analyze-caiet")
async def analyze_caiet_sarcini(payload: CaietAnalysisRequest, _user: dict = Depends(require_auth)):
    text = payload.specification_text
    if not text and (payload.doc_id or payload.notice_id):
        text = await CaietDeSarciniAnalyzer.load_extracted_text(doc_id=payload.doc_id, notice_id=payload.notice_id)
        if text is None:
            raise HTTPException(
                status_code=404,
                detail="Extragerea documentului nu a fost gasita sau nu s-a finalizat inca.",
            )
    if not text:
        raise HTTPException(status_code=400, detail="Trebuie furnizat specification_text sau doc_id/notice_id.")
    return CaietDeSarciniAnalyzer.analyze_specification_text(text, payload.project_title)

@app.post("/api/v1/addons/predict-win-rate")
def predict_win_rate(payload: WinProbabilityRequest, _user: dict = Depends(require_auth)):
    return WinProbabilityEngine.calculate_win_odds(
        payload.estimated_budget_ron, payload.proposed_price_ron, payload.has_local_partnership, payload.lead_time_days
    )

@app.get("/api/v1/me/export/csv")
async def export_my_csv(user: dict = Depends(require_auth)):
    # Floored for the same reason as the briefing: an export of the
    # entire database sorted by relevance is not a useful artifact.
    feed_data = await get_my_feed(user["user_id"], min_relevance=BRIEFING_RELEVANCE_FLOOR)
    leads = feed_data.get("leads", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID Sursa", "Tip Registru", "Categorie", "Judet", "Beneficiar", "Titlu Proiect", "Valoare RON", "Data Publicare", "Termen Reactie", "Scor", "URL"])

    for l in leads:
        writer.writerow([
            l.get("source_id", ""), l.get("source_type", "SICAP"), l.get("category", ""), l.get("county", ""),
            l.get("entity_name", ""), l.get("project_title", ""), l.get("financial_value_ron", 0),
            l.get("published_date", ""), l.get("action_deadline", ""), l.get("opportunity_score", 0), l.get("source_url", "")
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=RO-INTEL-export.csv"}
    )
