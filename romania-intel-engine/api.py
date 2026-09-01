import os
import csv
import io
import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, EmailStr
from typing import Any, Dict, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db
import document_extractions
from workers import document_tasks
import matching_engine
from matching_engine import TenantMatchingEngine, TENANT_ORGANIZATIONS
from workflow_engine import ConcurrentWorkflowEngine
from billing import StripeBillingEngine
from scrapers.orchestrator import OpportunityOrchestrator, TICK_DEADLINE_SECONDS
from cache_engine import global_cache, newsletter_store
from freemium_shield import FreemiumGatekeeper
from notifier import LeadAlertDispatcher
from security import SecurityGuard, require_auth, require_tenant_membership, enforce_onboarding_rate_limit

from addons.caiet_analyzer import CaietDeSarciniAnalyzer, TextExtractionError
from addons.win_probability import WinProbabilityEngine
from addons.competitor_tracker import CompetitorTrackerEngine
from ai_copilot import ProcurementAICopilot
from routers import eligibility, drafting, analysis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RO-INTEL-API")

scheduler = AsyncIOScheduler()
copilot_engine = ProcurementAICopilot()
orchestrator = OpportunityOrchestrator()

TICK_SECRET = os.getenv("TICK_SECRET", "")

# Fallback profile for a session that hasn't picked one. Must be a real key
# in TENANT_ORGANIZATIONS — matching_engine fails closed on an unknown
# tenant id, so a made-up default silently yields an empty feed.
DEFAULT_TENANT_ID = "t1_infra_transilvania"
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

    run_tick also alerts per tenant (dispatch_lead_alert_to_tenant, deduped
    via db.has_alert_been_dispatched) instead of the legacy non-tenant-aware
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
    await matching_engine.refresh_tenant_organizations()
    asyncio.create_task(background_scraping_job())
    logger.info("[SYSTEM] RO-INTEL Enterprise API active.")
    yield
    scheduler.shutdown()

