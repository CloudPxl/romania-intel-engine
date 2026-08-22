import re
from typing import List
from bs4 import BeautifulSoup
from src.scrapers.base_adapter import BaseSourceAdapter
from src.database.models import RawRecord, SourceCategory
from src.utils.http_client import fetch_with_retry

class BucurestiUrbanismAdapter(BaseSourceAdapter):
    def __init__(self):
        super().__init__(
            source_name="Primăria Municipiului București & Sectoare Urbanism",
            category=SourceCategory.URBANISM,
            poll_interval_minutes=60
        )
        self.endpoints = [
            {"sector": "PMB General", "url": "https://www.pmb.ro/urbanism/autorizatii-constructie"},
            {"sector": "Sector 1", "url": "https://www.primariasector1.ro/autorizatii-de-construire.html"},
            {"sector": "Sector 2", "url": "https://www.ps2.ro/index.php/informatii-publice/urbanism"},
            {"sector": "Sector 3", "url": "https://www.primarie3.ro/index.php/informatii_publice/autorizatii_de_construire"},
            {"sector": "Sector 6", "url": "https://www.primarie6.ro/urbanism/autorizatii-de-construire/"}
        ]

    async def fetch_latest(self) -> List[RawRecord]:
        new_records: List[RawRecord] = []

        for target in self.endpoints:
            sector_name = target["sector"]
            url = target["url"]

            try:
                html = await fetch_with_retry(url, timeout=12)
                if not html:
                    continue

                soup = BeautifulSoup(html, "html.parser")
                entries = soup.find_all(["tr", "div", "li"], class_=re.compile(r"item|row|autorizatie|document|tabel", re.I))

                for row in entries[:20]:
                    text = row.get_text(separator=" ", strip=True)
                    if len(text) < 40 or not any(k in text.lower() for k in ["construire", "imobil", "locuinte", "hala", "desfiintare", "amenajare"]):
                        continue

                    title = re.sub(r"\s+", " ", text)[:260]
                    link = row.find("a")
                    doc_url = link["href"] if link and link.has_attr("href") else url

                    source_id = self.generate_source_id(f"BUC_{sector_name}_{title[:60]}")

                    new_records.append(RawRecord(
                        source_id=source_id,
                        category=self.category,
                        county="Bucuresti",
                        locality=sector_name,
                        institution=f"Primăria {sector_name}",
                        document_title=title,
                        document_url=doc_url,
                        raw_metadata={
                            "stage": "Autorizație de Construire Emisă",
                            "sector": sector_name,
                            "authority_name": f"Primăria {sector_name}"
                        }
                    ))
            except Exception:
                continue

        return new_records