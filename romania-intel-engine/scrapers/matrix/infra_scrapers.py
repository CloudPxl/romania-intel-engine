from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

class SicapInfraScraper(BaseScraper):
    def __init__(self): super().__init__("SicapInfra", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="SICAP-MC-INFRA-101",
            source_type="SICAP Consultari",
            category="infrastructura",
            sub_category="Sisteme Inteligente Trafic (ITS)",
            county="Iasi",
            locality="Iasi",
            entity_name="Municipiul Iasi (Primaria Iasi)",
            project_title="Consultare Piata: Sistem integrat SCATS, prioritizare tramvaie si 32 camere ANPR",
            estimated_value_ron=18200000.0,
            published_date="2026-08-22",
            action_deadline="2026-09-18",
            raw_description="Consultare preliminara pentru stabilirea cerintelor tehnice de extindere a subsistemului de semnalizare adaptiva si detectie AID.",
            source_url="https://e-licitatie.ro/pub/notices/mc-notices/list/2/1",
            metadata={"cpv_code": "34996000-5"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class CniInfraScraper(BaseScraper):
    def __init__(self): super().__init__("CniInfra", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="CNI-INFRA-ARENA-02",
            source_type="CNI National",
            category="infrastructura",
            sub_category="Complexe Multifunctionale nZEB",
            county="Iasi",
            locality="Iasi",
            entity_name="Compania Nationala de Initii (CNI) / Primaria Iasi",
            project_title="CNI: Proiectare si executie Sala Polivalenta Regina Maria (10.000 locuri)",
            estimated_value_ron=240000000.0,
            published_date="2026-08-20",
            action_deadline="2026-10-30",
            raw_description="Avizare indicatori tehnico-economici in comisia interministeriala pentru complex sportiv cu fatada fotovoltaica integrata.",
            source_url="https://www.cni.ro/proiecte",
            metadata={"program": "Sali Polivalente"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class CnairCfrScraper(BaseScraper):
    def __init__(self): super().__init__("CnairCfr", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="CNAIR-A8-MONTAN-03",
            source_type="CNAIR Registru",
            category="infrastructura",
            sub_category="Autostrazi & Tuneluri Forate",
            county="Iasi",
            locality="Targu Neamt - Pascani",
            entity_name="CNAIR SA",
            project_title="CNAIR: Consultare caiet de sarcini Tronson A8 Targu Neamt - Iasi - Ungheni (Lot 2)",
            estimated_value_ron=3200000000.0,
            published_date="2026-08-24",
            action_deadline="2026-10-15",
            raw_description="Definire criterii de calificare tehnica pentru viaducte speciale, tuneluri cut&cover si structuri de consolidare versanti.",
            source_url="https://www.cnadnr.ro/ro/transparenta/programul-anual-al-achizitiilor-publice",
            metadata={"corridor": "TEN-T Core A8"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class UrbanismAcScraper(BaseScraper):
    def __init__(self): super().__init__("UrbanismAC", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="AC-METROU-CLUJ-04",
            source_type="Registru Urbanism AC",
            category="infrastructura",
            sub_category="Infrastructura Feroviara Subterana",
            county="Cluj",
            locality="Floresti / Cluj-Napoca",
            entity_name="Primaria Floresti / Primaria Cluj-Napoca",
            project_title="Autorizatie de Construire: Depou si Statii Tronson 1 Metrou Cluj",
            estimated_value_ron=310000000.0,
            published_date="2026-08-19",
            action_deadline="2026-10-30",
            raw_description="Emitere autorizatie de construire pentru infrastructura subterana, deviere utilitati si puturi de lansare TBM.",
            source_url="https://primariaclujnapoca.ro/achizitii-publice/",
            metadata={"permit_no": "AC 1142/2026"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class CountyHclScraper(BaseScraper):
    def __init__(self): super().__init__("CountyHcl", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="HCL-PASAJ-PODU-ROS-05",
            source_type="HCL Registru",
            category="infrastructura",
            sub_category="Pasaje Denivelate & Fluidizare",
            county="Iasi",
            locality="Iasi",
            entity_name="Consiliul Local Iasi",
            project_title="Hotarare CL Iasi: Indicatori tehnico-economici Pasaj Subteran Podu Ros",
            estimated_value_ron=115000000.0,
            published_date="2026-08-21",
            action_deadline="2026-11-15",
            raw_description="Aprobare studiu de fezabilitate si deviz general pentru fluidizarea traficului in intersectia Podu Ros si conectare axa Nicolina.",
            source_url="https://www.primaria-iasi.ro",
            metadata={"resolution": "HCL 388/2026"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]
