from typing import List
from src.scrapers.base_adapter import BaseSourceAdapter
from src.database.models import RawRecord, SourceCategory
from src.utils.http_client import fetch_with_retry

class DataGovRoAdapter(BaseSourceAdapter):
    def __init__(self):
        super().__init__(
            name="Guvernul Romaniei (Data.gov.ro)",
            category=SourceCategory.OPEN_DATA,
            poll_interval_minutes=180
        )
        self.institution = "Secretariatul General al Guvernului"
        self.api_url = "https://data.gov.ro/api/3/action/package_search"

    async def fetch_latest(self) -> List[RawRecord]:
        new_records: List[RawRecord] = []
        data = await fetch_with_retry(self.api_url, params={"q": "achizitii OR investitii OR buget OR proiecte", "rows": 25}, timeout=12)
        if not data or not isinstance(data, dict):
            return new_records
        results = data.get("result", {}).get("results", [])
        for pkg in results:
            title = (pkg.get("title") or "").strip()
            if len(title) < 15:
                continue
            pkg_id = pkg.get("id")
            org = pkg.get("organization", {})
            org_title = org.get("title") if isinstance(org, dict) else "Autoritate Publica Nationala"
            resources = pkg.get("resources", [])
            doc_url = resources[0].get("url") if resources else f"https://data.gov.ro/dataset/{pkg_id}"
            source_id = self.generate_source_id(f"DATAGOV_{pkg_id}_{title[:40]}")
            new_records.append(RawRecord(
                source_id=source_id,
                category=self.category,
                county="National",
                locality="National",
                institution=org_title,
                document_title=title[:220],
                document_url=doc_url,
                raw_metadata={
                    "authority_name": org_title,
                    "notes": (pkg.get("notes") or "")[:200]
                }
            ))
        return new_records
