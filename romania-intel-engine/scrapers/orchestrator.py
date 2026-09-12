import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import db
from scrapers import circuit_breaker
from scrapers.matrix.elicitatie_scraper import ElicitatieLiveScraper
from scrapers.matrix.direct_acquisition_scraper import DirectAcquisitionScraper, DaAwardNoticeScraper
from scrapers.matrix.notice_scraper import ContractNoticeScraper, SimplifiedContractNoticeScraper
from scrapers.matrix.infra_scrapers import (
    CniInfraScraper, CnairCfrScraper, UrbanismAcScraper, CountyHclScraper
)
from scrapers.matrix.health_scrapers import (
    MsAchizitiiScraper, ProgramSanatateScraper, CniHealthScraper
)
from scrapers.matrix.energy_scrapers import ApmPermitScraper, ProgramEnergieScraper
from scrapers.matrix.defense_scrapers import BorderPoliceProcurementScraper
from scrapers.matrix.digital_scrapers import AdrNordVestScraper, OradeaAchizitiiScraper
from scrapers.matrix.municipal_scrapers import (
    PmbAchizitiiScraper, TimisoaraHclScraper, ConstantaAchizitiiScraper
)
from scrapers.matrix.municipal_batch1 import (
    BrasovMunicipalScraper, CraiovaMunicipalScraper,
    GalatiMunicipalScraper, PloiestiMunicipalScraper,
)
from scrapers.matrix.municipal_matrix import CountyRegistryScraper
from scrapers.ted_scraper import TedRomaniaScraper
from ai_refinery import IntelligenceRefineryEngine
from matching_engine import RelevanceEngine
import push_notifications
from notifier import LeadAlertDispatcher

logger = logging.getLogger("OpportunityOrchestrator")

# Soft budget for one ingestion tick. Sits below the caller's hard timeout
# in api.py so the tick can wind down and record itself rather than being
# cancelled mid-flight. Render's free tier runs at 0.1 CPU, where PDF
# parsing and several hundred DB round-trips are genuinely slow, so this
# is treated as a routine condition rather than an error.
#
# 200 -> 260: a live production audit found 7 real, working scrapers
# (ElicitatieLive, the four SEAP notice types, CountyRegistryMatrix,
# TedRomania) with ZERO rows in source_run_log despite the app having been
# up and ticking every 5 minutes for over an hour — never even a failed
# attempt logged, which is only possible if their task is cancelled by the
# deadline before as_completed ever yields it (a cancelled, never-yielded
# task never reaches circuit_breaker.record_result). Locally, with a real
# CPU, all 26 scrapers running together finished in 81-111s; on Render's
# documented 0.1 CPU that same concurrent, partly CPU-bound batch (JSON
# parsing hundreds of items, HTML parsing across 35 counties) plausibly
# takes multiple times longer, meaning the slower of the 26 could lose the
# deadline race on literally every tick, forever, while all 26 stayed
# individually correct in isolation. 260s leaves 40s of margin under the
# 300s heartbeat cadence (.github/workflows/heartbeat.yml) so a tick still
# finishes, and the lock in api.py still turns an overlapping heartbeat
# call into a no-op, before the next one fires.
TICK_DEADLINE_SECONDS = float(os.getenv("TICK_DEADLINE_SECONDS", "260"))

