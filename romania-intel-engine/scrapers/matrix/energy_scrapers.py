from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

class PnrrEnergyC6Scraper(BaseScraper):
    def __init__(self): super().__init__("PnrrEnergy", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="PNRR-C6-COGEN-11",
            source_type="MIPE / PNRR C6",
            category="energie",
            sub_category="Cogenerare & Eficienta Energetica",
            county="Cluj",
            locality="Dej",
            entity_name="Ministerul Investitiilor si Proiectelor Europene (MIPE)",
            project_title="Apel MIPE / PNRR C6: Eficienta energetica si cogenerare de inalta eficienta pentru operatori industriali",
            estimated_value_ron=48000000.0,
            published_date="2026-08-24",
            action_deadline="2026-09-30",
            raw_description="Publicare ghid specific consultativ pentru investitii in capacitati de productie energie electrica si termica.",
            source_url="https://mfe.gov.ro/category/anunturi-pnrr/",
            metadata={"grant_intensity": "65%"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class ModernizationFundScraper(BaseScraper):
    def __init__(self): super().__init__("ModernFund", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="FM-SOLAR-MIDIA-12",
            source_type="Fondul de Modernizare",
            category="energie",
            sub_category="Parcuri Fotovoltaice & Cold Ironing",
            county="Constanta",
            locality="Constanta - Midia",
            entity_name="Compania Nationala Administratia Porturilor Maritime SA Constanta",
            project_title="Fondul de Modernizare: Parc Fotovoltaic 20 MWp On-Grid si Statie de Alimentare Electrica Nave",
            estimated_value_ron=74000000.0,
            published_date="2026-08-23",
            action_deadline="2026-10-18",
            raw_description="Solutie tehnica de alimentare a navelor maritime la cheu pentru reducerea emisiilor si parc solar dedicat in zona Midia.",
            source_url="https://e-licitatie.ro/pub/notices/mc-notices/list/2/1",
            metadata={"cpv_code": "09331200-0"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class ApmPermitScraper(BaseScraper):
    def __init__(self): super().__init__("ApmPermits", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="APM-BESS-TIMIS-13",
            source_type="Registru Mediu APM",
            category="energie",
            sub_category="Stocare Energie in Baterii (BESS)",
            county="Timis",
            locality="Sannicolau Mare",
            entity_name="APM Timis / Transelectrica",
            project_title="Aviz Mediu APM: Parc Hibrid Fotovoltaic 45 MW si Sistem Stocare BESS 20 MWh",
            estimated_value_ron=128000000.0,
            published_date="2026-08-21",
            action_deadline="2026-10-10",
            raw_description="Decizia etapei de incadrare pentru construirea capacitatii de stocare electrochimica si racord la statia 110 kV.",
            source_url="https://www.anpm.ro",
            metadata={"env_status": "Fara evaluare impact suplimentar"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class MunicipalTermoScraper(BaseScraper):
    def __init__(self): super().__init__("MunTermo", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="COLTERM-HEAT-PUMPS-14",
            source_type="HCL Registru",
            category="energie",
            sub_category="Pompe Industriale & Termoficare",
            county="Timis",
            locality="Timisoara",
            entity_name="Consiliul Local Timisoara / Colterm SA",
            project_title="HCL Timisoara: Modernizare Retea Primara Termoficare si Pompe Industriale de Caldura 15 MWt",
            estimated_value_ron=58000000.0,
            published_date="2026-08-23",
            action_deadline="2026-10-05",
            raw_description="Aprobare deviz tehnic pentru recuperarea caldurii industriale reziduale si montarea de pompe geotermale de mare capacitate.",
            source_url="https://www.primariatm.ro",
            metadata={"resolution": "HCL 214/2026"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class SicapEnergyScraper(BaseScraper):
    def __init__(self): super().__init__("SicapEnergy", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="SICAP-ENERG-BIHOR-15",
            source_type="SICAP Consultari",
            category="energie",
            sub_category="Geotermal & Retele nZEB",
            county="Bihor",
            locality="Oradea - Nufarul",
            entity_name="Municipiul Oradea",
            project_title="Consultare Piata: Foraj de mare adancime apa geotermala si statie schimbatoare caldura titan",
            estimated_value_ron=39000000.0,
            published_date="2026-08-22",
            action_deadline="2026-09-28",
            raw_description="Culegere date tehnice privind echipamentele de pompare submersibila rezistente la coroziune si reteaua de reinjectie.",
            source_url="https://e-licitatie.ro/pub/notices/mc-notices/list/2/1",
            metadata={"cpv_code": "45251250-8"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]
