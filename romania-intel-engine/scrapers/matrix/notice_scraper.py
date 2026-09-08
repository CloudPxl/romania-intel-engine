"""Real, live scrapers for e-licitatie.ro's two full-tender notice types:
Contract Notices (CN, `sysNoticeTypeId` 2 — "Anunț de participare") and
Simplified Contract Notices (SC, `sysNoticeTypeId` 17 — "Anunț de
participare simplificat"). This is the gap direct_acquisition_scraper.py's
module docstring left open — that file's reconnaissance (2026-08-31) found
DA/CAN/MC but explicitly could not find CN/SC's list endpoint, because its
backing service lived in a JS chunk not reachable from the two bundles it
fetched at the time.

Endpoints below were found and verified live on 2026-09-08 by fetching
e-licitatie.ro's current consolidated public bundle (`GET /app-pub?v=...`
— a single ~830KB response; the site's build appears to have changed
since the prior session, since this one bundle already contains code that
used to live in a separately-chunked module) and extracting the internal
`api-pub/*` service definitions it calls, then confirming each one with a
direct request:

    api-pub/NoticeCommon/GetCNoticeList/         (POST) — verified, live, real data, both notice types
    api-pub/comboPub/getSysAwardCriteriaTypes/   (GET)  — verified, live, real reference enum
    api-pub/NoticeCommon/getNoticeGeneralInfo/   (GET)  — verified, live; does not carry award criterion
    api-pub/NoticeCommon/GetSection4View/        (GET)  — verified, live; does not carry it either

What was ruled out along the way, so a future attempt doesn't repeat it:
  - `api-pub/AdvNoticeCommon/GetAdvNoticeList/` looked promising by name
    (found in the same bundle, genuinely live — a naive guess would ship
    it) but its own `sysAdvertisingNoticeId` filter enum
    (`getSysAdvertisingNotices`, verified live) returns exactly three
    values — "Informare publicare la JOUE", "Anexa 2", "Achizitii
    directe" — none of which is Contract/Simplified Notice. This is a
    different SEAP-internal feature, not CN/SC.
  - `GetCNoticeList`'s own filter accepts `sysAwardCriteriaTypeId` as a
    *search* parameter, proving the field exists server-side, and
    `getSysAwardCriteriaTypes` confirms its four values (1="Pretul cel
    mai scazut", 2="Cel mai bun raport calitate-pret", 3="Costul cel mai
    scazut", 4="Cel mai bun raport calitate-cost") — but no per-notice
    endpoint returning *which one a given notice uses* was found in the
    time available. `getNoticeGeneralInfo` (linkage to the notice's DF/PI/
    CA sibling notices and a TED cross-reference number) and
    `GetSection4View` (EU Section IV "Procedure" — deadlines, whether it's
    a framework agreement/DPS, `dcAwardCriteria` which is null and
    specific to Dynamic Purchasing Systems) were both checked live against
    a real CN and neither carries it. `award_criterion` is therefore
    always `None` from this module for now — see
    `procurement_notices.ProcurementNotice.award_criterion` for where it
    belongs once the right endpoint is found. Don't assume Section
    2 (`GetSection21View`) is it either without verifying first: a bare
    call 404'd (it needs a real `lotId`, not `0`) and wasn't pursued
    further this pass.

A data-quality nuance found while verifying this, worth knowing before
trusting the list values too far: the list endpoint's
`minTenderReceiptDeadline`/`maxTenderReceiptDeadline` can be stale
relative to a notice's later amendments. One live-fetched CN
(noticeId=100159118) showed `minTenderReceiptDeadline: 2019-05-09` in the
list response but `tenderReceiptDeadline: "21.11.2022 15:00"` in its own
Section IV detail view — the procedure had clearly been extended by
several errata since its original publication. This module uses the list
value as-is (same "latest full sync wins" convention every scraper here
already uses, refreshed on every re-poll via the UPSERT) rather than a
per-notice detail fetch for every item, which would multiply this
module's request volume by the page size on every tick against a host
that has already shown aggressive rate limiting (see below).

Also verified live: `contractingAuthorityNameAndFN` uses a *different*
separator ("4374873 - SPITALUL DE URGENTA PETROSANI") than DA/CAN's
`contractingAuthority` field ("RO 6865630 DELTA PLUS TRADING S.R.L.", no
hyphen) — `procurement_notices.split_cui_and_name`'s regex was extended to
accept both rather than adding a second parser.

Rate limiting note: e-licitatie.ro's bot mitigation was observed during
this reconnaissance to silently drop connections (TCP+TLS handshake
succeeds, then no HTTP response at all for 20-45s) under rapid repeated
requests from the same client IP, recovering after a roughly 15-20s pause
— a more aggressive pattern than what DA/MC's own reconnaissance
documented. This module reuses direct_acquisition_scraper.py's
User-Agent rotation and jittered-backoff retry helper (`_post_json`,
`_random_ua`) rather than inventing a second copy of the same logic, and
keeps its own page/tick budget modest given three scrapers (DA, CAN, and
now CN+SC) now share one rate-limited host.

Same as direct_acquisition_scraper.py, both scrapers here write two
representations of every item from one fetch: a lean
`RawInstitutionalSignal` (the tenant feed) and a fuller
`procurement_notices.ProcurementNotice`. If persistence isn't configured,
persistence degrades to a no-op exactly like every other module in this
codebase.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

import procurement_notices
from procurement_notices import (
    ContractingAuthority,
    FinancialInfo,
    ProcurementNotice,
    Timeline,
    split_cui_and_name,
)
from scrapers.base_scraper import BaseScraper
from scrapers.matrix.category_classifier import classify_category
from scrapers.matrix.direct_acquisition_scraper import (
    NonRetryableHTTPError,
    _get_priming,
    _post_json,
    _random_ua,
)
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("NoticeScraper")

LISTING_PAGE_URL = "https://e-licitatie.ro/pub/notices/contract-notices/list/2/0"
CN_LIST_URL = "https://e-licitatie.ro/api-pub/NoticeCommon/GetCNoticeList/"

# Only notices published within this window are requested — the server
# genuinely applies `startPublicationDate` as a filter (confirmed live,
# and it's the same default e-licitatie.ro's own public UI applies), so
# this is a real server-side reduction of an unbounded, apparently
# unordered multi-thousand-row list, not a client-side guess. A CN/SC
# procedure's submission window can run for weeks, so this is wider than
# elicitatie_scraper.py's 14-day market-consultation lookback.
LOOKBACK_DAYS = 45

# EU Section IV "Procedure" state, read directly off sysProcedureState.id
# — a genuine SEAP enum value, not inferred from text. 2 ("In Progress")
# and 5 ("Atribuita"/Awarded) were confirmed by e-licitatie.ro's own
# frontend logic and a live awarded notice respectively; 3 ("Anulata") was
# observed directly on two live Simplified Contract Notices. Anything else
# maps to "unknown" — declaring a stage explicitly (rather than falling
# through to ai_refinery._infer_stage's text heuristic) matters here more
# than for a plain HTML scraper: a legitimate open tender's own title can
# easily contain a word like "consultanță" that would otherwise
# accidentally trigger the market-consultation heuristic.
_PROCEDURE_STATE_TO_STAGE = {2: "tender_open", 5: "awarded", 3: "cancelled"}

# sysProcedureType.text, read verbatim off real live notices (id 1 on a
# Contract Notice, id 20 on a Simplified Contract Notice) — not a guess at
# what e-licitatie.ro might call these.
_SYS_PROCEDURE_TYPE_TO_PROCEDURE_TYPE = {
    "Licitatie deschisa": "licitatie_deschisa",
    "Procedura simplificata": "procedura_simplificata",
}

_CPV_PREFIX_RE = re.compile(r"^(\d{8}-\d)\b")


def _extract_cpv_code(cpv_code_and_name: Optional[str]) -> Optional[str]:
    """`cpvCodeAndName` arrives as e.g. '33652100-6 - Antineoplazice
    (Rev.2)' — the leading 8-digit-plus-check-digit code is what
    scrapers.cpv_taxonomy and the rest of the app expect; the trailing
    Romanian description is dropped rather than kept (it duplicates
    `contractTitle`'s level of detail for a different purpose)."""
    if not cpv_code_and_name:
        return None
    match = _CPV_PREFIX_RE.match(cpv_code_and_name.strip())
    return match.group(1) if match else None


def _iso_date(value: Optional[str]) -> Optional[str]:
    """Same convention as direct_acquisition_scraper.py's helper of the
    same name: e-licitatie dates arrive as e.g.
    '2019-04-08T14:17:43+03:00'; only the date part is ever used."""
    if not value:
        return None
    return value[:10]


def _view_url(sys_notice_type_id: int, sys_notice_version_id: Optional[int], notice_id: Any) -> str:
    """e-licitatie.ro's public view route is versioned per notice format
    ('Formatul nou' vs the legacy one — sysNoticeVersionId 2 vs 1,
    confirmed against a real notice's getNoticeGeneralInfo response) and
    forked per notice family (c-notice vs simplified-notice, confirmed via
    the app's own route table). Defaults to v2 — the only version observed
    on any live notice fetched during verification — when the field is
    absent, since that is more likely correct than guessing v1."""
    kind = "c-notice" if sys_notice_type_id == 2 else "simplified-notice"
    version = "v1" if sys_notice_version_id == 1 else "v2"
    return f"https://e-licitatie.ro/pub/notices/{kind}/{version}/view/{notice_id}"


class _BaseNoticeScraper(BaseScraper):
    """Shared pagination/session/persistence plumbing for the CN and SC
    scrapers below — same shape as direct_acquisition_scraper.py's
    `_BaseDirectAcqScraper`, sharing its retry/backoff helper rather than
    duplicating it. Not registered in the orchestrator itself — only the
    two concrete subclasses are."""

    SYS_NOTICE_TYPE_ID: int = 0
    NOTICE_TYPE: str = ""
    SUB_CATEGORY: str = ""

    def __init__(self, name: str, page_size: int = 50, max_pages: int = 4, poll_interval_minutes: int = 90):
        super().__init__(name, rate_limit_delay=1.0, poll_interval_minutes=poll_interval_minutes)
        self.page_size = page_size
        self.max_pages = max_pages

    def _build_signal(self, item: Dict[str, Any]) -> Optional[RawInstitutionalSignal]:
        raise NotImplementedError

    def _build_notice(self, item: Dict[str, Any]) -> Optional[ProcurementNotice]:
        raise NotImplementedError

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signals: List[RawInstitutionalSignal] = []
        headers = {"User-Agent": _random_ua(), "Referer": LISTING_PAGE_URL, "Accept": "application/json, text/plain, */*"}
        start_date = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        try:
            async with httpx.AsyncClient(
                timeout=25.0,
                follow_redirects=True,
                headers=headers,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            ) as client:
                # Retrying, not a bare GET — see _get_priming's docstring in
                # direct_acquisition_scraper.py. Reproduced live: this exact
                # call raised ConnectTimeout during e-licitatie's bot
                # mitigation and killed ContractNoticeScraper's whole tick.
                await _get_priming(client, LISTING_PAGE_URL)

                for page in range(self.max_pages):
                    await asyncio.sleep(self.rate_limit_delay)
                    body = {
                        "sysNoticeTypeIds": [self.SYS_NOTICE_TYPE_ID],
                        "startPublicationDate": start_date,
                        "pageIndex": page,
                        "pageSize": self.page_size,
                    }
                    try:
                        data = await _post_json(client, CN_LIST_URL, body)
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
                        break  # short last page — reached the end of this window
        except Exception as e:
            self.logger.error(f"[{self.name}] fetch_market_consultations failed: {e}")
            raise

        return signals

    def _shared_fields(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Fields both _build_signal and _build_notice need, computed once
        per item rather than twice."""
        ca_cui, ca_name = split_cui_and_name(item.get("contractingAuthorityNameAndFN"))
        cpv_code = _extract_cpv_code(item.get("cpvCodeAndName"))
        sys_procedure_type = (item.get("sysProcedureType") or {}).get("text")
        procedure_type = _SYS_PROCEDURE_TYPE_TO_PROCEDURE_TYPE.get(sys_procedure_type)
        sys_procedure_state_id = (item.get("sysProcedureState") or {}).get("id")
        stage = _PROCEDURE_STATE_TO_STAGE.get(sys_procedure_state_id, "unknown")
        view_url = _view_url(self.SYS_NOTICE_TYPE_ID, item.get("sysNoticeVersionId"), item.get("noticeId"))
        return {
            "ca_cui": ca_cui,
            "ca_name": ca_name or "Autoritate Contractantă",
            "cpv_code": cpv_code,
            "procedure_type": procedure_type,
            "stage": stage,
            "view_url": view_url,
        }

    def _build_signal_common(self, item: Dict[str, Any]) -> Optional[RawInstitutionalSignal]:
        notice_id = item.get("noticeNo") or f"{self.NOTICE_TYPE}-{item.get('noticeId')}"
        title = (item.get("contractTitle") or "").strip()
        if not title or not item.get("noticeId"):
            return None

        shared = self._shared_fields(item)
        category = classify_category(shared["ca_name"], title, cpv_code=shared["cpv_code"])

        return RawInstitutionalSignal(
            source_id=f"ELICITATIE-{self.NOTICE_TYPE}-{item.get('noticeId')}",
            source_type=f"SEAP {self.SUB_CATEGORY} (Live)",
            category=category,
            sub_category=self.SUB_CATEGORY,
            # Neither CN nor SC's list endpoint reports the authority's
            # county/locality — same honest gap DA/CAN already document
            # for the same reason (not exposed by this endpoint).
            county="Necunoscut",
            locality="",
            entity_name=shared["ca_name"],
            project_title=title,
            estimated_value_ron=float(item.get("estimatedValueRon") or 0.0),
            published_date=_iso_date(item.get("noticeStateDate")) or "",
            action_deadline=_iso_date(item.get("minTenderReceiptDeadline")),
            raw_description=title,
            source_url=shared["view_url"],
            cpv_code=shared["cpv_code"],
            document_url=shared["view_url"],
            metadata={
                "notice_id": notice_id,
                "notice_type": self.NOTICE_TYPE,
                "contracting_authority_cui": shared["ca_cui"],
                "procedure_type": shared["procedure_type"],
                "procurement_stage": shared["stage"],
                "acquisition_contract_type": (item.get("sysAcquisitionContractType") or {}).get("text"),
                "has_lots": item.get("hasLots"),
                "has_appeal": item.get("hasAppeal"),
                "live_fetch_verified": True,
            },
        )

    def _build_notice_common(self, item: Dict[str, Any]) -> Optional[ProcurementNotice]:
        notice_id = item.get("noticeNo") or (f"{self.NOTICE_TYPE}-{item['noticeId']}" if item.get("noticeId") else None)
        if not notice_id:
            return None

        shared = self._shared_fields(item)
        return ProcurementNotice(
            notice_id=notice_id,
            notice_type=self.NOTICE_TYPE,
            caen_codes=[],  # not exposed by this endpoint — left honestly empty, same as DA/CAN
            cpv_code=shared["cpv_code"],
            award_criterion=None,  # see this module's docstring for what was and wasn't found
            contracting_authority=ContractingAuthority(name=shared["ca_name"], cui=shared["ca_cui"]),
            financial=FinancialInfo(estimated_value_ron=float(item.get("estimatedValueRon") or 0.0)),
            # None even when procurement_stage is "awarded": this endpoint
            # only reports sysProcedureState (that the procedure concluded
            # in an award), never a genuine post-award value. Populating
            # awarded_value_ron from estimatedValueRon here would silently
            # present the original estimate as a confirmed outcome — the
            # same shape of mistake self-caught earlier in this project
            # (an estimate==awarded assumption that would have reported a
            # fabricated 0% median discount). getNoticeGeneralInfo does
            # expose a linked `caNoticeId`/`caNoticeNumber` (the real award
            # notice), but this pass doesn't follow it — the genuine
            # awarded value belongs to a real CAN notice, not this one.
            award_details=None,
            timeline=Timeline(
                publication_date=_iso_date(item.get("noticeStateDate")),
                bid_deadline_date=_iso_date(item.get("minTenderReceiptDeadline")),
                clarification_deadline_date=None,
            ),
            raw_attachments=[],  # no documents endpoint explored this pass
            source_url=shared["view_url"],
        )


class ContractNoticeScraper(_BaseNoticeScraper):
    """Contract Notices (Anunțuri de Participare) — notice_type 'CN',
    sysNoticeTypeId 2, e-licitatie.ro's `sysProcedureType` "Licitatie
    deschisa". Real, live, verified endpoint; ~3000 total records observed
    (server reports the count capped/rounded, per `searchTooLong`), scoped
    to the last LOOKBACK_DAYS days by the server's own publication-date
    filter rather than paginated through the unbounded full history."""

    SYS_NOTICE_TYPE_ID = 2
    NOTICE_TYPE = "CN"
    SUB_CATEGORY = "Anunț de Participare"

    def __init__(self):
        super().__init__("SeapContractNotice")

    def _build_signal(self, item: Dict[str, Any]) -> Optional[RawInstitutionalSignal]:
        return self._build_signal_common(item)

    def _build_notice(self, item: Dict[str, Any]) -> Optional[ProcurementNotice]:
        return self._build_notice_common(item)


class SimplifiedContractNoticeScraper(_BaseNoticeScraper):
    """Simplified Contract Notices (Anunțuri de Participare Simplificate)
    — notice_type 'SC', sysNoticeTypeId 17, e-licitatie.ro's
    `sysProcedureType` "Procedura simplificata". Same verified endpoint as
    ContractNoticeScraper, filtered to the other notice-type id."""

    SYS_NOTICE_TYPE_ID = 17
    NOTICE_TYPE = "SC"
    SUB_CATEGORY = "Anunț de Participare Simplificat"

    def __init__(self):
        super().__init__("SeapSimplifiedContractNotice")

    def _build_signal(self, item: Dict[str, Any]) -> Optional[RawInstitutionalSignal]:
        return self._build_signal_common(item)

    def _build_notice(self, item: Dict[str, Any]) -> Optional[ProcurementNotice]:
        return self._build_notice_common(item)
