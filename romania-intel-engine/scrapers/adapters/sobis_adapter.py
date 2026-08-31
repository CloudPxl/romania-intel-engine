"""Adapter for Sobis Public Administration Suite — a CMS family used by a
number of Romanian county councils and city halls, identifiable by a
public JSON API under /api/public/ (unlike Indeco Soft's server-rendered
ASP.NET pages) or, on older/customized deployments, a JS-rendered SPA that
still ships the same procurement data as a plain HTML table.

Field names inside the JSON payload are not standardized across
deployments (confirmed indirectly: this is a licensed product customized
per client, the way Indeco Soft's own table layout also varies) — this
adapter reads several plausible Romanian field-name variants per logical
field (`_first_key`) rather than assuming one fixed schema, the same
principle indeco_adapter.py applies to column headers. Where the JSON API
isn't reachable (a customization that removed it, or a deployment old
enough to predate it), it falls back to parsing a rendered HTML listing
page with the same regex-based value/date/CPV extraction the rest of this
matrix already uses (see municipal_scrapers.py's `_parse_ro_value`).

Live reconnaissance found zero confirmed deployments of this JSON-API
platform among the 41 county councils. The two counties whose homepage
HTML contained the string "Sobis" (Caraș-Severin, Dolj) turned out, on
closer inspection, to be running "Sobis" as a CSS theme/skin name
(`site.sobis.ro.js`, `sobis.citygov.css`) applied on top of an unrelated
platform — a genuine IBM/HCL Domino ".nsf" portal (confirmed live: real
paths like `/dm_cjcs/portal.nsf/pagini/achizitii+publice-...` and
`/dm_dolj/site.nsf/atasament/...`), the same underlying platform as this
codebase's existing `scrapers/matrix/infra_scrapers.py:CountyHclScraper`
(Iași, `dm_iasi/portal.nsf`). Both are registered in
county_registries.json as `platform: "domino_nsf"` (no adapter) rather
than "sobis" — this adapter's JSON-API-first strategy doesn't match a
Domino site's `.nsf?OpenView`/`.nsf/pagini/` URL convention at all, so
routing them here would silently return 0 while claiming coverage.
A same-pass homepage sweep for a bare ".nsf" substring also caught 3 more
counties (Bacău, Brăila, Sălaj) running the same Domino platform under
a plain-looking domain, suggesting it's a materially larger bucket among
the "generic_html" counties than this one pass had time to fully map —
a DominoNsfAdapter generalizing the existing Iași scraper (rather than a
Sobis-shaped one) is the highest-value next adapter to build here, not a
fix to this class. This class stays as real, working infrastructure for
whatever genuine Sobis JSON-API deployment turns up among the broader
UAT/city-hall universe the spec also names.
"""

import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.adapters.base_adapter import BaseCMSAdapter
from text_utils import matching_terms

ANUNTURI_API_PATH = "/api/public/anunturi"
HOTARARI_API_PATH = "/api/public/hotarari"
ANUNTURI_PAGE_PATH = "/achizitii-publice/anunturi/"
HOTARARI_PAGE_PATH = "/monitorul-oficial-local/hotarari/"

