import re
from typing import List
from bs4 import BeautifulSoup
from src.scrapers.base_adapter import BaseSourceAdapter
from src.database.models import RawRecord, SourceCategory
from src.utils.http_client import fetch_with_retry

class NationalAdrHubAdapter(BaseSourceAdapter):
    def __init__(self):
        super().__init__(
            name="Agentii de Dezvoltare Regionala (ADR Hub)",
            category=SourceCategory.GRANTS,
            poll_interval_minutes=120
        )
        self.adr_endpoints = [
            {"region": "Nord-Est", "county": "Iasi", "url": "https://www.adrnordest.ro/apeluri-lansate-pr-nord-est/"},
            {"region": "Nord-Vest", "county": "Cluj", "url": "https://regionv.ro/ghiduri-si-apeluri-de-proiecte/"},
            {"region": "Centru", "county": "Brasov", "url": "https://www.adrcentru.ro/proiecte-si-finantari/"},
            {"region": "Vest", "county": "Timis", "url": "https://adrvest.ro/comunicate-de-presa/"}
        ]

    async def fetch_latest(self) -> List[RawRecord]:
        new_records: List[RawRecord] = []
        for endpoint in self.adr_endpoints:
            region = endpoint["region"]
            url = endpoint["url"]
            try:
                html = await fetch_with_retry(url, timeout=12)
                if not html or not isinstance(html, str):
                    continue
                soup = BeautifulSoup(html, "html.parser")
                links = soup.find_all("a", href=True)
                for a in links[:30]:
                    title = a.get_text(separator=" ", strip=True)
                    href = a["href"]
                    if len(title) < 25 or not any(k in title.lower() for k in ["apel", "ghid", "finantare", "grant", "proiect", "imm"]):
                        continue
                    if href.startswith("/"):
                        base = "/".join(url.split("/")[:3])
                        href = f"{base}{href}"
                    source_id = self.generate_source_id(f"ADR_{region}_{title[:50]}_{href}")
                    new_records.append(RawRecord(
                        source_id=source_id,
                        category=self.category,
                        county=endpoint["county"],
                        locality=region,
                        institution=f"ADR {region}",
                        document_title=f"[{region}] {title[:200]}",
                        document_url=href,
                        raw_metadata={
                            "grant_region": region,
                            "authority_name": f"ADR {region}",
                            "type": "Fonduri Europene Nerambursabile"
                        }
                    ))
            except Exception:
                continue
        return new_records