app = FastAPI(title="RO-INTEL Enterprise Procurement Engine", version="2.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://ro-intel.xyz", "https://www.ro-intel.xyz", "https://romania-intel-frontend.vercel.app"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(eligibility.router)
app.include_router(drafting.router)
app.include_router(analysis.router)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Global, IP-based — safe to enable unconditionally since it requires
    # no client-side change (unlike SecurityGuard.verify_tenant_authorization,
    # which needs the frontend to start sending a bearer token before it can
    # be enforced on any route without breaking it). Exempted from itself:
    # the GitHub Actions heartbeat and health checks should never be able to
    # lock themselves out.
    if request.url.path not in ("/health", "/api/v1/system/status"):
        try:
            SecurityGuard.enforce_rate_limit(request)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
    return await call_next(request)

class AuthSyncRequest(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None

# Same five domains matching_engine.py's TENANT_ORGANIZATIONS entries and
# the frontend's CATEGORIES constant already use — kept as a plain set
# here rather than imported, since the frontend list is the presentation
# layer and this is just a validity check.
VALID_TENANT_DOMAINS = {"infrastructura", "sanatate", "energie", "aparare", "digitalizare"}

class OnboardingRequest(BaseModel):
    display_name: Optional[str] = None
    domain: str
    target_counties: List[str] = []
    min_value_ron: float = 0.0
    keywords: List[str] = []
    exclude_keywords: List[str] = []

# Self-serve callers submit these fields directly — there is no admin
# reviewing the payload before it's written, unlike scripts/provision_tenant.py's
# hand-typed --keywords/--target-counties. None of these caps constrain
# real usage (the largest existing hand-configured product line has under
# 20 keywords, see matching_engine.py); they exist so one garbage or
# malicious payload can't blow up matching_terms()'s per-opportunity,
# per-tenant regex scan — run once per *ingested signal*, for every
# product of every tenant in TENANT_ORGANIZATIONS (orchestrator.py:
# run_tick) — or write an unreasonably large row. target_counties and
# keywords are deliberately NOT validated against a fixed vocabulary
# (e.g. a real județ list): counties_match()/matching_terms() already
# degrade a typo'd or unrecognised value gracefully rather than failing —
# a bad county just never earns the +1.6 geography bonus (matching_engine.py),
# it does not zero out the match. A bad *keyword* is a harsher case
# (keyword evidence is a mandatory gate — TenantMatchingEngine._score_product's
# docstring), but validating "real Romanian procurement vocabulary" isn't
# something a fixed list can do reliably, and that risk is best addressed
# in the signup UI (out of scope here — frontend), not by rejecting
# free-text server-side.
MAX_ONBOARDING_LIST_ITEMS = 60
MAX_ONBOARDING_COUNTIES = 42  # 41 județe + București
MAX_ONBOARDING_STRING_LENGTH = 80
MAX_DISPLAY_NAME_LENGTH = 120
MAX_MIN_VALUE_RON = 1_000_000_000_000.0  # 1 trilion RON — past this it's not a real budget floor


def _validate_onboarding_payload(payload: "OnboardingRequest") -> None:
    """Shared sanity checks for both /api/v1/onboarding/complete and
    PUT /api/v1/tenants/{tenant_id}/profile. See the caps above for why
    each one exists."""
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

class AlertSettingsRequest(BaseModel):
    alert_email: EmailStr
    min_alert_score: float = 7.5

class ProformaRequest(BaseModel):
    plan_id: str
    company_name: str
    cui_fiscal: str
    billing_email: EmailStr
    billing_address: Optional[str] = "Romania"

class CopilotQueryRequest(BaseModel):
    query: str
    tenant_id: Optional[str] = "t1_infra_transilvania"

class PipelineAddRequest(BaseModel):
    lead_data: dict

class PipelineUpdateRequest(BaseModel):
    deal_id: str
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
    return {"engine": "RO-INTEL Enterprise Procurement Engine", "status": "online", "version": "2.4.0"}

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

@app.post("/api/v1/admin/reload-tenants")
async def reload_tenants(x_admin_secret: Optional[str] = Header(None)):
    """Called by scripts/provision_tenant.py right after it writes a new
    tenant/product/user_profiles row, so a freshly provisioned client's
    config is live in the running process without a redeploy — otherwise
    matching_engine.TENANT_ORGANIZATIONS (loaded once at startup, see
    api.py's lifespan) would only pick up the new tenant on the next
    natural restart. Reuses TICK_SECRET rather than adding a second admin
    secret env var — this is the same class of internal-operator-only
    endpoint as /api/v1/system/tick, not a user-facing route.
    """
    if not TICK_SECRET or x_admin_secret != TICK_SECRET:
        raise HTTPException(status_code=401, detail="unauthorized")
    loaded = await matching_engine.refresh_tenant_organizations()
    return {"status": "reloaded" if loaded else "unavailable", "tenant_count": len(TENANT_ORGANIZATIONS)}

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
        **(
            {"detail": "no tick recorded because persistence is unavailable — check DATABASE_URL"}
            if last is None and not database["reachable"]
            else {}
        ),
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

    # Upserts (email only — tenant_id/role are assigned exclusively by
    # scripts/provision_tenant.py, see db.upsert_user_profile_email's
    # docstring) and reads back whatever tenant_id already exists for this
    # user, if any. This used to return a hardcoded DEFAULT_TENANT_ID for
    # every user and write nothing anywhere — a brand-new, unprovisioned
    # user was silently handed tenant #1's data on every login.
    profile = await db.upsert_user_profile_email(user["user_id"], email)
    if profile is not None:
        tenant_id = profile.get("tenant_id")
    elif not db.DATABASE_URL:
        # No database configured at all — local/dev, same fallback
        # condition security.require_tenant_membership uses. There's
        # nothing to check a real membership against, so this preserves
        # today's "just works against the 3 hardcoded tenants" local dev
        # ergonomics rather than locking a developer with no DB out of
        # every tenant-scoped page.
        tenant_id = DEFAULT_TENANT_ID
    else:
        # A database IS configured but this specific call failed (e.g. the
        # migration hasn't been applied yet) — report honestly rather than
        # guessing a tenant.
        tenant_id = None
    role = (profile.get("role") if profile else None) or "Membru"

    return {
        "status": "synced",
        "user": {
            "user_id": user.get("user_id"),
            "email": email,
            "full_name": payload.full_name or email.split("@")[0].title(),
            # None when the user hasn't been provisioned to a tenant yet
            # (no db.upsert_user_profile_email row, or no database
            # configured at all) — the frontend must treat this as "no
            # access yet", never fall back to a default tenant.
            "tenant_id": tenant_id,
            "role": role,
            "avatar_url": payload.avatar_url
        }
    }

@app.post("/api/v1/onboarding/complete")
async def complete_onboarding(
    payload: OnboardingRequest,
    user: dict = Depends(require_auth),
    _rl: None = Depends(enforce_onboarding_rate_limit),
):
    """Self-serve replacement for the admin-only scripts/provision_tenant.py
    flow. This product now sells to individuals rather than companies —
    there is no admin for a new subscriber to email to get unblocked, so a
    signed-in user with no tenant yet must be able to create their own
    right here, choosing their own domain/counties/keywords instead of
    inheriting a company's product line. See db.create_self_provisioned_tenant
    for the actual write.

    Self-serve with zero admin approval also means zero admin visibility
    unless something here surfaces it — dispatch_admin_alert below is the
    only way the person actually running this business finds out a new
    account exists to follow up with (billing.py has no automatic payment
    collection, only manual proforma invoices)."""
    domain = payload.domain.strip().lower()
    if domain not in VALID_TENANT_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail=f"Domeniu invalid. Alegeți dintre: {', '.join(sorted(VALID_TENANT_DOMAINS))}.",
        )
    if not payload.keywords:
        raise HTTPException(
            status_code=400,
            detail="Adăugați cel puțin un cuvânt-cheie, altfel nu veți primi nicio oportunitate relevantă.",
        )
    _validate_onboarding_payload(payload)
    if not db.DATABASE_URL:
        raise HTTPException(status_code=503, detail="Baza de date nu este configurată — configurarea contului este indisponibilă momentan.")

    email = user.get("email", "")
    display_name = (payload.display_name or "").strip()
    try:
        result = await db.create_self_provisioned_tenant(
            user["user_id"], email, display_name, domain,
            payload.target_counties, payload.min_value_ron, payload.keywords, payload.exclude_keywords,
        )
    except db.TenantCapacityError as e:
        logger.warning(f"[Onboarding] {e}")
        # This is exactly the kind of thing the operator needs to know
        # about promptly — the cap constant itself likely needs revisiting,
        # not just this one signup rejecting.
        try:
            await LeadAlertDispatcher.dispatch_admin_alert(
                f"⚠️ Plafonul de conturi auto-provizionate a fost atins ({e}). "
                f"Următoarea înregistrare (user_id={user['user_id']}, email={email}) a fost refuzată."
            )
        except Exception as alert_err:
            logger.error(f"[Onboarding] Capacity-alert dispatch failed: {alert_err}")
        raise HTTPException(
            status_code=503,
            detail="Numărul maxim de conturi noi a fost atins momentan. Contactați echipa RO-INTEL pentru acces.",
        )
    if result is None:
        raise HTTPException(status_code=409, detail="Contul dvs. este deja configurat.")

    # Loaded once at startup (api.py's lifespan); without this refresh a
    # brand-new tenant would 403 on its own feed until the next restart —
    # the exact reason /api/v1/admin/reload-tenants exists for the admin
    # path, needed here too since this route creates tenants the same way.
    #
    # The tenant/product/membership rows above already committed
    # successfully (create_self_provisioned_tenant runs them in one
    # transaction) before this line ever runs — a failure here (e.g. a
    # transient pool error) does not mean provisioning failed, only that
    # this process's in-memory copy is stale until the next natural
    # refresh or a manual POST /api/v1/admin/reload-tenants. Letting the
    # exception propagate would turn a successful signup into a fabricated
    # 500 for a brand-new (possibly paying) user.
    try:
        await matching_engine.refresh_tenant_organizations()
    except Exception as e:
        logger.error(f"[Onboarding] Post-provisioning tenant-cache refresh failed: {e}")

    try:
        await LeadAlertDispatcher.dispatch_admin_alert(
            "🆕 Cont nou auto-provizionat pe RO-INTEL\n"
            f"Nume: {display_name or email}\n"
            f"Email: {email}\n"
            f"Domeniu: {domain}\n"
            f"Tenant: {result['tenant_id']}"
        )
    except Exception as e:
        # A failed operator notification must never fail the signup itself
        # — the account is already real in the database at this point.
        logger.error(f"[Onboarding] Operator notification failed: {e}")

    return {"status": "provisioned", **result}

@app.put("/api/v1/tenants/{tenant_id}/profile")
async def update_tenant_profile(tenant_id: str, payload: OnboardingRequest, _user: dict = Depends(require_tenant_membership)):
    """Lets an already-onboarded individual change their own watch
    criteria later — the self-serve counterpart to re-running
    scripts/provision_tenant.py by hand. See db.update_own_tenant_product."""
    domain = payload.domain.strip().lower()
    if domain not in VALID_TENANT_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail=f"Domeniu invalid. Alegeți dintre: {', '.join(sorted(VALID_TENANT_DOMAINS))}.",
        )
    if not payload.keywords:
        raise HTTPException(
            status_code=400,
            detail="Adăugați cel puțin un cuvânt-cheie, altfel nu veți primi nicio oportunitate relevantă.",
        )
    _validate_onboarding_payload(payload)
    ok = await db.update_own_tenant_product(
        tenant_id, domain, payload.target_counties, payload.min_value_ron,
        payload.keywords, payload.exclude_keywords,
    )
    if not ok:
        raise HTTPException(status_code=503, detail="Nu s-a putut salva profilul — baza de date este indisponibilă.")
    # Same reasoning as complete_onboarding above: the write already
    # succeeded, so a refresh failure here must not surface as if the
    # edit itself failed.
    try:
        await matching_engine.refresh_tenant_organizations()
    except Exception as e:
        logger.error(f"[UpdateTenantProfile] Post-update tenant-cache refresh failed: {e}")
    return {"status": "updated"}

