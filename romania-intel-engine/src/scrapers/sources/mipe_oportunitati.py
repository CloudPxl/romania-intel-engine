import re
from typing import List
from bs4 import BeautifulSoup
from src.scrapers.base_adapter import BaseSourceAdapter
from src.database.models import RawRecord, SourceCategory
from src.utils.http_client import fetch_with_retry

class MipeOportunitatiAdapter(BaseSourceAdapter):
    def __init__(self):
        super().__init__(
            name="Ministerul Fondurilor Europene (MIPE)",
            category=SourceCategory.GRANTS,
            poll_interval_minutes=120
        )
        self.institution = "Ministerul Investitiilor si Proiectelor Europene"
        self.feed_url = "https://mfe.gov.ro/programe-si-strategii/perioada-de-programare-2021-2027/"

    async def fetch_latest(self) -> List[RawRecord]:
        new_records: List[RawRecord] = []
        html = await fetch_with_retry(self.feed_url, timeout=12)
        if not html or not isinstance(html, str):
            return new_records
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True)[:35]:
            title = link.get_text(separator=" ", strip=True)
            href = link["href"]
            if len(title) < 25 or not any(k in title.lower() for k in ["apel", "ghid", "consultare", "finantare", "imm", "competitivitate", "digitalizare"]):
                continue
            if href.startswith("/"):
                href = f"https://mfe.gov.ro{href}"
            source_id = self.generate_source_id(f"MIPE_{title[:50]}_{href}")
            new_records.append(RawRecord(
                source_id=source_id,
                category=self.category,
                county="National",
                locality="Bucuresti",
                institution=self.institution,
                document_title=title[:220],
                document_url=href,
                raw_metadata={
                    "authority_name": self.institution,
                    "type": "Apeluri Deschise & Ghiduri MIPE"
                }
            ))
        return new_records
