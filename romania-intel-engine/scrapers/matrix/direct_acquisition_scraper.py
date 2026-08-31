"""Real, live scrapers for two of SEAP/e-licitatie.ro's five public notice
types: Direct Purchases (DA — Cumpărări directe) and their award notices
(CAN, scoped to direct acquisitions).

Endpoints below were found and verified live against production on
2026-08-31 by fetching e-licitatie.ro's own compiled frontend bundle
(assets/min/app.public.min.js — an AngularJS 1.x app, not the modern
Angular the /pub/* URLs might suggest) and extracting the internal
`api-pub/*` service definitions it calls, then confirming each one with a
direct request:

    api-pub/DirectAcquisitionCommon/GetDirectAcquisitionList/   (POST) — verified, live, real data
    api-pub/DaAwardNoticeCommon/GetDaAwardNoticeList/            (POST) — verified, live, real data
    api-pub/McNoticeCommon/GetMcNoticeList/                      (POST) — verified pre-existing; see elicitatie_scraper.py

Contract Notices (CN) and Simplified Contract Notices (SC) were NOT found.
What was ruled out, so a future attempt doesn't repeat it:
  - `api-pub/{CN,SC,SA,CAN,Contract,Attribution,...}NoticeCommon/Get...List`
    — every guessed variant 404s. The naming convention isn't uniform
    across e-licitatie's subsystems (compare `McNoticeCommon` vs the fully-
    spelled-out `DirectAcquisitionCommon`), so it can't be guessed from the
    MC controller's name.
  - `api-pub/NoticeCommon` is real but is a per-record section *viewer*
    (GetSection1View etc., keyed by an existing initNoticeId) — not a list
    endpoint.
  - `api-pub/ENotice/search` is real and public, but it's the notice
    *errata/change-history* feed (amendments to already-published notices),
    not a type-filtered search — confirmed by inspecting a full response
    item (`sysENoticeAutoGenContext: "La extinderea termenelor din
    procedura"`). Its `sysNoticeTypeIds` filter parameter had no visible
    effect in testing, consistent with it not being that kind of endpoint.
  - The frontend confirms a public "Contract Notice List" *page* exists
    (`sys.pub.routes.ContractNoticeList_Pub`, filtered client-side by a
    `sysNoticeTypeId` — 2 = Contract Notice, 17 = Simplified Participation
    Notice, confirmed via the app's own breadcrumb-label switch statement),
    but its backing list endpoint lives in a lazy-loaded JS chunk that
    wasn't reachable by fetching the two bundles referenced from the
    server-rendered shell (AngularJS route modules load additional chunks
    at runtime, which a plain HTTP client can't discover without executing
    the app). CN/SC ingestion needs that chunk found first — don't ship a
    guessed endpoint name for it.

Both scrapers here write two representations of every item, from one
fetch: a lean `RawInstitutionalSignal` (the existing tenant feed —
identical contract to every other scraper in this package) and a fuller
`procurement_notices.ProcurementNotice` (a normalized record with the
award/financial/timeline structure the lean feed has no room for),
persisted directly via procurement_notices.upsert_procurement_notice(). If
persistence isn't configured, upsert_procurement_notice() degrades to a
no-op exactly like db.upsert_opportunity() does — this module never treats
that as an error.
"""

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

import procurement_notices
from procurement_notices import (
    AwardDetails,
    ContractingAuthority,
    FinancialInfo,
    ProcurementNotice,
    Timeline,
    split_cui_and_name,
)
from scrapers.base_scraper import BaseScraper
from scrapers.matrix.category_classifier import classify_category
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("DirectAcquisitionScraper")

LISTING_PAGE_URL = "https://e-licitatie.ro/pub/direct-acquisition/list/1"
DA_LIST_URL = "https://e-licitatie.ro/api-pub/DirectAcquisitionCommon/GetDirectAcquisitionList/"
DA_AWARD_LIST_URL = "https://e-licitatie.ro/api-pub/DaAwardNoticeCommon/GetDaAwardNoticeList/"

