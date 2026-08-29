"""Shared reader for Romanian public institutions running WordPress.

MIPE/MFE (mfe.gov.ro) and ADR Nord-Vest (regionordvest.ro) both expose the
standard WordPress REST API, which is a far better contract than scraping
their rendered HTML: stable JSON, real publication timestamps, and
server-side category filtering.

Two quirks are handled here because they are shared across these hosts and
each one silently breaks naive parsing:

  * Responses can carry a UTF-8 BOM, which makes json.loads raise
    "Unexpected UTF-8 BOM" before any field is ever read.
  * Titles and bodies come back as rendered HTML with entities, so they
    need unescaping as well as tag stripping.
"""

import html as html_module
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal
from text_utils import matching_terms

logger = logging.getLogger("WordPressScraper")

_TAG_RE = re.compile(r"<[^>]+>")

# Funding calls state their submission window in prose inside the post
# body ("... se deschide in data de 27.08.2026 ... pana in data de
# 29.10.2026, ora 16.00"), never in a structured field.
DEADLINE_PATTERNS = [
    re.compile(r"p[âa]n[ăa]\s+(?:[îi]n|la)\s+data\s+de\s+(\d{1,2}\.\d{1,2}\.\d{4})", re.IGNORECASE),
    re.compile(r"termen(?:ul)?\s+(?:limit[ăa]|de\s+depunere)[^\d]{0,30}(\d{1,2}\.\d{1,2}\.\d{4})", re.IGNORECASE),
    re.compile(r"data\s+limit[ăa][^\d]{0,30}(\d{1,2}\.\d{1,2}\.\d{4})", re.IGNORECASE),
]


def strip_html(value: str) -> str:
    return " ".join(html_module.unescape(_TAG_RE.sub(" ", value or "")).split())


def parse_dotted_date(value: str) -> Optional[str]:
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def extract_deadline(text: str) -> Optional[str]:
    for pattern in DEADLINE_PATTERNS:
        match = pattern.search(text)
        if match:
            parsed = parse_dotted_date(match.group(1))
            if parsed:
                return parsed
    return None


class WordPressCategoryScraper(BaseScraper):
    """Base for scrapers that read a WordPress site's posts in given
    categories. Subclasses declare the endpoint, the categories, and how a
    post maps onto a signal."""

    API_URL: str = ""
    CATEGORIES: str = ""
    PER_PAGE: int = 50
    # Optional keyword gate. When set, only posts matching it are emitted —
    # used where one national feed serves several domains and this scraper
    # owns only one of them.
    TOPIC_KEYWORDS: Optional[List[str]] = None

    SOURCE_PREFIX: str = "WP"
    SOURCE_TYPE: str = "WordPress"
    DOMAIN_CATEGORY: str = "infrastructura"
    SUB_CATEGORY: str = "Anunț"
    ENTITY_NAME: str = ""
    COUNTY: str = "National"
    LOCALITY: str = "National"
    FALLBACK_URL: str = ""

    async def fetch_posts(self) -> List[Dict[str, Any]]:
        url = f"{self.API_URL}?categories={self.CATEGORIES}&per_page={self.PER_PAGE}"
        body = await self.fetch_url(url, timeout=30.0)
        if not body:
            return []
        try:
            # lstrip the BOM rather than relying on the caller's decoding.
            posts = json.loads(body.lstrip("﻿"))
        except json.JSONDecodeError:
            self.logger.error(f"[{self.name}] non-JSON response from {url}")
            return []
        if not isinstance(posts, list):
            self.logger.error(f"[{self.name}] unexpected payload shape from {url}")
            return []
        return posts

    def build_signal(self, post: Dict[str, Any]) -> Optional[RawInstitutionalSignal]:
        title = strip_html((post.get("title") or {}).get("rendered", ""))
        content = strip_html((post.get("content") or {}).get("rendered", ""))
        if not title:
            return None

        if self.TOPIC_KEYWORDS and not matching_terms(f"{title} {content}", self.TOPIC_KEYWORDS):
            return None

        return RawInstitutionalSignal(
            source_id=f"{self.SOURCE_PREFIX}-{post.get('id')}",
            source_type=self.SOURCE_TYPE,
            category=self.DOMAIN_CATEGORY,
            sub_category=self.SUB_CATEGORY,
            county=self.COUNTY,
            locality=self.LOCALITY,
            entity_name=self.ENTITY_NAME,
            project_title=title,
            published_date=(post.get("date") or "")[:10],
            action_deadline=extract_deadline(content),
            # The funding envelope lives in the guide PDF these posts link
            # to, not in the post itself, so no value is asserted here.
            raw_description=content[:1500] or title,
            source_url=post.get("link") or self.FALLBACK_URL,
            metadata={"wp_post_id": post.get("id")},
        )

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signals: List[RawInstitutionalSignal] = []
        for post in await self.fetch_posts():
            signal = self.build_signal(post)
            if signal:
                signals.append(signal)
        return signals
