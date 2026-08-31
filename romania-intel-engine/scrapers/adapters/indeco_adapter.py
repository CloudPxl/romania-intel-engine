"""Adapter for Indeco Soft's municipal CMS (e-administratie / Monitorul
Oficial Local) — the standard ASP.NET WebForms platform behind
`/monitorul-oficial-local/` (council resolutions, mayoral dispositions)
and `/achizitii-publice/` (procurement plans, notices) on a large share of
Romanian city-hall and county-council sites.

Detection and extraction below target the standard ASP.NET WebForms
GridView + postback-pagination shape this platform family is built on
(`__VIEWSTATE`/`__VIEWSTATEGENERATOR`/`__EVENTVALIDATION` hidden fields,
`javascript:__doPostBack('<target>','<argument>')` paging links) — this is
a well-documented, standardized ASP.NET mechanism, not something specific
to one site's markup. What genuinely varies per deployment is column
order and header wording, so `_map_columns()` reads each table's own
header row (folded, diacritic-insensitive) to locate the title/value/date/
CPV columns rather than assuming a fixed index — the same portal running
on two different counties can and does reorder columns.

Live reconnaissance across all 41 county councils (see
scrapers/config/county_registries.json) found zero confirmed Indeco Soft
deployments among them: the one candidate that passed `detect()`'s
__VIEWSTATE + known-path check (Tulcea) turned out on closer inspection
to be Microsoft SharePoint, not Indeco Soft — SharePoint emits the same
`__VIEWSTATE` hidden field, and its /monitorul-oficial-local/ path also
returned 200, so `detect()`'s current heuristic produced a false
positive there. Tulcea is registered with `platform: "sharepoint"` (no
adapter) rather than "indeco" for that reason — see its
`detection_evidence` for exactly what was observed live. `detect()`
itself is left as-is (it's a legitimate, real ASP.NET WebForms signature
check) rather than papered over with a SharePoint-exclusion hack tuned to
one false positive; a genuine Indeco Soft deployment may still exist
among the ~100 UAT/city-hall sites outside this county-level sweep, and
this class is ready for it. Whoever runs the next registry-building pass
should treat a `detect()`-positive result as a lead to verify by hand
(check the response for a GridView `<table>` under /achizitii-publice/,
not just the presence of the hidden fields) rather than as confirmation.
"""

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.adapters.base_adapter import BaseCMSAdapter
from text_utils import fold, matching_terms

MOL_PATH = "/monitorul-oficial-local/"
ACHIZITII_PATH = "/achizitii-publice/"

