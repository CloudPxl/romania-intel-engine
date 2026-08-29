"""Shared access to CNI's project register.

CNI (Compania Nationala de Investitii) is the national investment company
that builds both health facilities and general public works, so it feeds
two domains at once. Both read the same DataTables JSON endpoint
(https://www.cni.ro/ajaxProj.php, reverse-engineered from the inline
`ajax:` config on https://www.cni.ro/proiecte-in-achizitie), so this
module holds the fetch/parse logic once and adds a short-lived shared
cache: within a single orchestrator tick the infra and health scrapers
reuse one HTTP fetch instead of pulling several thousand rows twice.

Categories are partitioned, not overlapped: a project belongs to exactly
one domain. If both scrapers could emit the same project, they'd write the
same source_id with different `category` values and the DB upsert would
flip that column back and forth on every tick.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import List, Optional

from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("CniRegister")

AJAX_URL = "https://www.cni.ro/ajaxProj.php"
LISTING_URL = "https://www.cni.ro/proiecte-in-achizitie"

# Statuses worth surfacing as opportunities. Measured against the live
# register (15,308 rows): "In achizitie" 173, "Indicatori Aprobati" 188,
# "Analiza Documentatie" 24. The two pre-tender stages are deliberately
# included — a project whose technical-economic indicators were just
# approved is the earliest actionable signal there is, ahead of the tender
# notice, which is exactly the lead a consultancy wants.
#
# Excluded: "Finalizate" (3080, done), "In derulare" (1150, already
# awarded and under execution), "Contract Reziliat" (67, terminated), and
# "Lista sinteza" (10,623) — a long-range planning inventory too noisy and
# too far from procurement to alert on.
ACTIONABLE_STATUSES = frozenset({
    "In achizitie",
    "Indicatori Aprobati",
    "Analiza Documentatie",
})

# Maps CNI's status onto where the project sits in the procurement funnel,
# so downstream scoring/matching can weight a pre-tender lead differently
# from one already out to bid.
STAGE_BY_STATUS = {
    "Indicatori Aprobati": "pre_tender_approved_indicators",
    "Analiza Documentatie": "pre_tender_documentation_review",
    "In achizitie": "in_procurement",
}

# The register's category column, partitioned by domain. Health takes the
# sanitary-units category; every other category is public-works/infra.
HEALTH_CATEGORIES = frozenset({"Unitati sanitare*"})

# The register is ~15.3k rows / ~2.4MB in one response. It's pulled in
# pages so a single slow response can't blow the request timeout, and the
# loop stops on the first short page rather than trusting recordsTotal
# (which the endpoint always reports as 0).
PAGE_SIZE = 5000
MAX_PAGES = 12
FETCH_TIMEOUT_SECONDS = 60.0

_ID_RE = re.compile(r"-id-(\d+)-cmsid-\d+")
_LINK_RE = re.compile(r'href="([^"]+)"')

# The endpoint reports recordsTotal/recordsFiltered as 0 regardless of the
# real result count (a server-side bug), so pagination stops on a short
# page rather than trusting those fields.
_CACHE_TTL_SECONDS = 240
_cache_rows: Optional[List[list]] = None
_cache_at: float = 0.0
_cache_lock = asyncio.Lock()


def parse_ron(value: str) -> float:
    """CNI formats money as '9.844.025,00 lei' (RO thousands/decimal)."""
    try:
        cleaned = value.replace("lei", "").strip().replace(".", "").replace(",", ".")
        return float(cleaned)
    except (ValueError, AttributeError):
        return 0.0


class CniRegisterScraper(BaseScraper):
    """Base for the per-domain CNI scrapers. Subclasses declare which
    register categories they own and which domain label to emit."""

    DOMAIN_CATEGORY = "infrastructura"

    def accepts_category(self, category: str) -> bool:
        raise NotImplementedError

    async def _fetch_all_rows(self) -> List[list]:
        global _cache_rows, _cache_at
        async with _cache_lock:
            if _cache_rows is not None and (time.monotonic() - _cache_at) < _CACHE_TTL_SECONDS:
                return _cache_rows

            rows: List[list] = []
            for page in range(MAX_PAGES):
                url = f"{AJAX_URL}?draw=1&start={page * PAGE_SIZE}&length={PAGE_SIZE}"
                body = await self.fetch_url(url, timeout=FETCH_TIMEOUT_SECONDS)
                if not body:
                    break
                try:
                    page_rows = json.loads(body).get("data", [])
                except json.JSONDecodeError:
                    self.logger.error(f"[{self.name}] non-JSON response from {url}")
                    break
                rows.extend(page_rows)
                if len(page_rows) < PAGE_SIZE:
                    break

            # Only cache a non-empty read; caching a failed fetch would
            # suppress retries for the rest of the TTL window.
            if rows:
                _cache_rows, _cache_at = rows, time.monotonic()
            return rows

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signals: List[RawInstitutionalSignal] = []
        for row in await self._fetch_all_rows():
            if len(row) < 8:
                continue
            year, category, county, locality, title, budget_str, status, link_html = row[:8]
            if status not in ACTIONABLE_STATUSES or not self.accepts_category(category):
                continue

            link_match = _LINK_RE.search(link_html or "")
            detail_url = link_match.group(1).replace("\\/", "/") if link_match else LISTING_URL
            id_match = _ID_RE.search(detail_url)
            source_id = (
                f"CNI-{id_match.group(1)}"
                if id_match
                else f"CNI-{hashlib.sha1(f'{year}|{category}|{county}|{locality}|{title}'.encode()).hexdigest()[:16]}"
            )

            signals.append(RawInstitutionalSignal(
                source_id=source_id,
                source_type="CNI Registru Proiecte",
                category=self.DOMAIN_CATEGORY,
                sub_category=category or "Nespecificat",
                county=county or "",
                locality=locality or "",
                entity_name="Compania Nationala de Investitii (CNI)",
                project_title=title or "Proiect CNI",
                estimated_value_ron=parse_ron(budget_str),
                # The register gives a reporting year only, never a day or
                # month — left as the bare year rather than inventing one;
                # db._parse_date() stores an unparseable value as NULL.
                published_date=str(year) if year else "",
                raw_description=(
                    f"Proiect CNI in categoria '{category}', judetul {county}, "
                    f"stadiu: {status}. Obiectiv: {title}."
                ),
                source_url=detail_url,
                metadata={
                    "reported_year": year,
                    "cni_status": status,
                    "procurement_stage": STAGE_BY_STATUS.get(status, "unknown"),
                },
            ))
        return signals
