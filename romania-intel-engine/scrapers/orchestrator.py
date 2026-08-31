import asyncio
import logging
import os
import time
from typing import List, Dict, Any

import db
from scrapers import circuit_breaker
from scrapers.matrix.elicitatie_scraper import ElicitatieLiveScraper
from scrapers.matrix.direct_acquisition_scraper import DirectAcquisitionScraper, DaAwardNoticeScraper
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
from scrapers.matrix.municipal_matrix import CountyRegistryScraper
from scrapers.ted_scraper import TedRomaniaScraper
from ai_refinery import IntelligenceRefineryEngine
from matching_engine import TENANT_ORGANIZATIONS, TenantMatchingEngine
from notifier import LeadAlertDispatcher

logger = logging.getLogger("OpportunityOrchestrator")

# Soft budget for one ingestion tick. Sits below the caller's hard timeout
# in api.py so the tick can wind down and record itself rather than being
# cancelled mid-flight. Render's free tier runs at 0.1 CPU, where PDF
# parsing and several hundred DB round-trips are genuinely slow, so this
# is treated as a routine condition rather than an error.
TICK_DEADLINE_SECONDS = float(os.getenv("TICK_DEADLINE_SECONDS", "200"))

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
        ]
        if os.getenv("ENABLE_LIVE_ELICITATIE", "false").lower() == "true":
            # Real, live SICAP/e-licitatie data — added alongside (not yet
            # replacing) the fixture Sicap*Scraper classes above during
            # rollout; verified against the production API before shipping.
            self.scrapers.append(ElicitatieLiveScraper())
        if os.getenv("ENABLE_LIVE_DIRECT_ACQUISITION", "false").lower() == "true":
            # Real, live SEAP direct-purchase (DA) + direct-purchase award
            # (CAN) feeds — same live-verified-before-shipping rollout
            # pattern as ElicitatieLiveScraper above. See
            # scrapers/matrix/direct_acquisition_scraper.py's module
            # docstring for exactly which endpoints were confirmed and
            # which SEAP notice types (CN/SC) are still unimplemented.
            self.scrapers.append(DirectAcquisitionScraper())
            self.scrapers.append(DaAwardNoticeScraper())
        if os.getenv("ENABLE_LIVE_COUNTY_REGISTRY", "false").lower() == "true":
            # Polymorphic CMS-adapter coverage of county councils beyond
            # the 3 hand-integrated municipal sources above — see
            # scrapers/matrix/municipal_matrix.py and
            # scrapers/config/county_registries.json for exactly which
            # counties are live and which CMS platform each was confirmed
            # to run. Same live-verified-before-shipping rollout gate as
            # the two flags above.
            self.scrapers.append(CountyRegistryScraper())
        if os.getenv("ENABLE_LIVE_TED", "false").lower() == "true":
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
                await circuit_breaker.record_result(scraper.name, success=True, error=None, records=len(res))
            elif isinstance(res, Exception):
                logger.error(f"[Orchestrator] Scraper failure: {res}")
                await circuit_breaker.record_result(scraper.name, success=False, error=str(res), records=0)

        logger.info(f"⚡ [REFINERY] Refining and scoring {len(raw_signals)} deep bureaucratic signals...")

        refined_leads = []
        for sig in raw_signals:
            refined_lead = IntelligenceRefineryEngine.refine_signal(sig)
            refined_leads.append(refined_lead)
            await db.upsert_opportunity(refined_lead)

        refined_leads.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
        logger.info(f"✅ [SUCCESS] Pipeline complete. {len(refined_leads)} verified dossiers ready.")
        return {"leads": refined_leads, "total_count": len(refined_leads)}

    async def _run_one_scraper(self, scraper):
        try:
            signals = await scraper.fetch_market_consultations()
            return scraper, signals, None
        except Exception as e:
            return scraper, None, e

    async def run_tick(self, deadline_seconds: float = TICK_DEADLINE_SECONDS) -> Dict[str, Any]:
        """Streaming, per-signal pipeline for the free-tier scheduling
        cutover (/api/v1/system/tick): only scrapers whose own
        poll_interval_minutes has elapsed are run, results are processed as
        each scraper finishes (asyncio.as_completed, not gather-then-wait),
        and each genuinely new opportunity is matched + alerted per tenant
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
        due = []
        for scraper in self.scrapers:
            if await circuit_breaker.is_open(scraper.name):
                logger.warning(f"[Tick] Skipping {scraper.name} — circuit open.")
                continue
            if await db.is_source_due(scraper.name, scraper.poll_interval_minutes):
                due.append(scraper)

        # Most time-sensitive sources first. On a cold database every source
        # is due at once, and without ordering a daily 69-page PDF parse
        # could consume the budget ahead of the 10-minute tender feed.
        due.sort(key=lambda s: s.poll_interval_minutes)

        logger.info(f"⚡ [TICK] Running {len(due)}/{len(self.scrapers)} due scraper engines...")

        new_count = 0
        errors = 0
        completed_sources = 0
        truncated = False

        tasks = [asyncio.create_task(self._run_one_scraper(s)) for s in due]
        try:
            for coro in asyncio.as_completed(tasks, timeout=max(1.0, remaining())):
                scraper, signals, error = await coro
                if error is not None:
                    errors += 1
                    logger.error(f"[Tick] Scraper failure for {scraper.name}: {error}")
                    await circuit_breaker.record_result(
                        scraper.name, success=False, error=str(error), records=0,
                        poll_interval_minutes=scraper.poll_interval_minutes,
                    )
                    continue

                await circuit_breaker.record_result(
                    scraper.name, success=True, error=None, records=len(signals),
                    poll_interval_minutes=scraper.poll_interval_minutes,
                )
                completed_sources += 1

                for sig in signals:
                    if remaining() <= 0:
                        # A single source can return hundreds of signals;
                        # persisting them is itself unbounded work, so the
                        # deadline is enforced inside this loop too.
                        truncated = True
                        logger.warning(f"[Tick] Deadline reached while persisting {scraper.name}.")
                        break

                    refined = IntelligenceRefineryEngine.refine_signal(sig)
                    try:
                        is_new = await db.upsert_opportunity(refined)
                    except Exception as e:
                        errors += 1
                        logger.error(f"[Tick] Failed to persist opportunity {refined.get('source_id')}: {e}")
                        continue
                    if not is_new:
                        continue
                    new_count += 1
                    for tenant_id in TENANT_ORGANIZATIONS:
                        match = TenantMatchingEngine.evaluate_opportunity_for_tenant(refined, tenant_id)
                        if match["is_match"]:
                            try:
                                await LeadAlertDispatcher.dispatch_lead_alert_to_tenant(refined, tenant_id, match)
                            except Exception as e:
                                # A failing mail/Telegram transport must not
                                # abort ingestion of the remaining signals.
                                errors += 1
                                logger.error(f"[Tick] Alert dispatch failed for {tenant_id}: {e}")

                if truncated:
                    break
        except asyncio.TimeoutError:
            truncated = True
            logger.warning(
                f"[Tick] Soft deadline of {deadline_seconds:.0f}s reached; "
                f"{completed_sources}/{len(due)} sources processed. Remainder stays due."
            )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        await db.finish_tick(tick_id, completed_sources, new_count, errors)
        logger.info(
            f"✅ [TICK] Complete. sources_run={completed_sources}/{len(due)} "
            f"new_opportunities={new_count} errors={errors} truncated={truncated}"
        )
        return {
            "sources_run": completed_sources,
            "sources_due": len(due),
            "new_opportunities": new_count,
            "errors": errors,
            "truncated": truncated,
            "duration_seconds": round(time.monotonic() - started, 1),
        }
