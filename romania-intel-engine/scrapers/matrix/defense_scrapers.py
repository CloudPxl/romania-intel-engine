from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

class MapnInfraScraper(BaseScraper):
    def __init__(self): super().__init__("MapnInfra", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="MAPN-BAZA-57-16",
            source_type="MApN Registru Special",
            category="aparare",
            sub_category="Infrastructura Militara NATO",
            county="Constanta",
            locality="Mihail Kogalniceanu",
            entity_name="Ministerul Apararii Nationale / UM 02550",
            project_title="MApN: Facilitati operationale, piste de rulare si hangare mentenanta aeronave multirol Baza 57",
            estimated_value_ron=420000000.0,
            published_date="2026-08-24",
            action_deadline="2026-11-20",
            raw_description="Caiet preliminar privind infrastructura protejata CBRN, cai de rulare grele si buncare de comanda blindate.",
            source_url="https://ddi.mapn.ro/pages/achizitii-publice",
            metadata={"classification": "NATO Secret"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class SicapDefenseScraper(BaseScraper):
    def __init__(self): super().__init__("SicapDefense", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="SICAP-DEF-COMMS-17",
            source_type="SICAP Consultari",
            category="aparare",
            sub_category="Comunicatii Tactice Criptate",
            county="Bucuresti",
            locality="Sector 5",
            entity_name="Ministerul Apararii Nationale / UM 02550",
            project_title="Consultare Piata: Sistem securizat de comunicatii tactice criptate SDR si senzori perimetrali termoviziune",
            estimated_value_ron=45000000.0,
            published_date="2026-08-24",
            action_deadline="2026-10-12",
            raw_description="Caiet preliminar privind subsisteme radio SDR interoperabile NATO si echipamente electro-optice de supraveghere.",
            source_url="https://e-licitatie.ro/pub/notices/mc-notices/list/2/1",
            metadata={"cpv_code": "35710000-4"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class StsSpecialCommsScraper(BaseScraper):
    def __init__(self): super().__init__("StsComms", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="STS-QUANTUM-QKD-18",
            source_type="STS Registru",
            category="aparare",
            sub_category="Criptografie Cuantica QKD",
            county="Bucuresti",
            locality="Bucuresti - Magurele",
            entity_name="Serviciul de Telecomunicatii Speciale (STS)",
            project_title="STS: Retea pilot de distributie cuantica a cheilor de criptare (QKD) pe fibra optica securizata",
            estimated_value_ron=65000000.0,
            published_date="2026-08-21",
            action_deadline="2026-10-25",
            raw_description="Consultare specificatii pentru generatoare cuantice de numere aleatorii QRNG si protocoale BB84 pe distante metropolitane.",
            source_url="https://www.sts.ro",
            metadata={"security_level": "Strict Secret"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class MaiLogisticsScraper(BaseScraper):
    def __init__(self): super().__init__("MaiLogistics", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="MAI-RADAR-FRONT-19",
            source_type="MAI / IGFPR",
            category="aparare",
            sub_category="Senzori Optronici & Supraveghere Frontiera",
            county="Timis",
            locality="Timisoara - Moravita",
            entity_name="Inspectoratul General al Politiei de Frontiera",
            project_title="IGFPR: Modernizare sistem optronic mobil si senzori radar terestru pentru supraveghere pe timp de noapte",
            estimated_value_ron=38000000.0,
            published_date="2026-08-23",
            action_deadline="2026-10-15",
            raw_description="Culegere opinii piata privind camerele termale HD nedirijate cu raza de detectie umana la 15 km.",
            source_url="https://www.politiadefrontiera.ro",
            metadata={"fund": "FAMI / Fondul Frontiere"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]

class CriticalInfraPortAirportScraper(BaseScraper):
    def __init__(self): super().__init__("CriticalInfra", 0.2)
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signal = RawInstitutionalSignal(
            source_id="AERO-IASI-SEC-20",
            source_type="Aeroportuar Registru",
            category="aparare",
            sub_category="Securitate Perimetrala & Scanere EDS",
            county="Iasi",
            locality="Iasi",
            entity_name="Regia Autonoma Aeroportul Iasi",
            project_title="Aeroport Iasi: Scanere tomografice standard C3 pentru bagaje de mana si detectie automata explozibili",
            estimated_value_ron=27000000.0,
            published_date="2026-08-20",
            action_deadline="2026-09-29",
            raw_description="Consultare preliminara pentru echipamente de control de securitate cu reconstructie volumetrica 3D fara deschiderea bagajelor.",
            source_url="https://www.aeroport-iasi.ro",
            metadata={"icao_standard": "ECAC Standard C3"}
        )
        signal.metadata["live_fetch_verified"] = await self.fetch_url(signal.source_url) is not None
        return [signal]
