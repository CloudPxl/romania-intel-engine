from typing import List
from src.scrapers.base_adapter import BaseSourceAdapter
from src.database.models import RawRecord, SourceCategory
from src.utils.http_client import fetch_with_retry

class ClujUrbanismAdapter(BaseSourceAdapter):
    def __init__(self):
        super().__init__(
            name="Primaria Cluj-Napoca Urbanism",
            category=SourceCategory.URBANISM,
            poll_interval_minutes=60
        )
        self.institution = "Primăria Municipiului Cluj-Napoca"
        self.portal_url = "https://e-primariaclujnapoca.ro/registratura/autorizatii/index.php"

    async def fetch_latest(self) -> List[RawRecord]:
        new_records: List[RawRecord] = []
        html = await fetch_with_retry(self.portal_url, timeout=10)
        if not html:
            return new_records

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return new_records

        for row in table.find_all("tr")[1:25]:
            cols = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cols) >= 3:
                nr_ac = cols[0]
                applicant = cols[1]
                scope = cols[2]
                title = f"Autorizație de construire {nr_ac}: {scope}"
                source_id = self.generate_source_id(f"CLUJ_AC_{nr_ac}_{scope[:40]}")

                new_records.append(RawRecord(
                    source_id=source_id,
                    category=self.category,
                    county="Cluj",
                    locality="Cluj-Napoca",
                    institution=self.institution,
                    document_title=title,
                    document_url=self.portal_url,
                    raw_metadata={
                        "ac_number": nr_ac,
                        "beneficiary": applicant,
                        "authority_name": self.institution,
                        "status": "Autorizație AC Emisă"
                    }
                ))
        return new_records
