import re
from typing import List
from bs4 import BeautifulSoup
from src.scrapers.base_adapter import BaseSourceAdapter
from src.database.models import RawRecord, SourceCategory
from src.utils.http_client import fetch_with_retry

class ApmEnvironmentalAdapter(BaseSourceAdapter):
    def __init__(self):
        super().__init__(
            name="ANPM National Environmental Agency",
            category=SourceCategory.ENVIRONMENT,
            poll_interval_minutes=90
        )
        self.portal_url = "http://www.anpm.ro/acordul-de-mediu"

    async def fetch_latest(self) -> List[RawRecord]:
        new_records: List[RawRecord] = []
        html = await fetch_with_retry(self.portal_url, timeout=8)
        if not html:
            return new_records

        soup = BeautifulSoup(html, "html.parser")
        entries = soup.find_all(["tr", "div", "li"], class_=re.compile(r"item|row|article|content", re.I))
        if not entries:
            entries = soup.find_all("a", href=re.compile(r"acord|proiect|decizie", re.I))

        for item in entries[:20]:
            text = item.get_text(separator=" ", strip=True)
            if len(text) < 30:
                continue
            title = re.sub(r"\s+", " ", text)[:250]
            link = item.find("a") if item.name != "a" else item
            doc_url = link["href"] if link and link.has_attr("href") else self.portal_url
            if doc_url.startswith("/"):
                doc_url = f"http://www.anpm.ro{doc_url}"
            source_id = self.generate_source_id(f"ANPM_NAT_{title[:60]}_{doc_url}")

            new_records.append(RawRecord(
                source_id=source_id,
                category=self.category,
                county="National",
                locality="National",
                institution="Agenția Națională pentru Protecția Mediului (ANPM)",
                document_title=title,
                document_url=doc_url,
                raw_metadata={
                    "stage": "Aviz / Acord de Mediu",
                    "authority_name": "ANPM România"
                }
            ))
        return new_records
