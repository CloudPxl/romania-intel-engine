import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from scrapers.base_scraper import BaseScraper, USER_AGENT
from scrapers.models import RawInstitutionalSignal
from scrapers.document_enricher import extract_caen_codes_from_documents

logger = logging.getLogger("ElicitatieLiveScraper")

LISTING_PAGE_URL = "https://e-licitatie.ro/pub/mc-notices/list/1"
LIST_API_URL = "https://e-licitatie.ro/api-pub/McNoticeCommon/GetMcNoticeList/"
DETAIL_API_URL = "https://e-licitatie.ro/api-pub/PUBLICMCNotice/getView/"
DOCUMENTS_API_URL = "https://e-licitatie.ro/api-pub/PUBLICMCNotice/getDocuments/{id}"
DOWNLOAD_API_URL = "https://e-licitatie.ro/api-pub/PUBLICMCNotice/downloadDocument/"
DETAIL_VIEW_URL = "https://e-licitatie.ro/pub/notices/mc-notice/view/{id}"

# Domain classification is shared with the other general-purpose feeds
# (see scrapers/matrix/category_classifier.py) so a hospital tender lands
# in "sanatate" whether it arrives from SICAP or a municipal mirror. The
# local copy that used to live here did raw substring matching and had to
# spell every keyword twice to cope with diacritics.
from scrapers.matrix.category_classifier import CATEGORY_KEYWORDS, DEFAULT_CATEGORY, classify_category  # noqa: F401


class ElicitatieLiveScraper(BaseScraper):
    """Real SICAP/e-licitatie market-consultation scraper. Replicates the
    site's own internal JSON API via plain httpx (no runtime browser) —
    contract verified manually against the live site:
      1. GET the listing page to pick up a session cookie
      2. POST GetMcNoticeList for the recent notices
      3. GET PUBLICMCNotice/getView for county/description per notice
      4. POST PUBLICMCNotice/getDocuments + downloadDocument for CAEN mining

    Note: market-consultation notices genuinely carry no CPV code or
    estimated value in e-licitatie's API (that's published later, at the
    formal tender stage) — those fields are honestly left empty/zero here
    rather than fabricated."""

    def __init__(self, lookback_days: int = 14, page_size: int = 20):
        super().__init__("ElicitatieLive", rate_limit_delay=1.0, poll_interval_minutes=10)
        self.lookback_days = lookback_days
        self.page_size = page_size

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        headers = {"User-Agent": USER_AGENT, "Referer": LISTING_PAGE_URL, "Accept": "application/json, text/plain, */*"}
        signals: List[RawInstitutionalSignal] = []
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
                await client.get(LISTING_PAGE_URL)  # picks up the session cookie the API requires

                start = (datetime.now(timezone.utc) - timedelta(days=self.lookback_days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                list_resp = await client.post(LIST_API_URL, json={
                    "pageSize": self.page_size, "publicationDateStart": start, "pageIndex": 0,
                })
                list_resp.raise_for_status()
                items = list_resp.json().get("items", [])

                for item in items:
                    signal = await self._build_signal(client, item)
                    if signal:
                        signals.append(signal)
        except Exception as e:
            self.logger.error(f"[{self.name}] fetch_market_consultations failed: {e}")
            raise
        return signals

    async def _build_signal(self, client: httpx.AsyncClient, item: Dict[str, Any]) -> Optional[RawInstitutionalSignal]:
        mc_id = item.get("mcNoticeId")
        title = (item.get("consultingObject") or "").strip()
        if not mc_id or not title:
            return None

        detail = {}
        try:
            detail_resp = await client.get(DETAIL_API_URL, params={"id": mc_id})
            detail_resp.raise_for_status()
            detail = detail_resp.json()
        except Exception as e:
            self.logger.warning(f"[{self.name}] detail fetch failed for mcNoticeId={mc_id}: {e}")

        address = detail.get("address", {}) or {}
        county = (address.get("county") or {}).get("text") or "Necunoscut"
        locality = address.get("city") or ""
        entity_name = address.get("officialName") or item.get("contractingAuthority") or "Autoritate Contractantă"
        description = detail.get("consultingDescription") or detail.get("consultingIssues") or title

        caen_codes: List[str] = []
        try:
            docs_resp = await client.post(DOCUMENTS_API_URL.format(id=mc_id), json={"pageIndex": 0, "pageSize": 10})
            docs_resp.raise_for_status()
            documents = (docs_resp.json().get("result") or {}).get("items", [])
            if documents:
                caen_codes = await extract_caen_codes_from_documents(
                    client, documents,
                    lambda doc_id: ("POST", f"{DOWNLOAD_API_URL}?id={mc_id}&documentId={doc_id}"),
                )
        except Exception as e:
            self.logger.warning(f"[{self.name}] document enrichment failed for mcNoticeId={mc_id}: {e}")

        category = classify_category(entity_name, title, description)
        view_url = DETAIL_VIEW_URL.format(id=mc_id)

        return RawInstitutionalSignal(
            source_id=f"ELICITATIE-MC-{mc_id}",
            source_type="SEAP Consultare de Piață (Live)",
            category=category,
            sub_category="Consultare de Piață",
            county=county,
            locality=locality,
            entity_name=entity_name,
            project_title=title,
            estimated_value_ron=0.0,  # genuinely not published at the MC stage
            published_date=(item.get("publicationDate") or "")[:10],
            action_deadline=(detail.get("consultingDeadline") or item.get("consultingDeadline") or "")[:10] or None,
            raw_description=description,
            source_url=view_url,
            caen_codes=caen_codes,
            cpv_code=None,  # not published at the MC stage either
            document_url=view_url,
            metadata={"notice_no": item.get("noticeNo"), "live_fetch_verified": True},
        )
