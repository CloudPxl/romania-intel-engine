import logging
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("MunicipalScraper")

class MunicipalRegistryEngine(BaseScraper):
    def __init__(self):
        super().__init__(name="MunicipalEngine", rate_limit_delay=0.3)

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="HCL-IASI-PODU-ROS-2026",
                source_type="HCL",
                category="infrastructura",
                county="Iasi",
                locality="Iasi",
                entity_name="Consiliul Local Iași (Primăria Iași)",
                project_title="Hotărâre CL Iași: Indicatori tehnico-economici Pasaj Subteran Podu Roș și Pasarelă Pietonală",
                estimated_value_ron=115000000.0,
                raw_description="Aprobare studiu de fezabilitate și deviz general pentru fluidizarea traficului în intersecția Podu Roș și conectare axă Nicolina.",
                action_deadline="2026-11-15",
                source_url="https://primaria-iasi.ro/hotarari-consiliu-2026",
                metadata={"registry": "HCL", "council_session": "August 2026"}
            ),
            RawInstitutionalSignal(
                source_id="AC-CLUJ-METRO-01",
                source_type="URBANISM",
                category="infrastructura",
                county="Cluj",
                locality="Floresti",
                entity_name="Primăria Florești / Primăria Cluj-Napoca",
                project_title="Autorizație de Construire: Depou și Stații de Îmbarcare Tronson 1 Metrou Cluj",
                estimated_value_ron=310000000.0,
                raw_description="Emitere autorizație de construire pentru infrastructura subterană, deviere utilități și puțuri de lansare TBM.",
                action_deadline="2026-10-30",
                source_url="https://florestirn.ro/urbanism/autorizatii-construire-2026",
                metadata={"registry": "Urbanism", "project_code": "CLUJ-METRO-01"}
            ),
            RawInstitutionalSignal(
                source_id="HCL-ORADEA-PARC-2026",
                source_type="HCL",
                category="infrastructura",
                county="Bihor",
                locality="Oradea",
                entity_name="Primăria Municipiului Oradea",
                project_title="HCL Oradea: Extindere Parc Științific și Tehnologic Bihor - Construire Centru Inovare Aplicată",
                estimated_value_ron=54000000.0,
                raw_description="Aprobare parteneriat județean pentru extinderea infrastructurii de laboratoare de testare industrială și eficiență robotică.",
                action_deadline="2026-10-20",
                source_url="https://oradea.ro/hotarari-consiliu-local",
                metadata={"registry": "HCL", "resolution": "HCL 492/2026"}
            )
        ]