@app.put("/api/v1/tenants/{tenant_id}/alert-settings")
async def update_tenant_alert_settings(
    tenant_id: str, payload: AlertSettingsRequest, _user: dict = Depends(require_tenant_membership)
):
    """Where automated alerts actually go and at what score they fire.

    Split from update_tenant_profile (matching criteria) on purpose: the
    frontend's Settings modal used to write a notification email/threshold
    to localStorage only, which looked saved but never touched the
    tenants.alert_emails/min_alert_score columns notifier.py's
    dispatch_lead_alert_to_tenant actually reads — a real signup kept
    getting alerts at whatever create_self_provisioned_tenant set once at
    onboarding ([their signup email], 7.5), forever, no matter what they
    changed here."""
    if payload.min_alert_score < 0 or payload.min_alert_score > 10:
        raise HTTPException(status_code=400, detail="Pragul de alertă trebuie să fie între 0 și 10.")
    ok = await db.update_tenant_alert_settings(tenant_id, [payload.alert_email], payload.min_alert_score)
    if not ok:
        raise HTTPException(status_code=503, detail="Nu s-au putut salva preferințele — baza de date este indisponibilă.")
    try:
        await matching_engine.refresh_tenant_organizations()
    except Exception as e:
        logger.error(f"[UpdateTenantAlertSettings] Post-update tenant-cache refresh failed: {e}")
    return {"status": "updated"}

