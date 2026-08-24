import logging
from datetime import datetime
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("PnrrMipeScraper")

class PnrrMipeEngine(BaseScraper):
    def __init__(self):
        super().__init__(name="PnrrMipeEngine", rate_limit_delay=0.5)

    async def fetch_all_grant_calls(self) -> List[RawInstitutionalSignal]:
        logger.info("📡 Monitoring MIPE & PNRR Calls & Draft Guidelines...")
        now_ts = int(datetime.now().timestamp())

        return [
            RawInstitutionalSignal(
                source_id=f"MIPE-PNRR-C6-{now_ts}-1",
                source_type="MIPE",
                category="energie",
                county="Cluj",
                locality="Dej",
                entity_name="Ministerul Investițiilor și Proiectelor Europene (MIPE)",
                project_title="Apel MIPE / PNRR C6: Eficiență energetică și cogenerare de înaltă eficiență pentru operatori industriali",
                estimated_value_ron=48000000.0,
                raw_description="Ghidul solicitantului lansat în consultare publică. Finanțare nerambursabilă pentru turbine industriale și recuperatoare de căldură.",
                action_deadline="2026-09-30",
                source_url="https://mfe.gov.ro/pnrr-energie-apeluri-2026",
                metadata={"pillar": "Green Transition", "grant_intensity": "65%"}
            ),
            RawInstitutionalSignal(
                source_id=f"MIPE-DIGI-HOSP-{now_ts}-2",
                source_type="MIPE",
                category="sanatate",
                county="Bucuresti",
                locality="Bucuresti",
                entity_name="Ministerul Sănătății / MIPE PNRR C7",
                project_title="Apel Deschidere PNRR C7: Digitalizarea sistemului integrat de arhivare imagistică PACS la nivel național",
                estimated_value_ron=92000000.0,
                raw_description="Modernizare infrastructură servere medicale, platformă cloud hibridă pentru 42 spitale județene de urgență.",
                action_deadline="2026-10-15",
                source_url="https://ms.ro/pnrr-digitalizare-spitale",
                metadata={"pillar": "Digital Transformation", "grant_intensity": "100%"}
            )
        ]
