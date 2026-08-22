import asyncio
import json
from typing import List
from playwright.async_api import async_playwright
from src.scrapers.base_adapter import BaseSourceAdapter
from src.database.models import RawRecord, SourceCategory, is_record_scraped

class SeapMarketConsultationAdapter(BaseSourceAdapter):
    def __init__(self, min_value_ron: float = 50000.0, page_size: int = 50):
        super().__init__(
            name="SEAP Market Consultations Live",
            category=SourceCategory.PRE_SICAP,
            poll_interval_minutes=30
        )
        self.min_value_ron = min_value_ron
        self.page_size = page_size
        self.target_url = "https://e-licitatie.ro/pub/notices/mc-notices/list/1"

    async def fetch_latest(self) -> List[RawRecord]:
        new_records: List[RawRecord] = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                captured_payloads = []

                async def handle_response(response):
                    if "GetMarketConsultationList" in response.url and response.status == 200:
                        try:
                            data = await response.json()
                            captured_payloads.append(data)
                        except Exception:
                            pass

                page.on("response", handle_response)
                await page.goto(self.target_url, wait_until="networkidle", timeout=25000)
                await browser.close()

                for payload in captured_payloads:
                    items = payload.get("items", []) or payload.get("list", [])
                    for item in items:
                        mc_id = item.get("marketConsultationId") or item.get("id")
                        title = (item.get("title") or item.get("marketConsultationTitle") or "").strip()
                        est_value = float(item.get("estimatedValue") or item.get("contractValue") or 0.0)

                        if not title or est_value < self.min_value_ron:
                            continue

                        source_id = self.generate_source_id(f"SEAP_MC_{mc_id}_{title}")
                        if is_record_scraped(source_id):
                            continue

                        authority = item.get("contractingAuthorityName") or "Autoritate Contractantă Publică"
                        new_records.append(RawRecord(
                            source_id=source_id,
                            category=self.category,
                            county="National",
                            locality="National",
                            institution=authority,
                            document_title=title,
                            document_url=f"https://e-licitatie.ro/pub/notices/mc-notices/view/{mc_id}",
                            raw_metadata={
                                "estimated_value_ron": est_value,
                                "authority_name": authority,
                                "consultation_deadline": item.get("consultationDeadline"),
                                "cpv_code": item.get("cpvCode")
                            }
                        ))
        except Exception:
            pass
        return new_records