# Per-tick execution-weight budget. due.sort() below orders scrapers by
# poll_interval so time-sensitive sources are considered first, but that
# ordering alone does not bound how much CPU-bound work actually runs
# concurrently in one tick — every due scraper's task starts at once via
# asyncio.create_task, so "sorted first" was never the same as "protected
# from contention". A live audit found exactly that: on Render's 0.1 CPU,
# a full batch of ~20+ concurrently-due scrapers made the genuinely heavy
# ones (CountyRegistryMatrix fanning out across 35 counties,
# ElicitatieLive's per-item detail fetches) lose the tick deadline race on
# literally every attempt, with zero trace left anywhere (see the
# TICK_DEADLINE_SECONDS comment above). Raising the deadline bought margin;
# this bounds the actual concurrent load so fewer heavy sources are even
# attempted together in the first place.
#
# Weight per source, not per call: a value that reflects real measured
# cost, not a guess. 1 = light (a single or few-page REST/JSON call,
# under ~15s in live measurement). 3 = moderate (multi-page pagination or
# a bounded PDF/HTML parse). 5 = heavy (a multi-county fan-out or a
# scraper that issues a per-item follow-up request for every result — the
# two concretely responsible for the starvation above). Unlisted sources
# default to 1 in _scraper_weight() below; only sources with real,
# measured cost above that baseline are called out here; a name lookup by
# `scraper.name`, kept as one dict in the module that owns tick admission
# rather than a constructor kwarg threaded through 20+ scraper classes, so
# tuning a weight is a one-line, one-file change.
SCRAPER_EXECUTION_WEIGHT: Dict[str, int] = {
    "CountyRegistryMatrix": 5,   # fans out across up to 35 counties per tick
    "GalatiMunicipal": 3,        # parses a single ~5MB archive document
    "UrbanismAC": 3,             # pdfplumber table extraction (offloaded, still real CPU)
    "CountyHcl": 3,              # same PDF extraction path as UrbanismAC
    # 5 -> 2. Read against the source rather than by analogy: it fetches ONE
    # list page (page_size=20) and one detail GET per item — ~21 bounded
    # requests, ~20s wall clock, no PDF parsing and no fan-out. It was
    # weighted the same as CountyRegistryMatrix, which does 35 counties x 2
    # adapter calls at a measured 65-100s; the two are not in the same class.
    #
    # Miscalibrating it this way had a much larger effect than one wrong
    # number suggests, because weight interacts with poll interval: at
    # weight 5 on a 10-minute interval, ElicitatieLive alone demanded 720 of
    # the fleet's 1091.8 daily weight-units — 66% of the entire budget for
    # one source — and, sorting first on the shortest interval, took 5 of
    # every 6 available units whenever it was due. That is what actually
    # starved CountyRegistryMatrix and the other weight-3 sources, more than
    # the size of MAX_TICK_WEIGHT did.
    "ElicitatieLive": 2,
}
# Deliberately still 6, after measuring rather than assuming.
#
# Raising this to 8-10 looked like the obvious fix for the heavy daily
# sources appearing to starve, and it is the wrong one. Replaying a full
# simulated day (288 ticks at the 5-minute heartbeat) against a real
# Postgres, with all 26 sources registered and their real intervals, every
# source already reaches ~100% of its scheduled rate at 6 —
# CountyRegistryMatrix 1/1 per day, ElicitatieLive 143/144, the 15-minute
# SEAP feeds 96/96 — with nothing starved. The sources' intervals are
# staggered enough that the budget is rarely the binding constraint.
#
# The reason not to raise it anyway: this cap exists to bound how many
# scrapers race TICK_DEADLINE_SECONDS concurrently on Render's 0.1 CPU, and
# losing that race is the failure that leaves no trace anywhere (see the
# TICK_DEADLINE_SECONDS comment). A higher cap admits more work into that
# race, so raising it without evidence of a throughput shortfall spends
# real safety margin to buy headroom the measurement says is not needed.
#
# What actually protects the heavy sources is _due_with_priority()'s
# ordering below, which was verified against the same simulation: at a
# constrained budget of 3, the previous interval-only ordering starved all
# four weight-3+ daily sources to ZERO runs in a full day, while the
# overdue-ratio ordering still gave each of them their full allowance.
MAX_TICK_WEIGHT = int(os.getenv("MAX_TICK_WEIGHT", "6"))


def _feature_enabled(env_var: str) -> bool:
    """Rollout gates for the five live source families, now defaulting ON.

    They defaulted to "false" while each was being verified against its real
    upstream, and render.yaml sets all five to "true" — but render.yaml's
    `env` block only reaches the running process for a service Render is
    syncing as a Blueprint. This one is not: a live audit of
    /api/v1/system/sources found exactly 19 of 26 sources present, the
    missing 7 being precisely the ones behind these five flags, with no
    source_run_log row at all — not a success, not even an error row, which
    a registered-but-failing source does leave (CountyHcl's
    "name 'extract_table_rows' is not defined" was sitting right there in
    the same response). They had never been constructed, so SEAP contract
    notices, direct acquisitions, market consultations, the 41-county
    registry and TED were all silently absent from production ingestion
    while every dashboard reported the pipeline healthy.

    Defaulting ON makes the deployed behaviour match the documented and
    intended one without depending on how the service was provisioned.
    Setting any of these to "false" still disables it, so the kill switch
    each was added for is intact.
    """
    return os.getenv(env_var, "true").strip().lower() in ("true", "1", "yes", "on")


def _scraper_weight(scraper) -> int:
    return SCRAPER_EXECUTION_WEIGHT.get(scraper.name, 1)


