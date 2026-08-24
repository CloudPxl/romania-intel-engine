import logging
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("HealthMatrix")

class SicapHealthScraper(BaseScraper):
    def __init__(self): super().__init__("SicapHealth", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="SICAP-HEALTH-IRO-06",
                source_type="SICAP Consultari",
                category="sanatate",
                sub_category="Radioterapie Stereotaxica & AI",
                county="Iasi",
                locality="Iasi",
                entity_name="Institutul Regional de Oncologie (IRO) Iasi",
                project_title="Consultare Piata: Furnizare acceleratoare liniare de mare energie si soft conturare imagistica AI",
                estimated_value_ron=34000000.0,
                published_date="2026-08-23",
                action_deadline="2026-09-25",
                raw_description="Culegere opinii piata privind specificatiile clinice pentru acceleratoare cu ghidaj imagistic IGRT si planificare automata.",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1002",
                metadata={"cpv_code": "33151000-3"}
            )
        ]

class MsRegionalHospitalScraper(BaseScraper):
    def __init__(self): super().__init__("MsRegional", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="MS-SRU-IASI-07",
                source_type="Ministerul Sanatatii / ANDIS",
                category="sanatate",
                sub_category="Spitale Regionale de Urgenta",
                county="Iasi",
                locality="Iasi - Miroslava",
                entity_name="ANDIS / Ministerul Sanatatii",
                project_title="SRU Iasi: Consultare tehnica pachet robotica chirurgicala si farmacii automatizate",
                estimated_value_ron=85000000.0,
                published_date="2026-08-24",
                action_deadline="2026-10-05",
                raw_description="Definire specificatii pentru blocul operator robotic integrat si subsistemul automatizat de distributie pneumatica.",
                source_url="https://andis.gov.ro/proiecte-sru",
                metadata={"hospital": "SRU Iasi"}
            )
        ]

class PnrrHealthC7Scraper(BaseScraper):
    def __init__(self): super().__init__("PnrrHealth", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="PNRR-C7-PACS-08",
                source_type="MIPE / PNRR C7",
                category="sanatate",
                sub_category="Sisteme Digitale PACS / RIS",
                county="Bucuresti",
                locality="Bucuresti",
                entity_name="Ministerul Sanatatii / MIPE PNRR C7",
                project_title="Apel Deschidere PNRR C7: Digitalizarea sistemului integrat de arhivare imagistica PACS national",
                estimated_value_ron=92000000.0,
                published_date="2026-08-22",
                action_deadline="2026-10-15",
                raw_description="Ghidul solicitantului pentru interconectarea retelelor de radiologie si imagistica medicala intre 45 de spitale de urgenta.",
                source_url="https://ms.ro/pnrr-digitalizare-spitale",
                metadata={"pillar": "Digital Health"}
            )
        ]

class CountyEmergencyHospitalScraper(BaseScraper):
    def __init__(self): super().__init__("EmergencyHosp", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="HOSP-FLOREASCA-09",
                source_type="Spital de Urgenta",
                category="sanatate",
                sub_category="Imagistica Medicala RMN/CT",
                county="Bucuresti",
                locality="Sector 1",
                entity_name="Spitalul Clinic de Urgenta Floreasca",
                project_title="Consultare de Piata: Echipamente imagistica de inalta rezolutie (RMN 3T si CT 128 slice)",
                estimated_value_ron=22000000.0,
                published_date="2026-08-24",
                action_deadline="2026-09-20",
                raw_description="Definire parametri tehnici pentru achizitie RMN de urgenta cu secvente rapide neurologice si aparat CT cardiologic.",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1004",
                metadata={"cpv_code": "33115000-9"}
            )
        ]

class CniHealthScraper(BaseScraper):
    def __init__(self): super().__init__("CniHealth", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="CNI-SPITAL-BV-10",
                source_type="CNI National",
                category="sanatate",
                sub_category="Bloc Operator & Terapie Intensiva",
                county="Brasov",
                locality="Brasov",
                entity_name="Compania Nationala de Investitii (CNI) / CJ Brasov",
                project_title="CNI: Construire Corp Nou Chirurgie & Terapie Intensiva Spitalul Judetean Brasov",
                estimated_value_ron=145000000.0,
                published_date="2026-08-24",
                action_deadline="2026-11-10",
                raw_description="Aprobare indicatori tehnico-economici pentru cladire spitaliceasca P+5E cu bloc operator integrat si heliport.",
                source_url="https://www.cni.ro/proiecte-aprobate-2026",
                metadata={"program": "Infrastructura Sanitara"}
            )
        ]