_POSTBACK_RE = re.compile(r"__doPostBack\('([^']+)','([^']*)'\)")
_VALUE_RE = re.compile(r"([\d][\d.,]{2,})\s*lei", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(\d{2}[./]\d{2}[./]\d{4})\b")
_CPV_RE = re.compile(r"\b(\d{8}-\d)\b")

MAX_POSTBACK_PAGES = 8

# Header-label fragments (folded) that identify each logical column. Order
# doesn't matter for lookup, only for which one wins on an ambiguous header
# containing several fragments (unlikely, but title is checked first since
# it's the one column every table has).
_COLUMN_HINTS = {
    "title": ["titlu", "denumire", "obiect", "continut"],
    "value": ["valoare", "estimata"],
    "published_date": ["data adopt", "data public", "data emit"],
    "deadline": ["termen", "data limita"],
    "cpv": ["cpv"],
    "number": ["nr.", "numar", "nr crt"],
}


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


def _parse_ro_date(text: str) -> str:
    match = _DATE_RE.search(text)
    if not match:
        return ""
    try:
        return datetime.strptime(match.group(1).replace("/", "."), "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _map_columns(header_cells: List[str]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for idx, header in enumerate(header_cells):
        folded_header = fold(header)
        for field, hints in _COLUMN_HINTS.items():
            if field in mapping:
                continue
            if any(hint in folded_header for hint in hints):
                mapping[field] = idx
    return mapping


def _extract_hidden_fields(soup: BeautifulSoup) -> Dict[str, str]:
    fields = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        tag = soup.find("input", attrs={"name": name})
        fields[name] = tag.get("value", "") if tag else ""
    return fields


def _find_data_table(soup: BeautifulSoup) -> Optional[Any]:
    """Picks the table most likely to be the GridView data grid: the one
    with the most rows among tables that have a header row at all."""
    best = None
    best_rows = 0
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) > best_rows:
            best, best_rows = table, len(rows)
    return best if best_rows >= 2 else None


def _next_postback(soup: BeautifulSoup, seen_targets: set) -> Optional[tuple]:
    for a in soup.find_all("a", href=True):
        match = _POSTBACK_RE.search(a["href"])
        if not match:
            continue
        target, argument = match.groups()
        key = (target, argument)
        if key in seen_targets:
            continue
        text = a.get_text(strip=True)
        if text in ("»", "...", "Next", "Urmatoare", ">") or text.isdigit():
            return key
    return None


class IndecoAdapter(BaseCMSAdapter):
    platform_name = "indeco"

    def __init__(self):
        super().__init__(rate_limit_delay=1.2)

    async def detect(self, base_url: str, client) -> bool:
        response = await self._get(client, base_url)
        if response is None:
            return False
        soup = BeautifulSoup(response.text, "html.parser")
        has_viewstate = soup.find("input", attrs={"name": "__VIEWSTATE"}) is not None
        if not has_viewstate:
            return False
        for path in (MOL_PATH, ACHIZITII_PATH):
            probe = await self._get(client, urljoin(base_url, path))
            if probe is not None:
                return True
        return False

    async def _paginate(self, client, listing_url: str, page_limit: int) -> List[Dict[str, str]]:
        """Walks GridView postback pagination, returning raw table rows as
        {column_index: cell_text} isn't useful across pages with different
        header sets in theory, but in practice a GridView's headers are
        stable across its own pages — so this returns (header_cells,
        List[row_cells]) pairs per page and the caller maps columns once."""
        rows_by_page: List[tuple] = []
        seen_targets: set = set()

        response = await self._get(client, listing_url)
        if response is None:
            return rows_by_page

        for _ in range(page_limit):
            soup = BeautifulSoup(response.text, "html.parser")
            table = _find_data_table(soup)
            if table is not None:
                trs = table.find_all("tr")
                header_cells = [c.get_text(" ", strip=True) for c in trs[0].find_all(["th", "td"])]
                data_rows = [
                    [c.get_text(" ", strip=True) for c in tr.find_all("td")]
                    for tr in trs[1:]
                ]
                data_rows = [r for r in data_rows if any(cell.strip() for cell in r)]
                if data_rows:
                    rows_by_page.append((header_cells, data_rows))

            next_target = _next_postback(soup, seen_targets)
            if next_target is None:
                break
            seen_targets.add(next_target)

            hidden = _extract_hidden_fields(soup)
            form_data = {
                "__EVENTTARGET": next_target[0],
                "__EVENTARGUMENT": next_target[1],
                **hidden,
            }
            response = await self._post(client, listing_url, data=form_data)
            if response is None:
                break

        return rows_by_page

    def _rows_to_notices(
        self, rows_by_page: List[tuple], county: str, source_type: str, source_prefix: str,
        base_url: str, listing_url: str, keywords: Optional[List[str]] = None,
        cutoff_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        notices: List[Dict[str, Any]] = []
        for header_cells, data_rows in rows_by_page:
            columns = _map_columns(header_cells)
            title_idx = columns.get("title")
            if title_idx is None:
                continue
            for row_idx, row in enumerate(data_rows):
                if title_idx >= len(row):
                    continue
                title = row[title_idx].strip()
                if not title:
                    continue
                if keywords and not matching_terms(title, keywords):
                    continue

                full_text = " ".join(row)
                published_date = (
                    _parse_ro_date(row[columns["published_date"]]) if "published_date" in columns and columns["published_date"] < len(row)
                    else _parse_ro_date(full_text)
                )
                if cutoff_date and published_date and published_date < cutoff_date:
                    continue

                number = row[columns["number"]] if "number" in columns and columns["number"] < len(row) else str(row_idx)
                deadline = (
                    _parse_ro_date(row[columns["deadline"]]) if "deadline" in columns and columns["deadline"] < len(row) else None
                ) or None
                cpv = (
                    _CPV_RE.search(row[columns["cpv"]]).group(1)
                    if "cpv" in columns and columns["cpv"] < len(row) and _CPV_RE.search(row[columns["cpv"]])
                    else _CPV_RE.search(full_text).group(1) if _CPV_RE.search(full_text) else None
                )
                value = (
                    _parse_ro_value(row[columns["value"]]) if "value" in columns and columns["value"] < len(row)
                    else _parse_ro_value(full_text)
                )

                notices.append({
                    "source_id": f"{source_prefix}-{county.upper()}-{re.sub(r'[^A-Z0-9]', '', number.upper()) or row_idx}",
                    "source_type": source_type,
                    "county": county,
                    "locality": county,
                    "entity_name": f"Consiliul Județean {county}",
                    "project_title": title,
                    "financial_value_ron": value,
                    "published_date": published_date,
                    "action_deadline": deadline,
                    "source_url": listing_url,
                    "raw_text": full_text[:1500],
                    "document_url": None,
                    "cpv_code": cpv,
                })
        return notices

    async def extract_procurement_notices(self, base_url: str, county: str, days_back: int) -> List[Dict[str, Any]]:
        listing_url = urljoin(base_url, ACHIZITII_PATH)
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        async with self._new_client() as client:
            rows_by_page = await self._paginate(client, listing_url, MAX_POSTBACK_PAGES)
        return self._rows_to_notices(
            rows_by_page, county, "PAAP_LOCAL", "IDC-PAAP", base_url, listing_url, cutoff_date=cutoff,
        )

    async def extract_hcl_decisions(self, base_url: str, county: str, keywords: List[str]) -> List[Dict[str, Any]]:
        listing_url = urljoin(base_url, MOL_PATH)
        async with self._new_client() as client:
            rows_by_page = await self._paginate(client, listing_url, MAX_POSTBACK_PAGES)
        return self._rows_to_notices(
            rows_by_page, county, "HCL_LOCAL", "IDC-HCL", base_url, listing_url, keywords=keywords,
        )
