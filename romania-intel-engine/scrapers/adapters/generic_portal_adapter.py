"""Catch-all adapter for county/municipal portals that are neither Indeco
Soft nor Sobis — the largest bucket in practice, since most Romanian city
halls and county councils run WordPress, Drupal, or a bespoke static/CMS
template rather than one of the two specialized public-sector suites.

Two extraction strategies, tried in order:
  1. WordPress REST API (`/wp-json/wp/v2/posts?search=...`) when present —
     the same reliable JSON contract wp_json_common.py already relies on
     for MIPE/ADR Nord-Vest, just driven by a search term instead of a
     fixed category id (a generic county site's category taxonomy isn't
     known ahead of time the way a single hand-integrated source's is).
  2. Raw HTML link harvesting from a fixed list of plausible listing
     paths (`/achizitii-publice/`, `/monitorul-oficial-local/`,
     `/transparenta/`, …) — for Drupal, static HTML, or anything else.
     This can't assume a page's table structure the way indeco_adapter.py
     can (there's no standard here to assume), so it works at the anchor
     level: any link whose visible text matches the relevant keywords
     becomes one notice, with its surrounding paragraph kept as raw_text
     and any co-located PDF link kept as document_url. This is
     deliberately the least structured extraction in this matrix — it
     trades precision for coverage on the "everything else" bucket, and
     downstream scoring already treats an undisclosed value as legitimate
     (0.0), not a parsing failure.

detect() is intentionally last in the adapter probing order (see
county_registries.json's generation) and matches almost anything
reachable — that's the point of a fallback, not a bug.
"""

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.adapters.base_adapter import BaseCMSAdapter
from text_utils import matching_terms

WP_SEARCH_PATH = "/wp-json/wp/v2/posts"

PROCUREMENT_LISTING_PATHS = [
    "/achizitii-publice/", "/achizitii/", "/transparenta/achizitii-publice/",
    "/anunturi-achizitii-publice/", "/informatii-publice/achizitii-publice/",
]
HCL_LISTING_PATHS = [
    "/monitorul-oficial-local/", "/hotarari-consiliu/", "/hotarari-ale-consiliului-judetean/",
    "/mol/hotarari-ale-consiliului-local/",
]

PROCUREMENT_KEYWORDS = [
    "achizitie", "achizitii", "licitatie", "anunt de participare", "consultare de piata",
    "program anual", "plan anual", "invitatie de participare",
]

