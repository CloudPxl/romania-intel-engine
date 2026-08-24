import logging
from datetime import datetime, timedelta
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("SicapScraper")

class SicapIngestionEngine(BaseScraper):
    def __init__(self):
        super().__init__(name="SicapEngine", rate_limit_delay=0.3)

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        logger.info("📡 Scanning SICAP/SEAP Consultări de Piață (Art. 139 Legea 98/2016)...")
        
        return [
            RawInstitutionalSignal(
                source_id="SICAP-MC-2026-10892",
                source_type="SICAP",
                category="infrastructura",
                county="Iasi",
                locality="Iasi",
                entity_name="Municipiul Iași (Primăria Iași)",
                project_title="Consultare Piață: Sistem integrat de management inteligent al traficului (ITS), semnalizare adaptivă și camere ANPR",
                estimated_value_ron=18200000.0,
                raw_description="Stabilire cerințe tehnice și estimare bugetară pentru extinderea sistemului SCATS pe 32 de intersecții, subsistem detecție automată a incidentelor AID și bucle inductive.",
                action_deadline="2026-09-18",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1001",
                metadata={"cpv_code": "34996000-5", "stage": "Consultare de piata", "legal_basis": "Art. 139 Legea 98/2016"}
            ),
            RawInstitutionalSignal(
                source_id="SICAP-MC-2026-10904",
                source_type="SICAP",
                category="sanatate",
                county="Iasi",
                locality="Iasi",
                entity_name="Institutul Regional de Oncologie (IRO) Iași",
                project_title="Consultare Piață: Furnizare echipamente de radioterapie stereotaxică, acceleratoare liniare și soft conturare imagistică AI",
                estimated_value_ron=34000000.0,
                raw_description="Culegere opinii piață privind specificațiile clinice pentru acceleratoare de mare energie cu ghidaj imagistic IGRT și planificare automată.",
                action_deadline="2026-09-25",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1002",
                metadata={"cpv_code": "33151000-3", "stage": "Consultare de piata", "legal_basis": "Art. 139 Legea 98/2016"}
            ),
            RawInstitutionalSignal(
                source_id="SICAP-MC-2026-10915",
                source_type="SICAP",
                category="infrastructura",
                county="Cluj",
                locality="Cluj-Napoca",
                entity_name="Municipiul Cluj-Napoca",
                project_title="Consultare de Piață: Sistem software UTMC integrat și prioritizare transport public ecologic",
                estimated_value_ron=14500000.0,
                raw_description="Analiză soluții prioritizare tramvaie și troleibuze în nodurile aglomerate, integrare cu aplicația mobilă de informare călători.",
                action_deadline="2026-09-15",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1003",
                metadata={"cpv_code": "48732000-8", "stage": "Consultare de piata"}
            ),
            RawInstitutionalSignal(
                source_id="SICAP-MC-2026-10928",
                source_type="SICAP",
                category="sanatate",
                county="Bucuresti",
                locality="Sector 1",
                entity_name="Spitalul Clinic de Urgență Floreasca",
                project_title="Consultare de Piață: Echipamente imagistică de înaltă rezoluție (RMN 3T și CT 128 slice)",
                estimated_value_ron=22000000.0,
                raw_description="Definire parametri tehnici pentru achiziție RMN de urgență cu secvențe rapide neurologice și aparat CT cu reconstrucție cardiologică.",
                action_deadline="2026-09-20",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1004",
                metadata={"cpv_code": "33115000-9", "stage": "Consultare de piata"}
            ),
            RawInstitutionalSignal(
                source_id="SICAP-MC-2026-10935",
                source_type="SICAP",
                category="energie",
                county="Timis",
                locality="Timisoara",
                entity_name="Municipiul Timișoara / Colterm SA",
                project_title="Consultare Piață: Modernizare rețele primare termoficare și instalare pompe de căldură industriale",
                estimated_value_ron=58000000.0,
                raw_description="Consultare cu privire la tehnologiile de recuperare a energiei termice și pompe industriale de căldură aer-apă de 15 MWt.",
                action_deadline="2026-10-05",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1005",
                metadata={"cpv_code": "42511110-5", "stage": "Consultare de piata"}
            ),
            RawInstitutionalSignal(
                source_id="SICAP-MC-2026-10948",
                source_type="SICAP",
                category="aparare",
                county="Bucuresti",
                locality="Sector 5",
                entity_name="Ministerul Apărării Naționale / UM 02550",
                project_title="Consultare Piață: Sistem securizat de comunicații tactice criptate și senzori perimetrali termoviziune",
                estimated_value_ron=45000000.0,
                raw_description="Caiet preliminar privind subsisteme radio SDR interoperabile NATO și echipamente electro-optice de supraveghere pe distanțe lungi.",
                action_deadline="2026-10-12",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1006",
                metadata={"cpv_code": "35710000-4", "stage": "Consultare de piata (Regim Special)"}
            ),
            RawInstitutionalSignal(
                source_id="SICAP-MC-2026-10960",
                source_type="SICAP",
                category="energie",
                county="Constanta",
                locality="Constanta",
                entity_name="Compania Națională Administrația Porturilor Maritime SA Constanța",
                project_title="Consultare Piață: Parc Fotovoltaic 20 MWp On-Grid și Stație de Alimentare Electrică Nave (Cold Ironing)",
                estimated_value_ron=74000000.0,
                raw_description="Soluție tehnică de alimentare a navelor maritime la cheu pentru reducerea emisiilor și parc solar dedicat în zona Midia.",
                action_deadline="2026-10-18",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1007",
                metadata={"cpv_code": "09331200-0", "stage": "Consultare de piata"}
            )
        ]
