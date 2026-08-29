import asyncio
import logging
import os
from typing import List, Dict, Any

import db
from scrapers import circuit_breaker
from scrapers.matrix.elicitatie_scraper import ElicitatieLiveScraper
from scrapers.matrix.infra_scrapers import (
    SicapInfraScraper, CniInfraScraper, CnairCfrScraper, UrbanismAcScraper, CountyHclScraper
)
from scrapers.matrix.health_scrapers import (
    SicapHealthScraper, MsRegionalHospitalScraper, PnrrHealthC7Scraper, CountyEmergencyHospitalScraper, CniHealthScraper
)
from scrapers.matrix.energy_scrapers import (
    PnrrEnergyC6Scraper, ModernizationFundScraper, ApmPermitScraper, MunicipalTermoScraper, SicapEnergyScraper
)
from scrapers.matrix.defense_scrapers import (
    MapnInfraScraper, SicapDefenseScraper, StsSpecialCommsScraper, MaiLogisticsScraper, CriticalInfraPortAirportScraper
)
from scrapers.matrix.digital_scrapers import (
    SicapDigitalScraper, AdrRegionalDigiScraper, McidGovCloudScraper, TechParksInnovationScraper, SmartTransportUrbanScraper
)
from ai_refinery import IntelligenceRefineryEngine
from matching_engine import TENANT_ORGANIZATIONS, TenantMatchingEngine
from notifier import LeadAlertDispatcher

logger = logging.getLogger("OpportunityOrchestrator")

class OpportunityOrchestrator:
    def __init__(self):
        # 25 Dedicated Scraper Engines (5 per domain x 5 strategic domains)
        self.scrapers = [
            # 1. Infra
            SicapInfraScraper(), CniInfraScraper(), CnairCfrScraper(), UrbanismAcScraper(), CountyHclScraper(),
            # 2. Health
            SicapHealthScraper(), MsRegionalHospitalScraper(), PnrrHealthC7Scraper(), CountyEmergencyHospitalScraper(), CniHealthScraper(),
            # 3. Energy
            PnrrEnergyC6Scraper(), ModernizationFundScraper(), ApmPermitScraper(), MunicipalTermoScraper(), SicapEnergyScraper(),
            # 4. Defense
            MapnInfraScraper(), SicapDefenseScraper(), StsSpecialCommsScraper(), MaiLogisticsScraper(), CriticalInfraPortAirportScraper(),
            # 5. Digital
            SicapDigitalScraper(), AdrRegionalDigiScraper(), McidGovCloudScraper(), TechParksInnovationScraper(), SmartTransportUrbanScraper()
        ]
        if os.getenv("ENABLE_LIVE_ELICITATIE", "false").lower() == "true":
            # Real, live SICAP/e-licitatie data — added alongside (not yet
            # replacing) the fixture Sicap*Scraper classes above during
            # rollout; verified against the production API before shipping.
            self.scrapers.append(ElicitatieLiveScraper())

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

    async def run_tick(self) -> Dict[str, Any]:
        """Streaming, per-signal pipeline for the free-tier scheduling
        cutover (/api/v1/system/tick): unlike run_pipeline() above, only
        scrapers whose own poll_interval_minutes has elapsed are run, results
        are processed as each scraper finishes (asyncio.as_completed, not
        gather-then-wait-for-all), and each genuinely new opportunity is
        matched + alerted per tenant immediately rather than in a final
        batch loop."""
        tick_id = await db.start_tick()
        due = []
        for scraper in self.scrapers:
            if await circuit_breaker.is_open(scraper.name):
                logger.warning(f"[Tick] Skipping {scraper.name} — circuit open.")
                continue
            if await db.is_source_due(scraper.name, scraper.poll_interval_minutes):
                due.append(scraper)

        logger.info(f"⚡ [TICK] Running {len(due)}/{len(self.scrapers)} due scraper engines...")

        new_count = 0
        errors = 0
        for coro in asyncio.as_completed([self._run_one_scraper(s) for s in due]):
            scraper, signals, error = await coro
            if error is not None:
                errors += 1
                logger.error(f"[Tick] Scraper failure for {scraper.name}: {error}")
                await circuit_breaker.record_result(scraper.name, success=False, error=str(error), records=0,
                                                     poll_interval_minutes=scraper.poll_interval_minutes)
                continue

            await circuit_breaker.record_result(scraper.name, success=True, error=None, records=len(signals),
                                                 poll_interval_minutes=scraper.poll_interval_minutes)

            for sig in signals:
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
                        await LeadAlertDispatcher.dispatch_lead_alert_to_tenant(refined, tenant_id, match)

        await db.finish_tick(tick_id, len(due), new_count, errors)
        logger.info(f"✅ [TICK] Complete. sources_run={len(due)} new_opportunities={new_count} errors={errors}")
        return {"sources_run": len(due), "new_opportunities": new_count, "errors": errors}