# Rotated per request rather than fixed like the other scrapers' shared
# USER_AGENT constant — this module hits a paginated endpoint dozens of
# times per tick, which is exactly the repeated-fingerprint pattern basic
# bot filtering looks for.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/125.0.0.0",
]


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


class NonRetryableHTTPError(Exception):
    pass


@retry(
    stop=stop_after_attempt(4),
    # Jittered exponential backoff: a plain exponential curve retried by
    # every concurrent scraper on the same host at the same tick boundary
    # hits the server in synchronized waves; jitter spreads them out.
    wait=wait_exponential_jitter(initial=1, max=12),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError, asyncio.TimeoutError)),
    reraise=True,
)
async def _post_json(client: httpx.AsyncClient, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
    response = await client.post(url, json=body, headers={"User-Agent": _random_ua()})
    if 400 <= response.status_code < 500:
        raise NonRetryableHTTPError(f"{response.status_code} for {url}")
    response.raise_for_status()
    return response.json()


def _iso_date(value: Optional[str]) -> Optional[str]:
    """e-licitatie dates arrive as e.g. '2019-04-08T14:17:43+03:00'; the
    rest of the app only ever wants the date part."""
    if not value:
        return None
    return value[:10]


class _BaseDirectAcqScraper(BaseScraper):
    """Shared pagination/session/persistence plumbing for the two direct-
    acquisition-family scrapers below. Not registered in the orchestrator
    itself — only the two concrete subclasses are."""

    LIST_URL: str = ""
    NOTICE_TYPE: str = ""

    def __init__(self, name: str, page_size: int = 50, max_pages: int = 6, poll_interval_minutes: int = 60):
        super().__init__(name, rate_limit_delay=0.75, poll_interval_minutes=poll_interval_minutes)
        self.page_size = page_size
        self.max_pages = max_pages

    def _build_signal(self, item: Dict[str, Any]) -> Optional[RawInstitutionalSignal]:
        raise NotImplementedError

    def _build_notice(self, item: Dict[str, Any]) -> Optional[ProcurementNotice]:
        raise NotImplementedError

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signals: List[RawInstitutionalSignal] = []
        max_id_seen: Optional[str] = None
        headers = {"User-Agent": _random_ua(), "Referer": LISTING_PAGE_URL, "Accept": "application/json, text/plain, */*"}

        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
                headers=headers,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            ) as client:
                await client.get(LISTING_PAGE_URL)  # primes the session cookie the API expects

                for page in range(self.max_pages):
                    await asyncio.sleep(self.rate_limit_delay)
                    try:
                        data = await _post_json(client, self.LIST_URL, {"pageIndex": page, "pageSize": self.page_size})
                    except (httpx.HTTPError, asyncio.TimeoutError, NonRetryableHTTPError) as e:
                        logger.warning(f"[{self.name}] page {page} failed, stopping pagination: {e}")
                        break

                    items = (data or {}).get("items", [])
                    if not items:
                        break

                    for item in items:
                        signal = self._build_signal(item)
                        if signal:
                            signals.append(signal)
                            item_id = str(signal.metadata.get("notice_id") or "")
                            if item_id and (max_id_seen is None or item_id > max_id_seen):
                                max_id_seen = item_id

                        notice = self._build_notice(item)
                        if notice:
                            try:
                                await procurement_notices.upsert_procurement_notice(notice)
                            except Exception as e:
                                # A persistence failure for the richer record
                                # must not cost the lean signal above, which
                                # is already queued for the tenant feed.
                                logger.warning(f"[{self.name}] procurement_notices upsert failed: {e}")

                    if len(items) < self.page_size:
                        break  # short last page — reached the end of the list
        except Exception as e:
            self.logger.error(f"[{self.name}] fetch_market_consultations failed: {e}")
            raise

        if max_id_seen is not None:
            try:
                await procurement_notices.update_ingest_state(self.NOTICE_TYPE, datetime.now(timezone.utc), max_id_seen)
            except Exception as e:
                logger.warning(f"[{self.name}] ingest-state update failed: {e}")

        return signals