@app.get("/api/v1/tenants")
def list_tenant_profiles():
    """The intelligence profiles a desk can be pointed at.

    The frontend models companies as browser-local "desks", but matching
    only works against a real key in TENANT_ORGANIZATIONS — a desk id like
    `desk_main_infra` matches nothing, because evaluate_opportunity_for_tenant
    fails closed on an unknown tenant. Exposing the real ids lets the UI
    bind each desk to one instead of guessing.
    """
    return {
        "tenants": [
            {
                "tenant_id": tenant_id,
                "name": org["name"],
                "primary_domain": org["primary_domain"],
                "products": [
                    {"product_id": p["product_id"], "name": p["name"], "domain": p["domain"]}
                    for p in org.get("products", [])
                ],
            }
            for tenant_id, org in TENANT_ORGANIZATIONS.items()
        ],
        "default_tenant_id": DEFAULT_TENANT_ID,
    }

@app.get("/api/v1/billing/plans")
def list_billing_plans():
    return StripeBillingEngine.get_plans()

@app.post("/api/v1/tenants/{tenant_id}/billing/proforma")
def generate_proforma(tenant_id: str, payload: ProformaRequest, _user: dict = Depends(require_tenant_membership)):
    return StripeBillingEngine.generate_proforma_invoice(
        tenant_id=tenant_id,
        plan_id=payload.plan_id,
        company_name=payload.company_name,
        cui_fiscal=payload.cui_fiscal,
        billing_email=payload.billing_email,
        billing_address=payload.billing_address
    )

