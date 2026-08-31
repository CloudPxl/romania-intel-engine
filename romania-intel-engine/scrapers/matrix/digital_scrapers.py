import re
from datetime import datetime
from typing import List

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from scrapers.matrix.category_classifier import classify_with_evidence
from scrapers.matrix.wp_json_common import WordPressCategoryScraper
from scrapers.models import RawInstitutionalSignal

# Removed rather than rebuilt, after checking each target live:
#
#   SicapDigitalScraper — pointed at the generic e-licitatie.ro
#       market-consultation list already covered by ElicitatieLiveScraper.
#   McidGovCloudScraper — research.gov.ro redirects to mcid.gov.ro, whose
#       procurement page carries only 2017-2021 PDFs, and whose live post
#       feed is HR notices (exam results, promotions). No current
#       procurement stream exists there to scrape.
#   SmartTransportUrbanScraper — its source_url was primaria-iasi.ro, the
#       same publisher already scraped by CountyHclScraper; a second
#       scraper over one publisher would have produced colliding
#       source_ids for the same documents.


class AdrNordVestScraper(WordPressCategoryScraper):
    """ADR Nord-Vest (regionordvest.ro) runs the Regional Programme for the
    North-West and exposes the standard WordPress REST API.

    Categories verified live against its own taxonomy: 3 "por-2021-2027"
    (578 posts) carries the programme's calls and guides, and 18
    "consultare-publica" (41) carries draft guides open for public
    comment — the earliest possible engagement point, before a call is
    even finalised.

    ADR funding is regional by design, so this is filed under Cluj (the
    agency's seat) with the North-West region recorded in metadata, rather
    than as a national signal.
    """

    API_URL = "https://regionordvest.ro/wp-json/wp/v2/posts"
    CATEGORIES = "3,18"
    PER_PAGE = 50

    SOURCE_PREFIX = "ADRNV"
    SOURCE_TYPE = "ADR Nord-Vest - Program Regional"
    DOMAIN_CATEGORY = "digitalizare"
    SUB_CATEGORY = "Apel / Consultare Program Regional"
    ENTITY_NAME = "Agenția de Dezvoltare Regională Nord-Vest"
    COUNTY = "Cluj"
    LOCALITY = "Cluj-Napoca"
    FALLBACK_URL = "https://regionordvest.ro/"

    def __init__(self):
        super().__init__("AdrRegional", rate_limit_delay=1.0, poll_interval_minutes=360)

    def build_signal(self, post):
        signal = super().build_signal(post)
        if signal:
            signal.metadata["development_region"] = "nord-vest"
        return signal


class OradeaAchizitiiScraper(BaseScraper):
    """Primăria Oradea publishes a live, structured procurement feed at
    /primaria-oradea/achizitii/initieri-de-achizitii/.

    Reverse-engineered live: each listing entry is a single <a> whose
    class list includes `grid-cols-12`, wrapping labelled fields —
    procedure type, publication timestamp, contracting authority, title,
    CPV code, notice number ("Cod Unic"), contract type, submission
    deadline, estimated value in RON, and procedure state. That is the
    richest per-notice payload of any source in this matrix: real CPV
    codes, real values and real deadlines, published within the last day.

    Each entry links through to the corresponding e-licitatie *c-notice*
    (a published tender). That is a different funnel stage from
    ElicitatieLiveScraper, which reads *mc-notices* (pre-tender market
    consultations), so the two do not overlap — their source_ids are
    namespaced separately for that reason.

    Because a city hall procures across every sector — the current feed is
    dominated by county-hospital equipment — the domain is classified per
    notice by the shared classifier rather than hardcoded. The fixture
    this replaces asserted that everything from Oradea was a technology
    park.
    """

    BASE_URL = "https://oradea.ro"
    LISTING_URL = f"{BASE_URL}/primaria-oradea/achizitii/initieri-de-achizitii/"
    MAX_PAGES = 3

    _CPV_RE = re.compile(r"\b(\d{8}-\d)\b")
    _NOTICE_RE = re.compile(r"\b([A-Z]{2,4}\d{6,})\b")
    _DATETIME_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s*/\s*(\d{2}:\d{2})")
    _VALUE_RE = re.compile(r"(\d[\d\s.,]*)\s*RON")

    def __init__(self):
        super().__init__("OradeaAchizitii", rate_limit_delay=1.0, poll_interval_minutes=180)

    @staticmethod
    def _to_iso(dotted: str) -> str:
        try:
            return datetime.strptime(dotted, "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            return ""

    @classmethod
    def _parse_value(cls, text: str) -> float:
        match = cls._VALUE_RE.search(text)
        if not match:
            return 0.0
        raw = match.group(1).strip().replace(" ", "")
        # The feed renders values as plain decimals ("10302905.76"); guard
        # against a thousands-separated variant appearing later.
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return 0.0

    def _parse_page(self, html: str) -> List[RawInstitutionalSignal]:
        soup = BeautifulSoup(html, "lxml")
        entries = [
            tag for tag in soup.find_all("a")
            if tag.get("class") and any("grid-cols-12" in c for c in tag.get("class"))
        ]

        signals: List[RawInstitutionalSignal] = []
        for entry in entries:
            parts = [p.strip() for p in entry.get_text("|", strip=True).split("|") if p.strip()]
            if len(parts) < 4:
                continue
            blob = " ".join(parts)

            notice_match = self._NOTICE_RE.search(blob)
            if not notice_match:
                # Without the authority's own notice number there is no
                # stable identity for this row, and a positional id would
                # collide as entries page down over time.
                continue
            notice_no = notice_match.group(1)

            procedure_type = parts[0]
            dates = self._DATETIME_RE.findall(blob)
            published = self._to_iso(dates[0][0]) if dates else ""
            deadline = self._to_iso(dates[-1][0]) if len(dates) > 1 else None

            authority = parts[2] if len(parts) > 2 else "Primăria Municipiului Oradea"
            title = parts[3] if len(parts) > 3 else ""
            if not title:
                continue

            cpv_match = self._CPV_RE.search(blob)
            cpv_code = cpv_match.group(1) if cpv_match else None

            href = entry.get("href") or ""
            if href.startswith("//"):
                href = f"https:{href}"
            elif href.startswith("/"):
                href = f"{self.BASE_URL}{href}"

            category, evidence = classify_with_evidence(authority, title, blob)

            signals.append(RawInstitutionalSignal(
                source_id=f"ORADEA-{notice_no}",
                source_type="Primăria Oradea - Inițieri de Achiziții",
                category=category,
                sub_category=procedure_type or "Procedură de achiziție",
                county="Bihor",
                locality="Oradea",
                entity_name=authority,
                project_title=title,
                estimated_value_ron=self._parse_value(blob),
                published_date=published,
                action_deadline=deadline,
                raw_description=blob[:1500],
                source_url=href or self.LISTING_URL,
                cpv_code=cpv_code,
                metadata={
                    "notice_no": notice_no,
                    "procedure_type": procedure_type,
                    "classification_evidence": evidence,
                },
            ))
        return signals

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        collected = {}
        for page in range(1, self.MAX_PAGES + 1):
            url = self.LISTING_URL if page == 1 else f"{self.LISTING_URL}?sf_paged={page}"
            html = await self.fetch_url(url, timeout=30.0)
            if not html:
                break
            page_signals = self._parse_page(html)
            if not page_signals:
                break
            before = len(collected)
            for sig in page_signals:
                collected[sig.source_id] = sig
            # A pagination parameter the server ignores would otherwise
            # re-serve page 1 forever.
            if len(collected) == before:
                break
        return list(collected.values())