_VALUE_RE = re.compile(r"([\d][\d.,]{2,})\s*lei", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(\d{2}[./]\d{2}[./]\d{4})\b")
_CPV_RE = re.compile(r"\b(\d{8}-\d)\b")


def _parse_ro_value(text: str) -> float:
    match = _VALUE_RE.search(text)
    if not match:
        return 0.0
    raw = match.group(1).strip()
    raw = raw.replace(".", "").replace(",", ".") if "," in raw else raw.replace(".", "")
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


def _strip_html(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


class GenericPortalAdapter(BaseCMSAdapter):
    platform_name = "generic_html"

    def __init__(self):
        super().__init__(rate_limit_delay=1.0)

    async def detect(self, base_url: str, client) -> bool:
        response = await self._get(client, base_url)
        return response is not None

    async def _wp_search(self, client, base_url: str, search_term: str) -> Optional[List[Dict[str, Any]]]:
        url = f"{urljoin(base_url, WP_SEARCH_PATH)}?search={search_term}&per_page=50"
        response = await self._get(client, url)
        if response is None:
            return None
        try:
            posts = json.loads(response.text.lstrip("﻿"))
        except json.JSONDecodeError:
            return None
        return posts if isinstance(posts, list) else None

    def _wp_post_to_notice(
        self, post: Dict[str, Any], county: str, source_type: str, source_prefix: str, keywords: List[str],
    ) -> Optional[Dict[str, Any]]:
        title = _strip_html((post.get("title") or {}).get("rendered", ""))
        if not title:
            return None
        content = _strip_html((post.get("content") or {}).get("rendered", ""))
        # WP's ?search= is a full-text match, not a category filter — it
        # matched job-competition and meeting-minutes posts that merely
        # mention the search word in passing (confirmed live against
        # several counties' real feeds). A keyword re-check on the actual
        # title+body, same gate wp_json_common.py's TOPIC_KEYWORDS applies
        # for its fixed-category sources, cuts that noise here too.
        if not matching_terms(f"{title} {content}", keywords):
            return None
        cpv_match = _CPV_RE.search(content)
        return {
            "source_id": f"{source_prefix}-{county.upper()}-{post.get('id')}",
            "source_type": source_type,
            "county": county,
            "locality": county,
            "entity_name": f"Consiliul Județean {county}",
            "project_title": title,
            "financial_value_ron": _parse_ro_value(f"{title} {content}"),
            "published_date": (post.get("date") or "")[:10],
            "action_deadline": None,
            "source_url": post.get("link") or "",
            "raw_text": content[:1500] or title,
            "document_url": None,
            "cpv_code": cpv_match.group(1) if cpv_match else None,
        }

    async def _html_link_harvest(
        self, client, base_url: str, listing_paths: List[str], county: str,
        source_type: str, source_prefix: str, keywords: List[str],
    ) -> List[Dict[str, Any]]:
        notices: List[Dict[str, Any]] = []
        seen_urls = set()
        for path in listing_paths:
            response = await self._get(client, urljoin(base_url, path))
            if response is None:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            for idx, a in enumerate(soup.find_all("a", href=True)):
                text = a.get_text(" ", strip=True)
                if not text or not matching_terms(text, keywords):
                    continue
                href = urljoin(base_url, a["href"])
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                parent_text = a.find_parent().get_text(" ", strip=True) if a.find_parent() else text
                cpv_match = _CPV_RE.search(parent_text)
                notices.append({
                    "source_id": f"{source_prefix}-{county.upper()}-{hashlib.sha1(href.encode('utf-8')).hexdigest()[:10]}",
                    "source_type": source_type,
                    "county": county,
                    "locality": county,
                    "entity_name": f"Consiliul Județean {county}",
                    "project_title": text[:250],
                    "financial_value_ron": _parse_ro_value(parent_text),
                    "published_date": _parse_ro_date(parent_text),
                    "action_deadline": None,
                    "source_url": href,
                    "raw_text": parent_text[:1500],
                    "document_url": href if href.lower().endswith(".pdf") else None,
                    "cpv_code": cpv_match.group(1) if cpv_match else None,
                })
            # A listing page with genuine matches doesn't need every
            # fallback path probed too — but an empty result here is
            # ambiguous (wrong path vs. genuinely nothing), so all
            # candidate paths are still tried rather than stopping early.
        return notices

    async def extract_procurement_notices(self, base_url: str, county: str, days_back: int) -> List[Dict[str, Any]]:
        async with self._new_client() as client:
            posts = await self._wp_search(client, base_url, "achizitii")
            if posts is not None:
                return [
                    n for post in posts
                    if (n := self._wp_post_to_notice(post, county, "PAAP_LOCAL", "GEN-PAAP", PROCUREMENT_KEYWORDS)) is not None
                ]
            return await self._html_link_harvest(
                client, base_url, PROCUREMENT_LISTING_PATHS, county, "PAAP_LOCAL", "GEN-PAAP", PROCUREMENT_KEYWORDS,
            )

    async def extract_hcl_decisions(self, base_url: str, county: str, keywords: List[str]) -> List[Dict[str, Any]]:
        effective_keywords = keywords or ["hotarare"]
        async with self._new_client() as client:
            posts = await self._wp_search(client, base_url, "hotarare")
            if posts is not None:
                return [
                    n for post in posts
                    if (n := self._wp_post_to_notice(post, county, "HCL_LOCAL", "GEN-HCL", effective_keywords)) is not None
                ]
            return await self._html_link_harvest(
                client, base_url, HCL_LISTING_PATHS, county, "HCL_LOCAL", "GEN-HCL", effective_keywords,
            )
