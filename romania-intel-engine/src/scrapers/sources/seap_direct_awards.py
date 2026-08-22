from typing import List
from src.scrapers.base_adapter import BaseSourceAdapter
from src.database.models import RawRecord, SourceCategory
from src.utils.http_client import fetch_with_retry

class SeapDirectAwardsAdapter(BaseSourceAdapter):
    def __init__(self, min_value_ron: float = 20000.0):
        super().__init__(
            name="SEAP / SICAP Achizitii Directe Live",
            category=SourceCategory.PRE_SICAP,
            poll_interval_minutes=20
        )
        self.min_value_ron = min_value_ron
        self.api_url = "https://e-licitatie.ro/api-pub/DirectAcquisitionCommon/GetDirectAcquisitionList"

    async def fetch_latest(self) -> List[RawRecord]:
        new_records: List[RawRecord] = []
        payload = {
            "pageIndex": 0,
            "pageSize": 40,
            "sortProperties": [{"property": "publicationDate", "direction": 1}]
        }
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": "https://e-licitatie.ro/pub/direct-acquisitions/list/1"
        }
        data = await fetch_with_retry(self.api_url, method="POST", json_data=payload, headers=headers)
        if not data or not isinstance(data, dict):
            return new_records
        items = data.get("items", []) or data.get("list", [])
        for item in items:
            direct_id = item.get("directAcquisitionId") or item.get("id")
            title = (item.get("directAcquisitionName") or item.get("name") or "").strip()
            est_value = float(item.get("estimatedValueRon") or item.get("closingValue") or 0.0)
            if not title or est_value < self.min_value_ron:
                continue
            authority = (item.get("contractingAuthorityName") or "Autoritate Publica Locala").strip()
            cpv = item.get("cpvCode", {})
            cpv_text = cpv.get("text", "") if isinstance(cpv, dict) else str(cpv)
            source_id = self.generate_source_id(f"SEAP_DA_{direct_id}_{title}")
            new_records.append(RawRecord(
                source_id=source_id,
                category=self.category,
                county="National",
                locality="National",
                institution=authority,
                document_title=title,
                document_url=f"https://e-licitatie.ro/pub/direct-acquisition/view/{direct_id}",
                raw_metadata={
                    "estimated_value_ron": est_value,
                    "authority_name": authority,
                    "cpv_code": cpv_text,
                    "type": "Achizitie Directa Imediata"
                }
            ))
        return new_records
