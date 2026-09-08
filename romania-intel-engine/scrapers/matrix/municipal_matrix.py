"""Bridges the CMS adapter framework (scrapers/adapters/) into the
orchestrator as a single BaseScraper, driven by
scrapers/config/county_registries.json.

This is deliberately ONE scraper source, not 41 — the registry can list
up to 41 counties x 2 fetches (procurement + HCL) each, run under a
bounded asyncio.Semaphore(15) so a slow or hanging portal can't starve the
others (a per-county circuit breaker/is_source_due entry for each of 41
counties would also considerably outgrow the matrix's current shape,
which tracks failures per logical source, not per site). A county whose
adapter raises is logged and skipped — one bad portal degrades that one
county's contribution to zero rather than failing the whole tick, the
same tolerance CniRegisterScraper and the other multi-row sources in this
matrix already have for a single malformed row.

Only registry entries with a platform this module has an adapter for are
polled ("indeco", "sobis", "generic_html", "wordpress" — the last two
both route to GenericPortalAdapter, see _ADAPTERS below). Entries labeled
"sharepoint" or "domino_nsf" are recognized-but-unadapted platforms found
during live reconnaissance (see county_registries.json's per-entry
detection_evidence) — skipped for the same reason "unreachable" is:
polling them with an adapter built for a different platform's shape would
silently return 0 while implying coverage that isn't real yet. A
genuinely offline county government site also isn't going to start
responding because we asked again in 12 hours, and the circuit-breaker
mechanism this codebase uses elsewhere is scoped to whole scrapers, not
to individual rows inside one.

MunicipalNoticeDict -> RawInstitutionalSignal mapping happens here (not
in the adapters) because domain classification (category_classifier) and
this app's specific field names are a product concern, not something a
reusable adapter should know about — see base_adapter.py's docstring.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List

from scrapers.adapters.base_adapter import BaseCMSAdapter
from scrapers.adapters.generic_portal_adapter import GenericPortalAdapter
from scrapers.adapters.indeco_adapter import IndecoAdapter
from scrapers.adapters.sobis_adapter import SobisAdapter
from scrapers.base_scraper import BaseScraper
from scrapers.matrix.category_classifier import classify_with_evidence
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("MunicipalMatrix")

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "county_registries.json")

# Investment/procurement-relevant council-resolution keywords, same intent
# as TimisoaraHclScraper.RELEVANT_RE (municipal_scrapers.py) but as a
# matching_terms() list so it works across every adapter uniformly.
HCL_RELEVANT_KEYWORDS = [
    "indicatori tehnico-economic", "studiu de fezabilitate", "deviz general",
    "modernizare", "reabilitare", "construire", "extindere", "consolidare",
    "achizitie", "achizitii", "licitatie", "contract de lucrari",
    "contract de furnizare", "contract de servicii", "proiect tehnic",
    "infrastructura", "investitie", "investitii", "finantare nerambursabila",
]

PROCUREMENT_DAYS_BACK = 60
MAX_CONCURRENT_COUNTIES = 15

# Per-county wall-clock budget for BOTH adapter calls together.
#
# The semaphore alone bounds concurrency, not duration: without this, a
# county portal that accepts the TCP connection and then never answers holds
# its slot forever and `gather` below never returns. Measured live across
# all 35 registered counties: 25 complete (slowest 32.6s) and 10 hang
# indefinitely, so the fan-out never finished at all — it was cancelled by
# TICK_DEADLINE_SECONDS (200s) on every single tick and this source
# contributed ZERO signals despite 25 counties being perfectly healthy.
# With this bound the same run yields ~718 signals in ~60s.
#
# 45s sits comfortably above the slowest real county (32.6s) while keeping
# the worst case — ceil(35/15) = 3 waves — inside the tick deadline.
COUNTY_FETCH_TIMEOUT_SECONDS = float(os.getenv("COUNTY_FETCH_TIMEOUT_SECONDS", "45"))

_generic_adapter = GenericPortalAdapter()

# "wordpress" is a registry-level detection label (see
# county_registries.json's detection_evidence), not a separate adapter
# class — GenericPortalAdapter already tries the WP REST API first before
# falling back to raw HTML, so both labels route to the same instance.
_ADAPTERS: Dict[str, BaseCMSAdapter] = {
    "indeco": IndecoAdapter(),
    "sobis": SobisAdapter(),
    "generic_html": _generic_adapter,
    "wordpress": _generic_adapter,
}


def _load_registry() -> List[Dict[str, Any]]:
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("counties", [])
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"[MunicipalMatrix] failed to load {REGISTRY_PATH}: {e}")
        return []


def _notice_to_signal(notice: Dict[str, Any], source_prefix_hint: str) -> RawInstitutionalSignal:
    category, evidence = classify_with_evidence(notice["entity_name"], notice["project_title"], notice.get("raw_text", ""))
    return RawInstitutionalSignal(
        source_id=notice["source_id"],
        source_type=notice["source_type"],
        category=category,
        sub_category=notice["source_type"].replace("_", " ").title(),
        county=notice["county"],
        locality=notice["locality"],
        entity_name=notice["entity_name"],
        project_title=notice["project_title"],
        estimated_value_ron=notice.get("financial_value_ron", 0.0),
        published_date=notice.get("published_date") or "",
        action_deadline=notice.get("action_deadline"),
        raw_description=notice.get("raw_text") or notice["project_title"],
        source_url=notice["source_url"],
        cpv_code=notice.get("cpv_code"),
        document_url=notice.get("document_url"),
        metadata={
            "classification_evidence": evidence,
            "registry_platform": source_prefix_hint,
        },
    )


class CountyRegistryScraper(BaseScraper):
    """One source in the orchestrator's matrix, internally fanning out
    across every county in county_registries.json whose platform has a
    registered adapter."""

    def __init__(self):
        # 720 -> 1440 (12h -> 24h): the single heaviest scraper in the
        # matrix by measured wall-clock cost (a live audit clocked 65-100s
        # to fan out across up to 35 counties) and, per-county, largely
        # extracting HCL decisions and PAAP-adjacent notices — content that
        # genuinely does not change within a 12h window (a county council
        # meets at most a few times a month). Kept at the low end of a
        # 24-72h "institutional strategy document" band rather than the
        # top, since it also carries live procurement notices per county
        # alongside HCLs, not purely archival content. Also the reason it
        # carries an elevated SCRAPER_EXECUTION_WEIGHT in orchestrator.py —
        # halving its polling frequency and bounding its concurrent
        # admission are complementary, not redundant.
        super().__init__("CountyRegistryMatrix", poll_interval_minutes=1440)

    async def _fetch_county(self, semaphore: asyncio.Semaphore, entry: Dict[str, Any]) -> List[RawInstitutionalSignal]:
        platform = entry.get("platform")
        adapter = _ADAPTERS.get(platform)
        if adapter is None:
            return []

        # .get(), not [] — these two reads sat OUTSIDE the try below, so a
        # registry entry missing either key raised KeyError before any
        # isolation applied, and `gather` (see below) propagated it,
        # discarding all 40 other counties' already-fetched signals. One
        # typo in a 41-entry JSON file killed the whole source.
        county = entry.get("county")
        base_url = entry.get("base_url")
        if not county or not base_url:
            self.logger.warning(f"[{self.name}] Registry entry missing county/base_url — skipped: {entry!r:.120}")
            return []
        signals: List[RawInstitutionalSignal] = []

        # Closes over `signals`, so whatever a county produced before the
        # budget ran out survives the cancellation instead of being thrown
        # away with the coroutine — the same partial-coverage posture
        # fetch_market_consultations takes for a county that raises.
        async def _collect() -> None:
            try:
                notices = await adapter.extract_procurement_notices(base_url, county, PROCUREMENT_DAYS_BACK)
                signals.extend(_notice_to_signal(n, platform) for n in notices)
            except Exception as e:
                self.logger.error(f"[{self.name}] procurement extraction failed for {county} ({platform}): {e}")

            try:
                notices = await adapter.extract_hcl_decisions(base_url, county, HCL_RELEVANT_KEYWORDS)
                signals.extend(_notice_to_signal(n, platform) for n in notices)
            except Exception as e:
                self.logger.error(f"[{self.name}] HCL extraction failed for {county} ({platform}): {e}")

        # Inside the semaphore, so a hung county releases its slot on
        # timeout; wrapping the acquire instead would spend the budget
        # queueing behind healthy counties.
        async with semaphore:
            try:
                await asyncio.wait_for(_collect(), timeout=COUNTY_FETCH_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"[{self.name}] {county} ({platform}) exceeded "
                    f"{COUNTY_FETCH_TIMEOUT_SECONDS:.0f}s and was abandoned; "
                    f"keeping {len(signals)} partial signal(s)."
                )
        return signals

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        registry = _load_registry()
        active_entries = [e for e in registry if e.get("platform") in _ADAPTERS]
        skipped = len(registry) - len(active_entries)
        if skipped:
            self.logger.info(f"[{self.name}] {skipped}/{len(registry)} registry entries skipped (unreachable/no adapter)")

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_COUNTIES)
        # return_exceptions=True: without it, one county raising takes down
        # the whole fan-out and loses every other county's results. Partial
        # coverage is the honest outcome here — the same posture
        # _run_one_scraper takes for a whole source.
        results = await asyncio.gather(
            *(self._fetch_county(semaphore, e) for e in active_entries),
            return_exceptions=True,
        )

        signals: List[RawInstitutionalSignal] = []
        failed = 0
        for county_signals in results:
            if isinstance(county_signals, BaseException):
                failed += 1
                self.logger.error(f"[{self.name}] County fetch failed: {county_signals}")
                continue
            signals.extend(county_signals)
        if failed:
            self.logger.warning(f"[{self.name}] {failed}/{len(active_entries)} counties failed; returning the rest.")
        return signals
