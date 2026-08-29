import json
import re
from datetime import datetime
from typing import List, Optional

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from scrapers.matrix.cni_common import HEALTH_CATEGORIES, CniRegisterScraper
from scrapers.models import RawInstitutionalSignal

# Two former fixtures in this module (SicapHealthScraper,
# CountyEmergencyHospitalScraper) both pointed at the same generic
# e-licitatie.ro market-consultation list that ElicitatieLiveScraper now
# scrapes live, so they were redundant and have been removed rather than
# rebuilt. SICAP health consultations still reach the pipeline — they
# arrive through ElicitatieLiveScraper, which classifies by keyword.

RO_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}


def parse_ro_long_date(value: str) -> str:
    """'27 August 2024' -> '2024-08-27'. Returns '' when the source's date
    element is missing or in a shape we don't recognise, so the caller
    stores nothing rather than a guessed date."""
    match = re.search(r"(\d{1,2})\s+([A-Za-zăâîșşțţĂÂÎȘŞȚŢ]+)\s+(\d{4})", value or "")
    if not match:
        return ""
    day, month_name, year = match.groups()
    month = RO_MONTHS.get(month_name.strip().lower())
    if not month:
        return ""
    try:
        return datetime(int(year), month, int(day)).strftime("%Y-%m-%d")
    except ValueError:
        return ""


class MsAchizitiiScraper(BaseScraper):
    """Ministerul Sanatatii publishes its own procurement announcements at
    /ro/informatii-de-interes-public/achizitii-publice/anunturi/ — a plain
    server-rendered Bootstrap list (article > div.news-list, title anchor,
    blockquote summary, and a calendar <li> carrying a Romanian long-form
    date), paginated via ?page=N.

    This is a genuinely low-volume source: the ministry posts a handful of
    notices a year, so most polls legitimately return nothing new. That's a
    property of the publisher, not a broken scraper — dedup by source_id in
    db.upsert_opportunity means re-reading the same page costs nothing and
    only real additions raise alerts."""

    BASE_URL = "https://www.ms.ro"
    LISTING_PATH = "/ro/informatii-de-interes-public/achizitii-publice/anun%C8%9Buri/"
    MAX_PAGES = 3

    def __init__(self):
        super().__init__("MsAchizitii", rate_limit_delay=1.0, poll_interval_minutes=720)

    def _parse_page(self, html: str) -> List[RawInstitutionalSignal]:
        soup = BeautifulSoup(html, "lxml")
        signals: List[RawInstitutionalSignal] = []

        for article in soup.select("div.news-list article"):
            anchor = article.find("a", href=True)
            if not anchor:
                continue
            title = anchor.get("title") or anchor.get_text(" ", strip=True)
            title = " ".join((title or "").split())
            if not title:
                continue

            href = anchor["href"]
            detail_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            summary_el = article.find("blockquote")
            summary = " ".join(summary_el.get_text(" ", strip=True).split()) if summary_el else ""

            date_el = article.select_one("ul.list-inline li")
            published = parse_ro_long_date(date_el.get_text(" ", strip=True) if date_el else "")

            # The announcement slug is the ministry's own stable identifier
            # for a notice; it survives re-pagination as items age down the
            # list, which a positional index would not.
            slug = href.rstrip("/").rsplit("/", 1)[-1][:120]

            signals.append(RawInstitutionalSignal(
                source_id=f"MS-ANUNT-{slug}",
                source_type="Ministerul Sanatatii - Anunturi Achizitii",
                category="sanatate",
                sub_category="Achizitie Ministerul Sanatatii",
                county="Bucuresti",
                locality="Bucuresti",
                entity_name="Ministerul Sanatatii",
                project_title=title,
                published_date=published,
                raw_description=summary or title,
                source_url=detail_url,
                metadata={"announcement_slug": slug},
            ))
        return signals

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        collected: dict = {}
        for page in range(1, self.MAX_PAGES + 1):
            url = f"{self.BASE_URL}{self.LISTING_PATH}" + (f"?page={page}" if page > 1 else "")
            html = await self.fetch_url(url)
            if not html:
                break
            page_signals = self._parse_page(html)
            if not page_signals:
                break
            before = len(collected)
            for sig in page_signals:
                collected[sig.source_id] = sig
            # A pagination link that silently serves page 1 again would
            # otherwise loop; stop as soon as a page adds nothing new.
            if len(collected) == before:
                break
        return list(collected.values())