def _overdue_ratio(scraper, last_run: Optional[datetime], now: datetime) -> float:
    """How far past its own schedule this source is, as a multiple of its
    poll interval. 1.0 = exactly due, 2.0 = a full interval late, inf =
    never run at all.

    A ratio, deliberately, not raw elapsed minutes: the two disagree in
    exactly the case that matters. Sorting by raw age would put a 24-hour
    source that ran 20 hours ago ahead of a 15-minute source that ran 20
    minutes ago, even though the first is not due yet and the second is
    late — which would starve the fast sources instead of the slow ones,
    trading one bias for its mirror image. A ratio is scale-free, so
    "late" means the same thing to a 10-minute feed and a daily PDF.
    """
    if last_run is None:
        return float("inf")
    elapsed_minutes = (now - last_run).total_seconds() / 60.0
    return elapsed_minutes / max(1.0, float(scraper.poll_interval_minutes))


def _due_with_priority(scrapers: list, last_runs: Optional[Dict[str, datetime]], now: datetime) -> list:
    """The due subset of `scrapers`, most-overdue-first.

    Replaces a plain `due.sort(key=poll_interval_minutes)`, which was a
    permanent ordering rather than a priority: a 15-minute source sorts
    ahead of a 1440-minute source on every tick forever, so once enough
    short-interval sources existed to fill MAX_TICK_WEIGHT, the heavy daily
    ones could be deferred indefinitely without anything anywhere recording
    that it was happening. Deferral is silent by design (see
    _admit_within_weight_budget), which is precisely what makes unbounded
    deferral dangerous.

    Ordering by overdue-ratio is self-correcting instead: a deferred
    source's ratio keeps climbing every tick it does not run, so it
    overtakes the frequently-scheduled sources on its own, without a
    deferral counter to persist or a starvation timeout to tune. A source
    that has never run scores inf and therefore goes first — which is also
    what gets a newly-enabled scraper its first row promptly instead of
    behind the whole backlog.

    `last_runs` is None when no database is configured, in which case every
    source is treated as due — the same degrade-open behaviour
    db.is_source_due has always had for that case.
    """
    ranked = []
    for scraper in scrapers:
        last_run = None if last_runs is None else last_runs.get(scraper.name)
        ratio = float("inf") if last_runs is None else _overdue_ratio(scraper, last_run, now)
        if ratio < 1.0:
            continue
        ranked.append((ratio, scraper))
    # Most overdue first, shortest interval breaking ties. The tie-break is
    # load-bearing rather than cosmetic: on a cold start every source scores
    # inf, and relying on the sort's stability alone would fall back to the
    # order sources happen to be declared in __init__ — which puts the
    # conditionally-appended SEAP/TED feeds last, exactly the sources whose
    # 15-minute interval means they should lead. Sorted as one composite key
    # (not reverse=True, which would also reverse the tie-break and defeat
    # its purpose).
    ranked.sort(key=lambda pair: (-pair[0], pair[1].poll_interval_minutes))
    return [scraper for _, scraper in ranked]


def _admit_within_weight_budget(due: list, max_weight: int) -> tuple:
    """First-fit greedy admission over an already-priority-sorted `due`
    list: walk it in order, admitting whatever still fits the remaining
    budget and skipping (deferring) whatever does not, rather than
    stopping at the first source that overflows — a later, lighter source
    further down the list can still fit even after a heavy one didn't.

    Always admits at least one source regardless of its own weight: a due
    source heavier than max_weight itself must still run eventually, or a
    budget lower than any single source's weight would defer it forever.
    Deferred sources are not marked as run in any way — they simply stay
    due (db.is_source_due never learns of this tick), so they are picked
    up on a later heartbeat exactly like one that lost the deadline race.

    Returns (admitted, deferred) — both plain lists, order preserved.
    """
    admitted, deferred = [], []
    weight_used = 0
    for scraper in due:
        weight = _scraper_weight(scraper)
        if not admitted or weight_used + weight <= max_weight:
            admitted.append(scraper)
            weight_used += weight
        else:
            deferred.append(scraper)
    return admitted, deferred


# Fleet-wide data-freshness watchdog, distinct from db.get_last_successful_tick
# (which only proves a tick's own bookkeeping round-tripped, not that any
# real data moved — see get_max_last_seen_at's docstring). Checked once per
# tick rather than on its own timer: the heartbeat already ticks every 5
# minutes (.github/workflows/heartbeat.yml), so piggybacking here costs
# nothing extra and needs no separate scheduler entry.
DATA_STALE_AFTER_HOURS = float(os.getenv("DATA_STALE_AFTER_HOURS", "12"))
# In-process latch so the alert fires once per stale episode, not every 5
# minutes for the whole duration of an outage — mirrors
# source_run_log.stale_alert_fired_at's per-source version, but this is a
# single fleet-wide condition with no natural row of its own to store a
# timestamp on, so a module-level flag is the proportionate amount of
# state. A restart clears it, which just means one possible duplicate
# alert right after a deploy — acceptable, since silence is the failure
# mode this exists to prevent, not the reverse.
_data_stale_alert_fired = False

