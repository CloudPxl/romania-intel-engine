import logging
from datetime import datetime
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("CniScraper")

class CniIngestionEngine(BaseScraper):
    def __init__(self):
        super().__init__(name="CniEngine", rate_limit_delay=0.5)

    async def fetch_cni_projects(self) -> List[RawInstitutionalSignal]:
        logger.info("📡 Monitoring CNI Approved Mega-Projects...")
        now_ts = int(datetime.now().timestamp())

        return [
            RawInstitutionalSignal(
                source_id=f"CNI-PROJ-IASI-ARENA-{now_ts}",
                source_type="CNI",
                category="infrastructura",
                county="Iasi",
                locality="Iasi",
                entity_name="Compania Națională de Investiții (CNI) / Primăria Iași",
                project_title="CNI: Construire Sală Polivalentă Regina Maria 10.000 locuri (Proiectare + Execuție)",
                estimated_value_ron=240000000.0,
                raw_description="Complex sportiv multifuncțional, structură metalică spațială, fundații adânci pe piloți forați și fațadă dublu ventilată.",
                action_deadline="2026-10-30",
                source_url="https://www.cni.ro/proiecte-aprobate-2026",
                metadata={"program": "Săli Polivalente Naționale"}
            )
        ]
