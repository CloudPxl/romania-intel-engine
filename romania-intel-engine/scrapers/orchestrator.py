import asyncio
import logging
from typing import List, Dict, Any

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

    async def run_pipeline(self) -> Dict[str, Any]:
        logger.info(f"⚡ [ORCHESTRATOR] Concurrently querying all {len(self.scrapers)} specialized scraper engines...")
        
        # Run all 25 scrapers concurrently
        tasks = [scraper.fetch_market_consultations() for scraper in self.scrapers]
        results_nested = await asyncio.gather(*tasks, return_exceptions=True)

        raw_signals = []
        for res in results_nested:
            if isinstance(res, list):
                raw_signals.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"[Orchestrator] Scraper failure: {res}")

        logger.info(f"⚡ [REFINERY] Refining and scoring {len(raw_signals)} deep bureaucratic signals...")
        
        refined_leads = []
        for sig in raw_signals:
            refined_lead = IntelligenceRefineryEngine.refine_signal(sig)
            refined_leads.append(refined_lead)

        refined_leads.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
        logger.info(f"✅ [SUCCESS] Pipeline complete. {len(refined_leads)} verified dossiers ready.")
        return {"leads": refined_leads, "total_count": len(refined_leads)}
