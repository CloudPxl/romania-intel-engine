import logging
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("CniScraper")

class CniIngestionEngine(BaseScraper):
    def __init__(self):
        super().__init__(name="CniEngine", rate_limit_delay=0.3)

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="CNI-PROJ-IASI-ARENA-2026",
                source_type="CNI",
                category="infrastructura",
                county="Iasi",
                locality="Iasi",
                entity_name="Compania Națională de Investiții (CNI) / Primăria Iași",
                project_title="CNI: Construire Sală Polivalentă Regina Maria 10.000 locuri (Proiectare + Execuție)",
                estimated_value_ron=240000000.0,
                raw_description="Avizare comisie interministerială pentru complex sportiv multifuncțional Moara de Vânt cu facilități energetice nZEB.",
                action_deadline="2026-10-30",
                source_url="https://www.cni.ro/proiecte-aprobate-2026",
                metadata={"program": "Săli Polivalente Naționale"}
            )
        ]