class OpportunityOrchestrator:
    def __init__(self):
        # Every scraper below reads a live source. The matrix is no longer
        # a fixed 5-per-domain grid: the old shape was only achievable with
        # fixtures, and several institutions simply do not publish a
        # machine-readable procurement feed. Domains are covered by the
        # sources that genuinely exist, plus ElicitatieLiveScraper, which
        # spans all five via SICAP market consultations.
        self.scrapers = [
            # 1. Infrastructure
            CniInfraScraper(), CnairCfrScraper(), UrbanismAcScraper(), CountyHclScraper(),
            # 2. Health
            MsAchizitiiScraper(), ProgramSanatateScraper(), CniHealthScraper(),
            # 3. Energy (ANPM currently unreachable — see energy_scrapers.py)
            ProgramEnergieScraper(), ApmPermitScraper(),
            # 4. Defence (thin by nature: most defence procurement is
            # classified or published only through SICAP)
            BorderPoliceProcurementScraper(),
            # 5. Digital / regional funding. OradeaAchizitiiScraper is a
            # general municipal feed and classifies each notice into its
            # real domain rather than assuming this one.
            AdrNordVestScraper(), OradeaAchizitiiScraper(),
            # Direct coverage for the 3 of Romania's 5 largest economic
            # hubs that had no dedicated municipal source (Cluj-Napoca and
            # Iași already did — UrbanismAcScraper and CountyHclScraper
            # above). Each is a general municipal feed classified per
            # notice, same as OradeaAchizitiiScraper.
            PmbAchizitiiScraper(), TimisoaraHclScraper(), ConstantaAchizitiiScraper(),
            # Batch 1 of the regional expansion beyond those five hubs.
            # Each was verified live before being added here and each runs
            # a different architecture — see municipal_batch1.py's module
            # docstring for the per-portal reconnaissance. Unlike the SEAP
            # feeds these are NOT behind a rollout flag: they are plain
            # municipal HTML/REST sources with the same failure profile as
            # the three municipal scrapers directly above them, which are
            # also unflagged, and they inherit the same circuit breaker and
            # per-source poll interval as every other entry in this list.
            BrasovMunicipalScraper(), CraiovaMunicipalScraper(),
            PloiestiMunicipalScraper(), GalatiMunicipalScraper(),
        ]
        if _feature_enabled("ENABLE_LIVE_ELICITATIE"):
            # Real, live SICAP/e-licitatie data — added alongside (not yet
            # replacing) the fixture Sicap*Scraper classes above during
            # rollout; verified against the production API before shipping.
            self.scrapers.append(ElicitatieLiveScraper())
        if _feature_enabled("ENABLE_LIVE_DIRECT_ACQUISITION"):
            # Real, live SEAP direct-purchase (DA) + direct-purchase award
            # (CAN) feeds — same live-verified-before-shipping rollout
            # pattern as ElicitatieLiveScraper above. See
            # scrapers/matrix/direct_acquisition_scraper.py's module
            # docstring for exactly which endpoints were confirmed and
            # which SEAP notice types (CN/SC) are still unimplemented.
            self.scrapers.append(DirectAcquisitionScraper())
            self.scrapers.append(DaAwardNoticeScraper())
        if _feature_enabled("ENABLE_LIVE_CONTRACT_NOTICES"):
            # Real, live SEAP Contract Notice (CN) + Simplified Contract
            # Notice (SC) feeds — the full-tender coverage
            # direct_acquisition_scraper.py's module docstring explicitly
            # left as future work because its list endpoint could not be
            # located at the time. See scrapers/matrix/notice_scraper.py's
            # module docstring for the endpoint (found in a since-changed,
            # more consolidated site bundle), what was verified live, and
            # the one field (award_criterion) still not found. Same
            # live-verified-before-shipping rollout gate as the flags above.
            self.scrapers.append(ContractNoticeScraper())
            self.scrapers.append(SimplifiedContractNoticeScraper())
        if _feature_enabled("ENABLE_LIVE_COUNTY_REGISTRY"):
            # Polymorphic CMS-adapter coverage of county councils beyond
            # the 3 hand-integrated municipal sources above — see
            # scrapers/matrix/municipal_matrix.py and
            # scrapers/config/county_registries.json for exactly which
            # counties are live and which CMS platform each was confirmed
            # to run. Same live-verified-before-shipping rollout gate as
            # the two flags above.
            self.scrapers.append(CountyRegistryScraper())
        if _feature_enabled("ENABLE_LIVE_TED"):
            # Real, live TED/OJEU (EU Official Journal) cross-border
            # infra/defence/health/energy notices naming Romania as buyer
            # country — see scrapers/ted_scraper.py's module docstring for
            # the full live-verification trail (endpoint/query DSL/field
            # names) and the honest gap it documents around SEAP
            # cross-referencing. Same live-verified-before-shipping
            # rollout gate as the flags above.
            self.scrapers.append(TedRomaniaScraper())

    async def run_pipeline(self) -> Dict[str, Any]:
        active_scrapers = []
        for scraper in self.scrapers:
            if await circuit_breaker.is_open(scraper.name):
                logger.warning(f"[Orchestrator] Skipping {scraper.name} — circuit open.")
                continue
            active_scrapers.append(scraper)

        logger.info(f"⚡ [ORCHESTRATOR] Concurrently querying {len(active_scrapers)}/{len(self.scrapers)} specialized scraper engines...")

        tasks = [scraper.fetch_market_consultations() for scraper in active_scrapers]
        results_nested = await asyncio.gather(*tasks, return_exceptions=True)

        raw_signals = []
        for scraper, res in zip(active_scrapers, results_nested):
            if isinstance(res, list):
                raw_signals.extend(res)
                try:
                    await circuit_breaker.record_result(scraper.name, success=True, error=None, records=len(res))
                except Exception as e:
                    logger.error(f"[Orchestrator] circuit_breaker record failed for {scraper.name}: {e}")
            elif isinstance(res, Exception):
                logger.error(f"[Orchestrator] Scraper failure: {res}")
                try:
                    await circuit_breaker.record_result(scraper.name, success=False, error=str(res), records=0)
                except Exception as e:
                    logger.error(f"[Orchestrator] circuit_breaker record failed for {scraper.name}: {e}")

        logger.info(f"⚡ [REFINERY] Refining and scoring {len(raw_signals)} deep bureaucratic signals...")

        refined_leads = []
        for sig in raw_signals:
            refined_lead = IntelligenceRefineryEngine.refine_signal(sig)
            refined_leads.append(refined_lead)
            try:
                await db.upsert_opportunity(refined_lead)
            except Exception as e:
                logger.error(f"[Orchestrator] Failed to persist opportunity {refined_lead.get('source_id')}: {e}")

        refined_leads.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
        logger.info(f"✅ [SUCCESS] Pipeline complete. {len(refined_leads)} verified dossiers ready.")
        return {"leads": refined_leads, "total_count": len(refined_leads)}

    async def _run_one_scraper(self, scraper):
        try:
            signals = await scraper.fetch_market_consultations()
            return scraper, signals, None
        except Exception as e:
            return scraper, None, e

    @staticmethod
    async def _maybe_push(
        refined: Dict[str, Any],
        profile: Dict[str, Any],
        match: Dict[str, Any],
        push_subs_by_user: Dict[str, list],
    ) -> int:
        """Send one Web Push notification if the policy says to. Returns the
        number of devices reached (0 when the policy declines, which is the
        common case and not an error).

        The policy itself lives in push_notifications.decide_push — a pure
        function — so what gets notified is testable without a tick, a
        database or a push service.
        """
        if not push_subs_by_user:
            return 0
        user_id = profile.get("id")
        subs = push_subs_by_user.get(str(user_id) if user_id else "")
        if not subs:
            return 0

        reason = push_notifications.decide_push(refined, profile, match)
        if reason is None:
            return 0

        source_id = refined.get("source_id") or ""
        # Deduped per (user, opportunity) across BOTH rules: a tender that
        # first arrives via the radar and is later re-evaluated as a
        # criteria match must not notify the same person twice.
        if await db.has_push_been_dispatched(user_id, source_id):
            return 0

        delivered = await push_notifications.dispatch_to_user(user_id, subs, refined, reason)
        if delivered:
            # Recorded only on real delivery, so a total push-service outage
            # leaves the notification eligible for the next tick instead of
            # marking it sent. Same contract as the email/Telegram log.
            await db.record_push_dispatch(user_id, source_id, reason)
        return delivered

    async def run_tick(self, deadline_seconds: float = TICK_DEADLINE_SECONDS) -> Dict[str, Any]:
        """Streaming, per-signal pipeline for the free-tier scheduling
        cutover (/api/v1/system/tick): only scrapers whose own
        poll_interval_minutes has elapsed are run, results are processed as
        each scraper finishes (asyncio.as_completed, not gather-then-wait),
        and each genuinely new opportunity is matched + alerted per user
        immediately rather than in a final batch loop.

        The tick enforces its own soft deadline and always records its
        outcome. Previously the only limit was the caller's
        asyncio.wait_for, which hard-cancelled the coroutine mid-flight:
        db.finish_tick() then never ran, so the tick row kept
        completed_at NULL, get_last_successful_tick() never advanced, and
        /system/status reported is_stale forever even though ingestion was
        working. Overrunning now degrades to a partial tick — whatever
        finished is persisted and recorded, and the sources that did not
        get their turn simply stay due for the next tick.
        """
        started = time.monotonic()

        def remaining() -> float:
            return deadline_seconds - (time.monotonic() - started)

        tick_id = await db.start_tick()

        # Declared before the guarded region below so the `finally` can
        # always report *something*, even if the failure happened during
        # setup and none of these ever advanced.
        new_count = 0
        errors = 0
        completed_sources = 0
        truncated = False
        # Persistence is counted separately from `errors` because the two
        # answer different questions. A scraper that fetched fine still
        # records success on its circuit breaker even when every row it
        # produced then failed to save — which is exactly how a total write
        # outage (an UndefinedColumnError on every upsert) ran for ~19 hours
        # with every source logged healthy and /system/status reporting
        # is_stale:false. Ratio, not count, is what distinguishes "one bad
        # row" from "the write path is gone".
        persist_attempts = 0
        persist_failures = 0
        pushed = 0
        push_subs_by_user: Dict[str, list] = {}
        due: List[BaseScraper] = []

        # Everything from here on is guarded so that db.finish_tick ALWAYS
        # runs. It used to be a bare statement after the loop, so any
        # exception raised in between — the unguarded get_onboarded_profiles /
        # is_open / is_source_due calls above, or refine_signal / evaluate
        # inside the loop — skipped it, leaving the tick row with
        # completed_at NULL. /api/v1/system/status then reported is_stale
        # forever while ingestion was in fact running, which is exactly the
        # failure this function's docstring says it fixed. A transient
        # asyncpg error on Render's free tier is enough to trigger it.
        try:

            # Read once per tick and passed down, never held in a module-level
            # cache. The previous design cached this config in matching_engine
            # and had to mutate it in place forever after, because two modules
            # had bound the dict by reference at import time — reassigning it
            # would have left them matching against stale config with no error
            # anywhere. A local has no aliasing hazard, and one SELECT against
            # a run that already takes minutes costs nothing.
            profiles = await db.get_onboarded_profiles()

            # Loaded once per tick and passed down, the same reason profiles
            # are: the alternative is a query per (profile, new signal) pair,
            # which on a tick ingesting several hundred signals is thousands
            # of round trips. Skipped entirely when push is unconfigured, so
            # a deployment without VAPID keys pays nothing for this.
            if push_notifications.is_configured():
                push_subs_by_user = await db.get_push_subscriptions_by_user()

            # One query for every source's last_run_at, rather than the
            # per-scraper db.is_source_due call this replaces — that was 26
            # sequential round trips spent deciding what to run, before any
            # scraping had started.
            last_runs = await db.get_source_last_run_map()
            eligible = []
            for scraper in self.scrapers:
                if await circuit_breaker.is_open(scraper.name):
                    logger.warning(f"[Tick] Skipping {scraper.name} — circuit open.")
                    continue
                eligible.append(scraper)

            # Most OVERDUE first, not shortest-interval first — see
            # _due_with_priority. Sorting by interval was a fixed ordering
            # rather than a priority, so a heavy daily source could sit
            # behind the 15-minute feeds on every tick indefinitely.
            due = _due_with_priority(eligible, last_runs, datetime.now(timezone.utc))

            # Bounds how much of `due` actually executes this tick — see
            # SCRAPER_EXECUTION_WEIGHT's comment above for why sort order
            # alone does not protect against concurrent-load spikes.
            # Deferred sources stay due and are picked up on a later
            # heartbeat; this only changes WHEN they run, never whether.
            all_due_count = len(due)
            due, deferred_by_weight = _admit_within_weight_budget(due, MAX_TICK_WEIGHT)
            if deferred_by_weight:
                logger.info(
                    f"[Tick] Weight budget ({MAX_TICK_WEIGHT}) reached; deferred to a later tick: "
                    f"{', '.join(s.name for s in deferred_by_weight)}."
                )

            logger.info(f"⚡ [TICK] Running {len(due)}/{all_due_count} due scraper engines...")

            # scraper.name isn't recoverable from a bare Task once it's
            # cancelled below, so it has to be captured here — the
            # TimeoutError branch is the whole reason this exists: naming
            # exactly which due sources never got a turn. Before this, the
            # log only said "N/M sources processed", which cannot tell a
            # source that is occasionally slow from one that loses the
            # deadline race on literally every tick, forever, and never
            # produces a single row anywhere.
            task_names = {}
            tasks = []
            for s in due:
                t = asyncio.create_task(self._run_one_scraper(s))
                task_names[t] = s.name
                tasks.append(t)
            try:
                for coro in asyncio.as_completed(tasks, timeout=max(1.0, remaining())):
                    scraper, signals, error = await coro
                    if error is not None:
                        errors += 1
                        logger.error(f"[Tick] Scraper failure for {scraper.name}: {error}")
                        try:
                            await circuit_breaker.record_result(
                                scraper.name, success=False, error=str(error), records=0,
                                poll_interval_minutes=scraper.poll_interval_minutes,
                            )
                        except Exception as e:
                            logger.error(f"[Tick] circuit_breaker record failed for {scraper.name}: {e}")
                        continue

                    try:
                        await circuit_breaker.record_result(
                            scraper.name, success=True, error=None, records=len(signals),
                            poll_interval_minutes=scraper.poll_interval_minutes,
                        )
                    except Exception as e:
                        logger.error(f"[Tick] circuit_breaker record failed for {scraper.name}: {e}")
                    completed_sources += 1

                    if remaining() <= 0:
                        # A single source can return hundreds of signals;
                        # persisting them used to be unbounded serial work
                        # (one round trip per record), which is exactly why
                        # this check existed mid-loop. Batched below, a
                        # whole scraper's signals persist in one round trip,
                        # so the meaningful place left to spend the
                        # remaining budget check is once, before starting
                        # that batch — not per record inside it.
                        truncated = True
                        logger.warning(f"[Tick] Deadline reached before persisting {scraper.name}.")
                        break

                    # Refinement stays per-signal (pure CPU, unchanged); only
                    # the database write is batched. db.upsert_opportunities_batch
                    # replaces what used to be `len(signals)` sequential
                    # `await db.upsert_opportunity(...)` calls — a live audit
                    # found CountyRegistryMatrix alone producing 759 signals
                    # in one tick, meaning 759 serial round trips to Supabase
                    # (50-100ms each from Render) were spent on network
                    # latency rather than actual database work. One batch
                    # call cuts that to a single round trip regardless of
                    # how many signals a source returns.
                    refined_signals = [IntelligenceRefineryEngine.refine_signal(sig) for sig in signals]
                    persist_attempts += len(refined_signals)
                    try:
                        is_new_by_id = await db.upsert_opportunities_batch(refined_signals)
                    except Exception as e:
                        errors += len(refined_signals)
                        persist_failures += len(refined_signals)
                        logger.error(f"[Tick] Batch persist failed for {scraper.name} ({len(refined_signals)} signals): {e}")
                        continue

                    for refined in refined_signals:
                        source_id = refined.get("source_id")
                        if not is_new_by_id.get(source_id):
                            continue
                        new_count += 1
                        for profile in profiles:
                            match = RelevanceEngine.evaluate(refined, profile)
                            if match["is_match"]:
                                try:
                                    await LeadAlertDispatcher.dispatch_lead_alert_to_user(refined, profile, match)
                                except Exception as e:
                                    # A failing mail/Telegram transport must not
                                    # abort ingestion of the remaining signals.
                                    errors += 1
                                    logger.error(f"[Tick] Alert dispatch failed for {profile.get('id')}: {e}")
                            # Push is evaluated for EVERY profile, not only
                            # matches: the radar rule exists precisely to
                            # surface a high-scoring tender that the user's
                            # own filters did not catch, so gating it behind
                            # is_match would delete the feature.
                            try:
                                pushed += await self._maybe_push(
                                    refined, profile, match, push_subs_by_user
                                )
                            except Exception as e:
                                errors += 1
                                logger.error(f"[Tick] Push dispatch failed for {profile.get('id')}: {e}")
            except asyncio.TimeoutError:
                truncated = True
                # A task cancelled here never reaches circuit_breaker's
                # record_result — the only trace it leaves anywhere is this
                # log line. Named explicitly rather than just counted, so a
                # source that consistently loses this race (never appearing
                # even once in source_run_log or /api/v1/system/sources
                # despite the app ticking every 5 minutes for hours) is
                # visible on sight instead of indistinguishable from one
                # that occasionally runs a little long.
                skipped = sorted(task_names[t] for t in tasks if not t.done())
                logger.warning(
                    f"[Tick] Soft deadline of {deadline_seconds:.0f}s reached; "
                    f"{completed_sources}/{len(due)} sources processed. "
                    f"Never got a turn this tick: {', '.join(skipped) or '(none)'}."
                )
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

            # Every attempted write failed. The scrapers are fine — they all
            # recorded success — so nothing else in the system will ever
            # report this: not the circuit breakers, not source_run_log, and
            # not is_stale once the due sources fall out of their poll
            # windows and the following ticks go quietly to errors=0.
            if persist_attempts and persist_failures == persist_attempts:
                message = (
                    f"[RO-INTEL] PERSISTENCE DOWN: all {persist_attempts} writes failed this tick "
                    f"across {completed_sources} healthy source(s). Scraping works; nothing is being "
                    f"saved. Check /api/v1/system/status -> schema_guard and the DB connection."
                )
                logger.error(message)
                try:
                    await LeadAlertDispatcher.dispatch_admin_alert(message)
                except Exception as e:
                    logger.error(f"[Tick] Could not dispatch persistence-failure alert: {e}")

            # A second, independent freshness check: is real data actually
            # advancing, not just "did this tick's own bookkeeping
            # succeed". An empty tick (nothing due) or a tick where every
            # scraper degrades to an honest zero-signal result (a real
            # source change, not an exception — circuit breakers never
            # open for that) both record errors=0 and would otherwise
            # leave is_stale=false indefinitely while opportunities.
            # last_seen_at stops moving entirely.
            global _data_stale_alert_fired
            try:
                newest = await db.get_max_last_seen_at()
            except Exception as e:
                logger.error(f"[Tick] Could not check data freshness: {e}")
                newest = None
            if newest is not None:
                age_hours = (datetime.now(timezone.utc) - newest).total_seconds() / 3600
                if age_hours > DATA_STALE_AFTER_HOURS:
                    if not _data_stale_alert_fired:
                        _data_stale_alert_fired = True
                        stale_message = (
                            f"[RO-INTEL] DATA STALE: no opportunity has advanced last_seen_at in "
                            f"{age_hours:.1f}h (threshold {DATA_STALE_AFTER_HOURS:.0f}h). Ticks are "
                            f"completing but real ingestion may have silently stopped — check "
                            f"/api/v1/system/sources for sources stuck at circuit_state=open or a "
                            f"rising consecutive_zero_result_runs across the board."
                        )
                        logger.error(stale_message)
                        try:
                            await LeadAlertDispatcher.dispatch_admin_alert(stale_message)
                        except Exception as e:
                            logger.error(f"[Tick] Could not dispatch data-staleness alert: {e}")
                elif _data_stale_alert_fired:
                    # Recovered — re-arm so a second, later episode can
                    # alert again instead of staying permanently silenced
                    # by the first one.
                    _data_stale_alert_fired = False
                    logger.info("[Tick] Data freshness recovered; staleness watchdog re-armed.")

            logger.info(
                f"✅ [TICK] Complete. sources_run={completed_sources}/{len(due)} "
                f"(admitted; {len(deferred_by_weight)} deferred by weight budget) "
                f"new_opportunities={new_count} errors={errors} truncated={truncated} "
                f"persisted={persist_attempts - persist_failures}/{persist_attempts}"
            )
            return {
                "sources_run": completed_sources,
                # The true count of sources whose poll interval had elapsed
                # this tick — NOT narrowed by the weight quota below, so
                # sources_due - sources_run still means what it always has
                # ("how many that needed attention did not get it"),
                # whether the cause was a genuine failure, the tick
                # deadline, or a deliberate weight-budget deferral (each
                # independently visible via errors/truncated/
                # sources_deferred_by_weight_budget).
                "sources_due": all_due_count,
                "sources_deferred_by_weight_budget": len(deferred_by_weight),
                "push_notifications_sent": pushed,
                "new_opportunities": new_count,
                "errors": errors,
                "truncated": truncated,
                "persist_attempts": persist_attempts,
                "persist_failures": persist_failures,
                "duration_seconds": round(time.monotonic() - started, 1),
            }
        finally:
            try:
                await db.finish_tick(tick_id, completed_sources, new_count, errors)
            except Exception as e:
                logger.error(f"[Tick] Could not record tick completion: {e}")