@app.get("/api/v1/tenants/{tenant_id}/pipeline")
async def get_tenant_pipeline(tenant_id: str, product_id: Optional[str] = None, _user: dict = Depends(require_tenant_membership)):
    # Previously named `stage` here while being forwarded into
    # get_tenant_pipeline's product_id filter — a request for
    # ?stage=discovery silently filtered on product_id="discovery" instead
    # (always empty) rather than actually filtering by stage. Renamed to
    # match what the parameter actually does; the frontend never sent this
    # param, so nothing depended on the old (wrong) name.
    return {
        "tenant_id": tenant_id,
        "stages": ConcurrentWorkflowEngine.get_stages(),
        "deals": await ConcurrentWorkflowEngine.get_tenant_pipeline(tenant_id, product_id)
    }

@app.get("/api/v1/tenants/{tenant_id}/pipeline/metrics")
async def get_tenant_pipeline_metrics(tenant_id: str, product_id: Optional[str] = None, _user: dict = Depends(require_tenant_membership)):
    return await ConcurrentWorkflowEngine.get_pipeline_metrics(tenant_id, product_id)

@app.post("/api/v1/tenants/{tenant_id}/pipeline/add")
async def add_pipeline_deal(tenant_id: str, payload: PipelineAddRequest, _user: dict = Depends(require_tenant_membership)):
    return await ConcurrentWorkflowEngine.add_lead_to_pipeline(tenant_id, payload.lead_data)

@app.post("/api/v1/tenants/{tenant_id}/pipeline/update")
async def update_pipeline_deal(tenant_id: str, payload: PipelineUpdateRequest, _user: dict = Depends(require_tenant_membership)):
    return await ConcurrentWorkflowEngine.update_deal_stage(
        tenant_id=tenant_id,
        deal_id=payload.deal_id,
        new_stage=payload.new_stage,
        notes=payload.notes,
        proposed_price=payload.proposed_price
    )

@app.post("/api/v1/notifications/send-email-alert")
async def send_manual_email_alert(payload: EmailAlertRequest, _user: dict = Depends(require_auth)):
    success = await LeadAlertDispatcher.dispatch_email_alert(payload.lead_data, [payload.recipient_email])
    return {"status": "success" if success else "failed", "recipient": payload.recipient_email}