_VALUE_RE = re.compile(r"([\d][\d.,]{2,})\s*lei", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b|\b(\d{2}[./]\d{2}[./]\d{4})\b")
_CPV_RE = re.compile(r"\b(\d{8}-\d)\b")

TITLE_KEYS = ["titlu", "denumire", "title", "obiect", "denumireAchizitie"]
VALUE_KEYS = ["valoareEstimata", "valoare_estimata", "valoare", "valoareRon", "estimatedValue"]
PUBLISHED_KEYS = ["dataPublicarii", "data_publicarii", "dataPublicare", "publishedAt", "data"]
DEADLINE_KEYS = ["dataLimita", "data_limita", "termenLimita", "deadline"]
CPV_KEYS = ["cpv", "codCpv", "cod_cpv", "cpvCode"]
ID_KEYS = ["id", "idAnunt", "nrInregistrare", "numar"]
URL_KEYS = ["url", "link", "documentUrl", "fisier"]


def _first_key(item: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _parse_ro_value(text: str) -> float:
    match = _VALUE_RE.search(text)
    if not match:
        return 0.0
    raw = match.group(1).strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _normalize_date(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    match = _DATE_RE.search(text)
    if not match:
        return ""
    iso, dotted = match.groups()
    if iso:
        return iso
    try:
        return datetime.strptime(dotted.replace("/", "."), "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


class SobisAdapter(BaseCMSAdapter):
    platform_name = "sobis"

    def __init__(self):
        super().__init__(rate_limit_delay=1.0)

    async def detect(self, base_url: str, client) -> bool:
        response = await self._get(client, urljoin(base_url, ANUNTURI_API_PATH))
        if response is not None:
            try:
                json.loads(response.text)
                return True
            except json.JSONDecodeError:
                pass
        homepage = await self._get(client, base_url)
        return homepage is not None and "sobis" in homepage.text.lower()

    async def _fetch_json_items(self, client, url: str) -> Optional[List[Dict[str, Any]]]:
        response = await self._get(client, url)
        if response is None:
            return None
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("items", "data", "results", "anunturi", "hotarari"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        return None

    def _item_to_notice(
        self, item: Dict[str, Any], county: str, source_type: str, source_prefix: str,
        listing_url: str, fallback_index: int,
    ) -> Optional[Dict[str, Any]]:
        title = str(_first_key(item, TITLE_KEYS) or "").strip()
        if not title:
            return None
        raw_id = _first_key(item, ID_KEYS) or fallback_index
        doc_url = _first_key(item, URL_KEYS)
        return {
            "source_id": f"{source_prefix}-{county.upper()}-{raw_id}",
            "source_type": source_type,
            "county": county,
            "locality": county,
            "entity_name": f"Consiliul Județean {county}",
            "project_title": title,
            "financial_value_ron": _parse_ro_value(f"{_first_key(item, VALUE_KEYS) or ''} lei") or _parse_ro_value(str(item)),
            "published_date": _normalize_date(_first_key(item, PUBLISHED_KEYS)),
            "action_deadline": _normalize_date(_first_key(item, DEADLINE_KEYS)) or None,
            "source_url": doc_url or listing_url,
            "raw_text": json.dumps(item, ensure_ascii=False)[:1500],
            "document_url": doc_url,
            "cpv_code": _first_key(item, CPV_KEYS),
        }

    async def _extract_html_fallback(
        self, client, page_url: str, county: str, source_type: str, source_prefix: str,
    ) -> List[Dict[str, Any]]:
        response = await self._get(client, page_url)
        if response is None:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        containers = soup.select("table tr") or soup.select(".anunt, .list-item, li")
        notices: List[Dict[str, Any]] = []
        for idx, el in enumerate(containers):
            text = el.get_text(" ", strip=True)
            if len(text) < 10:
                continue
            link = el.find("a", href=True)
            cpv_match = _CPV_RE.search(text)
            notices.append({
                "source_id": f"{source_prefix}-{county.upper()}-HTML{idx}",
                "source_type": source_type,
                "county": county,
                "locality": county,
                "entity_name": f"Consiliul Județean {county}",
                "project_title": text[:200],
                "financial_value_ron": _parse_ro_value(text),
                "published_date": _normalize_date(text),
                "action_deadline": None,
                "source_url": urljoin(page_url, link["href"]) if link else page_url,
                "raw_text": text[:1500],
                "document_url": urljoin(page_url, link["href"]) if link and link["href"].lower().endswith(".pdf") else None,
                "cpv_code": cpv_match.group(1) if cpv_match else None,
            })
        return notices

    async def extract_procurement_notices(self, base_url: str, county: str, days_back: int) -> List[Dict[str, Any]]:
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        async with self._new_client() as client:
            items = await self._fetch_json_items(client, urljoin(base_url, ANUNTURI_API_PATH))
            if items is not None:
                notices = [
                    n for i, item in enumerate(items)
                    if (n := self._item_to_notice(item, county, "PAAP_LOCAL", "SBS-PAAP", urljoin(base_url, ANUNTURI_PAGE_PATH), i)) is not None
                ]
                return [n for n in notices if not n["published_date"] or n["published_date"] >= cutoff]
            return await self._extract_html_fallback(
                client, urljoin(base_url, ANUNTURI_PAGE_PATH), county, "PAAP_LOCAL", "SBS-PAAP",
            )

    async def extract_hcl_decisions(self, base_url: str, county: str, keywords: List[str]) -> List[Dict[str, Any]]:
        async with self._new_client() as client:
            items = await self._fetch_json_items(client, urljoin(base_url, HOTARARI_API_PATH))
            if items is not None:
                notices = [
                    n for i, item in enumerate(items)
                    if (n := self._item_to_notice(item, county, "HCL_LOCAL", "SBS-HCL", urljoin(base_url, HOTARARI_PAGE_PATH), i)) is not None
                ]
            else:
                notices = await self._extract_html_fallback(
                    client, urljoin(base_url, HOTARARI_PAGE_PATH), county, "HCL_LOCAL", "SBS-HCL",
                )
        if not keywords:
            return notices
        return [n for n in notices if matching_terms(n["project_title"], keywords)]