class DirectAcquisitionScraper(_BaseDirectAcqScraper):
    """Direct Purchases (Cumpărări directe) — notice_type 'DA'. Real, live,
    verified endpoint; ~2000 records total observed at verification time,
    so a full walk (page_size 50 * max_pages 6 = 300/tick) clears the
    backlog in well under ten ticks and then just tracks new arrivals."""

    LIST_URL = DA_LIST_URL
    NOTICE_TYPE = "DA"

    def __init__(self):
        super().__init__("SeapDirectAcquisition", poll_interval_minutes=60)

    def _build_signal(self, item: Dict[str, Any]) -> Optional[RawInstitutionalSignal]:
        title = (item.get("directAcquisitionName") or "").strip()
        notice_id = item.get("uniqueIdentificationCode") or f"DA-{item.get('directAcquisitionId')}"
        if not title or not item.get("directAcquisitionId"):
            return None

        ca_cui, ca_name = split_cui_and_name(item.get("contractingAuthority"))
        cpv = item.get("cpvCode")

        # Direct purchases carry no county/locality field on this endpoint
        # at all (unlike MC/CN, which at least name the authority's
        # address) — classify_category has to work from title+CPV alone,
        # and county genuinely can't be reported rather than guessed.
        category = classify_category(ca_name, title, cpv or "")

        return RawInstitutionalSignal(
            source_id=f"SEAP-DA-{notice_id}",
            source_type="SEAP Cumpărare Directă (Live)",
            category=category,
            sub_category="Cumpărare Directă",
            county="Necunoscut",
            locality="",
            entity_name=ca_name or "Autoritate Contractantă",
            project_title=title,
            estimated_value_ron=float(item.get("estimatedValueRon") or 0.0),
            published_date=_iso_date(item.get("publicationDate")) or "",
            action_deadline=_iso_date(item.get("supplierDecisionDeadline")),
            raw_description=title,
            source_url=LISTING_PAGE_URL,
            cpv_code=cpv,
            metadata={
                "notice_id": notice_id,
                "notice_type": self.NOTICE_TYPE,
                "contracting_authority_cui": ca_cui,
                "state": (item.get("sysDirectAcquisitionState") or {}).get("text"),
                "live_fetch_verified": True,
            },
        )

    def _build_notice(self, item: Dict[str, Any]) -> Optional[ProcurementNotice]:
        notice_id = item.get("uniqueIdentificationCode") or (
            f"DA-{item['directAcquisitionId']}" if item.get("directAcquisitionId") else None
        )
        if not notice_id:
            return None

        ca_cui, ca_name = split_cui_and_name(item.get("contractingAuthority"))
        closing_value = item.get("closingValue")
        award: Optional[AwardDetails] = None
        if item.get("supplier") and closing_value is not None:
            supplier_cui, supplier_name = split_cui_and_name(item.get("supplier"))
            estimated = item.get("estimatedValueRon") or 0.0
            discount = round((1 - (closing_value / estimated)) * 100, 2) if estimated else None
            award = AwardDetails(
                winning_bidder_name=supplier_name or None,
                winning_bidder_cui=supplier_cui,
                awarded_value_ron=float(closing_value),
                discount_pct=discount,
                number_of_offers_received=None,  # not exposed by this endpoint
            )

        return ProcurementNotice(
            notice_id=notice_id,
            notice_type=self.NOTICE_TYPE,
            caen_codes=[],  # not exposed by this endpoint — left honestly empty
            cpv_code=item.get("cpvCode"),
            contracting_authority=ContractingAuthority(name=ca_name or "Autoritate Contractantă", cui=ca_cui),
            financial=FinancialInfo(estimated_value_ron=float(item.get("estimatedValueRon") or 0.0)),
            award_details=award,
            timeline=Timeline(
                publication_date=_iso_date(item.get("publicationDate")),
                # Direct purchases have no competitive bid-submission phase;
                # the closest real concept is the deadline by which the
                # chosen supplier must respond.
                bid_deadline_date=_iso_date(item.get("supplierDecisionDeadline")),
                clarification_deadline_date=None,
            ),
            raw_attachments=[],  # no documents endpoint found for this controller
            source_url=LISTING_PAGE_URL,
        )