class ProgramSanatateScraper(BaseScraper):
    """MIPE/MFE (mfe.gov.ro) runs WordPress and exposes a live REST API.
    Reverse-engineered live: funding calls land in categories 2800
    (ultimele-apeluri-prima-pagina) and 2492 (invitatii-de-participare).
    The previously-targeted 'anunturi-pnrr' category (2719) turned out to
    be almost entirely payment lists ('Lista platilor PNRR ...'), which are
    settlement records, not opportunities — hence the switch.

    Posts are filtered to health-relevant calls by keyword, which is what
    keeps this a *health-domain* source: MFE publishes across every
    operational programme, and the non-health calls belong to other domains.

    Two source quirks handled here: responses carry a UTF-8 BOM (so
    httpx/json .json() parsing fails without stripping it), and the call
    deadline lives in prose inside the post body ('... pana in data de
    29.10.2026, ora 16.00'), not in any structured field."""

    API_URL = "https://mfe.gov.ro/wp-json/wp/v2/posts"
    CATEGORIES = "2800,2492"
    PER_PAGE = 60

    HEALTH_KEYWORDS = re.compile(
        r"s[aă]n[aă]t|spital|medic|clinic|farmac|oncolog|ambulator|"
        r"paliativ|maternit|policlinic|dispensar|health",
        re.IGNORECASE,
    )
    DEADLINE_RE = re.compile(r"p[âa]n[ăa]\s+(?:[îi]n|la)\s+data\s+de\s+(\d{1,2}\.\d{1,2}\.\d{4})", re.IGNORECASE)
    TAG_RE = re.compile(r"<[^>]+>")

    def __init__(self):
        super().__init__("ProgramSanatate", rate_limit_delay=1.0, poll_interval_minutes=180)

    @classmethod
    def _strip_html(cls, value: str) -> str:
        import html as html_module
        return " ".join(html_module.unescape(cls.TAG_RE.sub(" ", value or "")).split())

    @staticmethod
    def _parse_dotted_date(value: str) -> str:
        for fmt in ("%d.%m.%Y",):
            try:
                return datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return ""

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        url = f"{self.API_URL}?categories={self.CATEGORIES}&per_page={self.PER_PAGE}"
        body = await self.fetch_url(url)
        if not body:
            return []
        try:
            posts = json.loads(body.lstrip("﻿"))
        except json.JSONDecodeError:
            self.logger.error(f"[{self.name}] non-JSON response from {url}")
            return []
        if not isinstance(posts, list):
            self.logger.error(f"[{self.name}] unexpected payload shape from {url}")
            return []

        signals: List[RawInstitutionalSignal] = []
        for post in posts:
            title = self._strip_html((post.get("title") or {}).get("rendered", ""))
            content = self._strip_html((post.get("content") or {}).get("rendered", ""))
            if not title or not self.HEALTH_KEYWORDS.search(f"{title} {content}"):
                continue

            deadline_match = self.DEADLINE_RE.search(content)
            deadline = self._parse_dotted_date(deadline_match.group(1)) if deadline_match else None

            published = (post.get("date") or "")[:10]

            signals.append(RawInstitutionalSignal(
                source_id=f"MFE-{post.get('id')}",
                source_type="MIPE/MFE - Apeluri Finantare",
                category="sanatate",
                sub_category="Apel de finantare / Ghidul Solicitantului",
                county="National",
                locality="National",
                entity_name="Ministerul Investitiilor si Proiectelor Europene (MIPE)",
                project_title=title,
                published_date=published,
                action_deadline=deadline,
                # Funding calls announce an envelope in the guide PDF, not
                # in the post body — left at 0 rather than guessed.
                raw_description=content[:1500] or title,
                source_url=post.get("link") or "https://mfe.gov.ro/",
                metadata={"wp_post_id": post.get("id")},
            ))
        return signals


class CniHealthScraper(CniRegisterScraper):
    """CNI's project register, restricted to health facilities ('Unitati
    sanitare*'). Shares one cached fetch with CniInfraScraper — see
    scrapers/matrix/cni_common.py."""

    DOMAIN_CATEGORY = "sanatate"

    def __init__(self):
        super().__init__("CniHealth", rate_limit_delay=1.5, poll_interval_minutes=360)

    def accepts_category(self, category: str) -> bool:
        return category in HEALTH_CATEGORIES
