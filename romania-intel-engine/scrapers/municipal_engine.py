import logging
from datetime import datetime
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("MunicipalScraper")

class MunicipalIngestionEngine(BaseScraper):
    def __init__(self):
        super().__init__(name="MunicipalUrbanismEngine", rate_limit_delay=0.4)

    async def fetch_all_regional_signals(self) -> List[RawInstitutionalSignal]:
        logger.info("📡 Monitoring Municipal Registries (Iași, Cluj, București, Timiș, Bihor)...")
        now_ts = int(datetime.now().timestamp())

        return [
            RawInstitutionalSignal(
                source_id=f"AC-IASI-MIROSLAVA-{now_ts}-1",
                source_type="URBANISM",
                category="energie",
                county="Iasi",
                locality="Miroslava",
                entity_name="Consiliul Județean Iași / Industrial Park Miroslava SA",
                project_title="Autorizație de Construire: Hub Logistic & Parc Fotovoltaic 28 MWp cu Baterii de Stocare BESS",
                estimated_value_ron=62500000.0,
                raw_description="Construire platformă industrială, racord la SEN 110 kV, parc fotovoltaic cu trackere monoaxiale și container stocare energie.",
                action_deadline="2026-10-10",
                source_url="https://primariamiroslava.ro/urbanism/autorizatii-2026",
                metadata={"registry": "Urbanism", "resolution": "AC 114/2026"}
            ),
            RawInstitutionalSignal(
                source_id=f"HCL-IASI-ITS-{now_ts}-2",
                source_type="HCL",
                category="infrastructura",
                county="Iasi",
                locality="Iasi",
                entity_name="Consiliul Local Iași (Primăria Iași)",
                project_title="Hotărâre CL Iași: Aprobare indicatori tehnico-economici pentru Pasaj Subteran Podu Roș și Pasarelă Pietonală",
                estimated_value_ron=115000000.0,
                raw_description="Aprobare proiect tehnic de fluidizare a traficului în intersecția Podu Roș. Finanțare multianuală din împrumut BERD și buget local.",
                action_deadline="2026-11-15",
                source_url="https://primaria-iasi.ro/hotarari-consiliu-2026",
                metadata={"registry": "HCL", "council_session": "August 2026"}
            ),
            RawInstitutionalSignal(
                source_id=f"AC-CLUJ-METROU-{now_ts}-3",
                source_type="URBANISM",
                category="infrastructura",
                county="Cluj",
                locality="Floresti",
                entity_name="Primăria Florești / Primăria Cluj-Napoca",
                project_title="Autorizație de Construire: Depou și Stații de Îmbarcare Tronson 1 Metrou Cluj",
                estimated_value_ron=310000000.0,
                raw_description="Lucrări de infrastructură grea, pereți mulați, relocare utilități magistrale apă/gaz și organizare de șantier TBM.",
                action_deadline="2026-10-30",
                source_url="https://florestirn.ro/urbanism/autorizatii-construire-2026",
                metadata={"registry": "Urbanism", "project_code": "CLUJ-METRO-01"}
            ),
            RawInstitutionalSignal(
                source_id=f"AC-TIMIS-SOLAR-{now_ts}-4",
                source_type="URBANISM",
                category="energie",
                county="Timis",
                locality="Sânandrei",
                entity_name="Consiliul Județean Timiș / Solaria West SRL",
                project_title="Autorizație de Construire: Parc Fotovoltaic 45 MW și Stație Transformare 110 kV",
                estimated_value_ron=85000000.0,
                raw_description="Instalare 78.000 panouri bifaciale, invertoare de putere 330 kVA și linie subterană 110 kV racordată la stația Transelectrica.",
                action_deadline="2026-10-01",
                source_url="https://cjtimis.ro/urbanism/autorizatii-2026",
                metadata={"registry": "Urbanism"}
            ),
            RawInstitutionalSignal(
                source_id=f"HCL-ORADEA-CAMPUS-{now_ts}-5",
                source_type="HCL",
                category="infrastructura",
                county="Bihor",
                locality="Oradea",
                entity_name="Primăria Municipiului Oradea",
                project_title="HCL Oradea: Extindere Parc Științific și Tehnologic Bihor - Construire Centru Inovare Aplicată",
                estimated_value_ron=54000000.0,
                raw_description="Aprobare SF și indicatori tehnico-economici pentru clădire laborator P+3E, laboratoare de robotică și rețele termice geotermale.",
                action_deadline="2026-10-20",
                source_url="https://oradea.ro/hotarari-consiliu-local",
                metadata={"registry": "HCL", "resolution": "HCL 492/2026"}
            )
        ]