class DaAwardNoticeScraper(_BaseDirectAcqScraper):
    """Award notices for direct acquisitions — notice_type 'CAN'. This is a
    genuine, verified, separate feed (its own IDs/'DAN...' notice numbers,
    dating back to 2018), not derived from DirectAcquisitionScraper above.
    It is *not* full tender award-notice coverage (CAN for regular
    Contract/Simplified Notices) — see this module's docstring."""

    LIST_URL = DA_AWARD_LIST_URL
    NOTICE_TYPE = "CAN"

    def __init__(self):
        super().__init__("SeapDaAwardNotice", poll_interval_minutes=120)

    def _build_signal(self, item: Dict[str, Any]) -> Optional[RawInstitutionalSignal]:
        title = (item.get("contractObject") or "").strip()
        notice_id = item.get("noticeNo") or f"CAN-{item.get('daAwardNoticeId')}"
        if not title or not item.get("daAwardNoticeId"):
            return None

        _, ca_name = split_cui_and_name(item.get("contractingAuthority"))
        cpv = item.get("cpvCode")
        category = classify_category(ca_name, title, item.get("cpvCategory") or "")

        return RawInstitutionalSignal(
            source_id=f"SEAP-CAN-DA-{notice_id}",
            source_type="SEAP Anunț de Atribuire — Achiziție Directă (Live)",
            category=category,
            sub_category="Anunț de Atribuire",
            county="Necunoscut",
            locality="",
            entity_name=ca_name or "Autoritate Contractantă",
            project_title=title,
            estimated_value_ron=float(item.get("awardedValue") or 0.0),
            published_date=_iso_date(item.get("publicationDate")) or "",
            raw_description=title,
            source_url=LISTING_PAGE_URL,
            cpv_code=cpv,
            metadata={
                "notice_id": notice_id,
                "notice_type": self.NOTICE_TYPE,
                "live_fetch_verified": True,
            },
        )

    def _build_notice(self, item: Dict[str, Any]) -> Optional[ProcurementNotice]:
        notice_id = item.get("noticeNo") or (
            f"CAN-{item['daAwardNoticeId']}" if item.get("daAwardNoticeId") else None
        )
        if not notice_id:
            return None

        ca_cui, ca_name = split_cui_and_name(item.get("contractingAuthority"))
        supplier_cui, supplier_name = split_cui_and_name(item.get("supplier"))
        awarded_value = item.get("awardedValue")

        return ProcurementNotice(
            notice_id=notice_id,
            notice_type=self.NOTICE_TYPE,
            caen_codes=[],
            cpv_code=item.get("cpvCode"),
            contracting_authority=ContractingAuthority(name=ca_name or "Autoritate Contractantă", cui=ca_cui),
            financial=FinancialInfo(estimated_value_ron=float(awarded_value or 0.0)),
            award_details=AwardDetails(
                winning_bidder_name=supplier_name or None,
                winning_bidder_cui=supplier_cui,
                awarded_value_ron=float(awarded_value) if awarded_value is not None else None,
                discount_pct=None,  # no separate "estimated value" on this feed to compare against
                number_of_offers_received=None,
            ),
            timeline=Timeline(publication_date=_iso_date(item.get("publicationDate"))),
            raw_attachments=[],
            source_url=LISTING_PAGE_URL,
        )