@app.post("/api/v1/addons/competitor-analysis")
async def analyze_competitor_landscape(payload: CompetitorAnalysisRequest, _user: dict = Depends(require_auth)):
    # Feed the engine the opportunities actually ingested, so the sector
    # view is computed from real data. It previously received nothing and
    # answered from a hardcoded benchmark table.
    return CompetitorTrackerEngine.analyze_landscape(
        payload.category,
        payload.county,
        payload.budget_ron,
        observed_opportunities=(await _load_feed()).get("leads", []),
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

@app.get("/api/v1/tenants/{tenant_id}/feed")
async def get_tenant_feed_route(
    tenant_id: str,
    product_id: Optional[str] = None,
    category: Optional[str] = None,
    force_refresh: bool = False,
    _user: dict = Depends(require_tenant_membership),
):
    # `is_subscribed` used to be a plain query parameter defaulting to
    # True — so the freemium gate was both trivially bypassable
    # (?is_subscribed=true) and off by default anyway, meaning
    # FreemiumGatekeeper never actually withheld anything. Entitlement is
    # now decided server-side. Until billing.py has real subscription
    # state (deliberately deferred), "authenticated" is the entitlement:
    # that is honest about what the system currently knows, and the knob
    # is no longer something a client can set for itself.
    return await get_tenant_feed(
        tenant_id,
        product_id=product_id,
        category=category,
        force_refresh=force_refresh,
        is_subscribed=True,
    )


async def get_tenant_feed(
    tenant_id: str,
    product_id: Optional[str] = None,
    category: Optional[str] = None,
    force_refresh: bool = False,
    is_subscribed: bool = True
):
    """Matches ingested opportunities against one tenant's product lines.

    This used to call orchestrator.run_pipeline() on every cache miss —
    a full synchronous re-scrape of all 13 live sources (CNI's ~15k-row
    register, multi-page PDF parsing, etc.) inside the HTTP request path,
    on a 90-second cache TTL. On Render's free-tier CPU that reliably took
    well over a minute, which is why /api/v1/copilot/chat (which calls
    this for context) was timing out at 90s with no response at all.
    It also duplicated the ingestion the tick already performs on its own
    schedule, and — unlike run_tick() — ignored each source's
    poll_interval_minutes entirely, so a handful of requests could hammer
    every source far more often than the scrapers were designed for.

    force_refresh now means "recompute matching against the latest
    ingested data," not "trigger a live re-scrape" — the tick already
    keeps that data fresh on its own cadence; a request re-running the
    scrapers themselves was never the right place for that to happen.
    """
    product_key = product_id or "all"
    cache_key = f"feed:{tenant_id}:{product_key}:{category or 'all'}:{is_subscribed}"
    if not force_refresh:
        cached_data = global_cache.get(cache_key)
        if cached_data:
            return cached_data

    feed = await _load_feed()
    raw_leads = feed.get("leads", [])

    matched_leads = []
    for lead in raw_leads:
        if category and category != "all" and lead.get("category") != category:
            continue
        match_info = TenantMatchingEngine.evaluate_opportunity_for_tenant(lead, tenant_id)
        if not match_info["is_match"]:
            continue
        # product_id was accepted and folded into the cache key but never
        # actually applied — every request advertising this filter got an
        # unfiltered result back regardless.
        if product_id and product_id != "all":
            if not any(p["product_id"] == product_id for p in match_info["product_matches"]):
                continue
        lead_copy = dict(lead)
        lead_copy["opportunity_score"] = match_info["tenant_opportunity_score"]
        lead_copy["product_matches"] = match_info["product_matches"]
        matched_leads.append(lead_copy)

    matched_leads.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
    gated_leads = FreemiumGatekeeper.enforce_paywall_tier(matched_leads, has_active_subscription=is_subscribed)

    payload = {
        "tenant_id": tenant_id,
        "count": len(gated_leads),
        "leads": gated_leads,
        "data_source": feed.get("source", "file-cache"),
        "data_updated_at": feed.get("updated_at"),
    }
    if feed.get("degraded"):
        payload["degraded"] = True
    global_cache.set(cache_key, payload, ttl_seconds=60)
    return payload

@app.get("/api/v1/analytics/market-report-72h")
async def get_72h_report(tenant_id: str = DEFAULT_TENANT_ID, user: dict = Depends(require_auth)):
    # tenant_id here is a query param with a default, not a path param, so
    # it can't be checked via Depends(require_tenant_membership) the way
    # the /tenants/{tenant_id}/... routes are (FastAPI would resolve that
    # dependency's own tenant_id as a *required* query param, breaking the
    # default). Calling the same check function directly instead — it's a
    # plain async function underneath Depends(), nothing stops calling it
    # like one. This is the same tenant-scoped /feed data as the path-param
    # route above, so it needs the same check, not a lesser one.
    await require_tenant_membership(tenant_id, user)
    feed_data = await get_tenant_feed(tenant_id)
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
    tenant_id = payload.tenant_id or DEFAULT_TENANT_ID
    # Same reasoning as get_72h_report above: tenant_id lives inside the
    # JSON body here, not a path param, so the check is called directly.
    await require_tenant_membership(tenant_id, user)
    try:
        feed_data = await asyncio.wait_for(
            get_tenant_feed(tenant_id),
            timeout=10.0,
        )
        leads = feed_data.get("leads", [])
        reply = await asyncio.wait_for(
            copilot_engine.answer_copilot_query(payload.query, leads),
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

@app.get("/api/v1/tenants/{tenant_id}/products")
async def get_tenant_products(tenant_id: str, _user: dict = Depends(require_tenant_membership)):
    org = TENANT_ORGANIZATIONS.get(tenant_id)
    if not org:
        return {"tenant_id": tenant_id, "company_name": "SC General Procurement SRL", "products": []}
    return {"tenant_id": tenant_id, "company_name": org["name"], "products": org["products"]}

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

@app.get("/api/v1/tenants/{tenant_id}/export/csv")
async def export_tenant_csv(tenant_id: str, _user: dict = Depends(require_tenant_membership)):
    feed_data = await get_tenant_feed(tenant_id)
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
        headers={"Content-Disposition": f"attachment; filename=RO-INTEL-{tenant_id}.csv"}
    )
