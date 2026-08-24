import logging
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("DigitalMatrix")

class SicapDigitalScraper(BaseScraper):
    def __init__(self): super().__init__("SicapDigital", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="SICAP-DIGI-CLUJ-21",
                source_type="SICAP Consultari",
                category="digitalizare",
                sub_category="Software Mobilitate Urbana UTMC",
                county="Cluj",
                locality="Cluj-Napoca",
                entity_name="Municipiul Cluj-Napoca",
                project_title="Consultare de Piata: Sistem software UTMC integrat si prioritizare transport public ecologic",
                estimated_value_ron=14500000.0,
                published_date="2026-08-20",
                action_deadline="2026-09-15",
                raw_description="Analiza solutii prioritizare tramvaie si troleibuze in nodurile aglomerate, integrare cu aplicatia mobila calatori.",
                source_url="https://e-licitatie.ro/pub/notices/mc-notices/view/1003",
                metadata={"cpv_code": "48732000-8"}
            )
        ]

class AdrRegionalDigiScraper(BaseScraper):
    def __init__(self): super().__init__("AdrRegional", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="ADR-NV-DIGI-SME-22",
                source_type="ADR Nord-Vest",
                category="digitalizare",
                sub_category="Automatizare Robotica RPA & Cloud",
                county="Cluj",
                locality="Cluj-Napoca",
                entity_name="Agentia de Dezvoltare Regionala Nord-Vest",
                project_title="Apel ADR NV: Transformarea digitala avansata a companiilor de productie prin solutii AI si IoT",
                estimated_value_ron=52000000.0,
                published_date="2026-08-24",
                action_deadline="2026-10-20",
                raw_description="Ghid consultativ pentru granturi nerambursabile intre 250.000 si 1.500.000 EUR pentru integrare ERP, senzori IoT industriali si cloud.",
                source_url="https://regionordvest.ro/apeluri-digitalizare-2026",
                metadata={"grant_program": "PRNV 2026"}
            )
        ]

class McidGovCloudScraper(BaseScraper):
    def __init__(self): super().__init__("McidCloud", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="MCID-CLOUD-GOV-23",
                source_type="MCID / ADR National",
                category="digitalizare",
                sub_category="Cloud Guvernamental & Interoperabilitate",
                county="Bucuresti",
                locality="Bucuresti",
                entity_name="Ministerul Cercetarii, Inovarii si Digitalizarii (MCID) / ADR",
                project_title="MCID: Platforma nationala de interoperabilitate date publice (Baza Nationala de Schimb de Date)",
                estimated_value_ron=110000000.0,
                published_date="2026-08-23",
                action_deadline="2026-10-30",
                raw_description="Consultare arhitectura microservicii securizata pentru schimbul automatizat de date intre ANAF, ONRC, MAI si administratiile locale.",
                source_url="https://mcid.gov.ro/consultari-publice-cloud",
                metadata={"legal_basis": "Legea Interoperabilitatii"}
            )
        ]

class TechParksInnovationScraper(BaseScraper):
    def __init__(self): super().__init__("TechParks", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="PARC-INOV-BIHOR-24",
                source_type="HCL Registru",
                category="digitalizare",
                sub_category="Parcuri Tehnologice & R&D",
                county="Bihor",
                locality="Oradea",
                entity_name="Primaria Municipiului Oradea",
                project_title="HCL Oradea: Extindere Parc Stiintific si Tehnologic Bihor - Construire Centru Inovare Aplicata",
                estimated_value_ron=54000000.0,
                published_date="2026-08-22",
                action_deadline="2026-10-20",
                raw_description="Aprobare parteneriat judetean pentru extinderea infrastructurii de laboratoare de testare industriala si eficienta robotica.",
                source_url="https://oradea.ro/hotarari-consiliu-local",
                metadata={"resolution": "HCL 492/2026"}
            )
        ]

class SmartTransportUrbanScraper(BaseScraper):
    def __init__(self): super().__init__("SmartTransport", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        return [
            RawInstitutionalSignal(
                source_id="CTP-IASI-TICKETING-25",
                source_type="Regie Publica Transport",
                category="digitalizare",
                sub_category="Smart Ticketing EMV & Informare Calatori",
                county="Iasi",
                locality="Iasi",
                entity_name="Compania de Transport Public (CTP) Iasi",
                project_title="CTP Iasi: Sistem modern de ticketing contactless EMV la bord si panouri inteligente e-paper in 120 statii",
                estimated_value_ron=19500000.0,
                published_date="2026-08-24",
                action_deadline="2026-09-25",
                raw_description="Consultare specificatii validatoare bancare contactless la fiecare usa si dispecerat integrat de monitorizare flota GPS.",
                source_url="https://sctpiasi.ro/achizitii",
                metadata={"cpv_code": "30144200-2"}
            )
        ]
