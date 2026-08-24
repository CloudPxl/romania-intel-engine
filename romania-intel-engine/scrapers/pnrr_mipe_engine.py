import logging
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("PnrrMipeScraper")

class PnrrMipeIngestionEngine(BaseScraper):
    def __init__(self):
        super().__init__(name="PnrrMipeEngine", rate_limit_delay=0.3)

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="MIPE-PNRR-C6-2026",
                source_type="MIPE",
                category="energie",
                county="Cluj",
                locality="Dej",
                entity_name="Ministerul Investițiilor și Proiectelor Europene (MIPE)",
                project_title="Apel MIPE / PNRR C6: Eficiență energetică și cogenerare de înaltă eficiență pentru operatori industriali",
                estimated_value_ron=48000000.0,
                raw_description="Publicare ghid specific consultativ pentru sprijinirea investițiilor în capacități de producție energie electrică și termică în cogenerare.",
                action_deadline="2026-09-30",
                source_url="https://mfe.gov.ro/pnrr-energie-apeluri-2026",
                metadata={"pillar": "Green Transition", "grant_intensity": "65%"}
            ),
            RawInstitutionalSignal(
                source_id="MIPE-DIGI-HOSP-2026",
                source_type="MIPE",
                category="sanatate",
                county="Bucuresti",
                locality="Bucuresti",
                entity_name="Ministerul Sănătății / MIPE PNRR C7",
                project_title="Apel Deschidere PNRR C7: Digitalizarea sistemului integrat de arhivare imagistică PACS la nivel național",
                estimated_value_ron=92000000.0,
                raw_description="Ghidul solicitantului pentru interconectarea rețelelor de radiologie și imagistică medicală între 45 de spitale de urgență.",
                action_deadline="2026-10-15",
                source_url="https://ms.ro/pnrr-digitalizare-spitale",
                metadata={"pillar": "Digital Transformation", "grant_intensity": "100%"}
            )
        ]
