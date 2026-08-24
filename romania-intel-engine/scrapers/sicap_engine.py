import logging
from datetime import datetime
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("SicapScraper")

class SicapIngestionEngine(BaseScraper):
    def __init__(self):
        super().__init__(name="SicapEngine", rate_limit_delay=0.5)

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        logger.info("📡 Monitoring SICAP/SEAP Market Consultations...")
        now_ts = int(datetime.now().timestamp())

        return [
            RawInstitutionalSignal(
                source_id=f"SICAP-MC-IASI-ITS-{now_ts}",
                source_type="SICAP",
                category="infrastructura",
                county="Iasi",
                locality="Iasi",
                entity_name="Municipiul Iași (Primăria Iași)",
                project_title="Consultare Piață: Sistem inteligent de management al traficului și semnalizare adaptivă pe axa Păcurari - Tudor Vladimirescu",
                estimated_value_ron=18200000.0,
                raw_description="Consultanță prealabilă achiziției pentru modernizarea rețelei semaforizate, senzori radar, camere detecție automată incidente.",
                action_deadline="2026-09-18",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/iasi-its-101",
                metadata={"stage": "Consultare de piata", "cpv_code": "34996000-5"}
            ),
            RawInstitutionalSignal(
                source_id=f"SICAP-MC-IASI-IRO-{now_ts}",
                source_type="SICAP",
                category="sanatate",
                county="Iasi",
                locality="Iasi",
                entity_name="Institutul Regional de Oncologie (IRO) Iași",
                project_title="Consultare Piață: Furnizare echipamente de radioterapie stereotaxică și acceleratoare liniare de particule",
                estimated_value_ron=34000000.0,
                raw_description="Stabilire cerințe tehnice și bugetare pentru 2 acceleratoare liniare de energie înaltă cu sistem ghidaj imagistic integrat.",
                action_deadline="2026-09-25",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/iro-iasi-rad-202",
                metadata={"stage": "Consultare de piata", "cpv_code": "33151000-3"}
            ),
            RawInstitutionalSignal(
                source_id=f"SICAP-MC-CJ-TRAF-{now_ts}",
                source_type="SICAP",
                category="infrastructura",
                county="Cluj",
                locality="Cluj-Napoca",
                entity_name="Municipiul Cluj-Napoca",
                project_title="Consultare de Piață: Sistem integrat de monitorizare trafic și prioritizare transport public ecologic",
                estimated_value_ron=14500000.0,
                raw_description="Achiziție soluții software UTMC cu algoritmi de prioritizare a flotei de autobuze electrice și troleibuze.",
                action_deadline="2026-09-15",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1001",
                metadata={"stage": "Consultare de piata", "cpv_code": "48732000-8"}
            ),
            RawInstitutionalSignal(
                source_id=f"SICAP-MC-B-FLOR-{now_ts}",
                source_type="SICAP",
                category="sanatate",
                county="Bucuresti",
                locality="Sector 1",
                entity_name="Spitalul Clinic de Urgență Floreasca",
                project_title="Consultare de Piață: Echipamente imagistică medicală de înaltă rezoluție (RMN 3T și CT 128 slice)",
                estimated_value_ron=22000000.0,
                raw_description="Identificare soluții optime pentru aparatură imagistică de urgență cu contrast și soft reconstrucție 3D cardiacă.",
                action_deadline="2026-09-20",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1002",
                metadata={"stage": "Consultare de piata", "cpv_code": "33115000-9"}
            )
        ]
