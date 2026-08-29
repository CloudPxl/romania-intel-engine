"""Direct municipal/county coverage for București, Timișoara and Constanța —
closing the gap where Iași (CountyHclScraper, infra_scrapers.py) and
Cluj-Napoca (UrbanismAcScraper, infra_scrapers.py) already had a dedicated
live source but the other two of Romania's five largest economic hubs did
not. Kept in their own file rather than folded into infra_scrapers.py
because, like OradeaAchizitiiScraper, each of these is a general municipal
feed spanning every domain (not infrastructure-only) and is classified per
notice via category_classifier.classify_with_evidence.

Every source below was reverse-engineered live (curl + inspecting the
actual JS bundle / rendered HTML), not assumed from documentation:

  - București: pmb.ro's own site is an Angular SPA with no server-rendered
    content, but its bundled JS calls a real public JSON API at
    api.pmb.ro/api/get-public-procurments (found by grepping the bundle for
    "apiUrl" and endpoint name literals). No API key or auth required.
  - Timișoara: primariatm.ro/hcl is a Next.js page that *is*
    server-rendered — the HCL register is real HTML in the initial
    response, paginated via ?page=N.
  - Constanța: primaria-constanta.ro publishes a genuine, current-year
    procurement-announcement page (WordPress/Elementor) with explicit CPV
    codes, RON values and submission deadlines per notice — the richest
    per-notice payload of any source in this matrix.
"""
import json
import re
from datetime import datetime
from typing import List, Optional

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from scrapers.matrix.category_classifier import classify_with_evidence
from scrapers.models import RawInstitutionalSignal

_VALUE_RE = re.compile(r"([\d][\d.,]{2,})\s*lei", re.IGNORECASE)


def _parse_ro_value(text: str) -> float:
    match = _VALUE_RE.search(text)
    if not match:
        return 0.0
    raw = match.group(1).strip()
    # Romanian notices render values as "1.234.567,89" (dot thousands,
    # comma decimal) — the reverse of the JSON/US convention.
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return 0.0


class PmbAchizitiiScraper(BaseScraper):
    """Primăria Municipiului București's public-procurement announcement
    feed, read from its real backend API (api.pmb.ro) rather than the
    Angular shell at pmb.ro, which renders nothing server-side.

    The endpoint returns its entire history in one call (245 entries as of
    this writing, back to 2020) rather than paginating — there is no
    since/date parameter to request only new ones. Filtering to the
    current and previous calendar year keeps each run's payload relevant
    (a 2020 procurement result is not actionable market intelligence) while
    still being wide enough to never miss anything genuinely current; the
    upsert's ON CONFLICT already makes re-sending older ids from a wider
    window harmless, but there is no reason to persist six-year-old rows
    on every tick.

    Values are not a structured field — when a notice states its value at
    all, it is written inline in the title or description ("...279.330.042
    lei..."), so it is recovered by regex the same way as the Constanța
    and Oradea sources. Many entries (draft strategies, award results
    without a restated figure) genuinely have none; those are left at 0.0
    per this codebase's "undisclosed, not worthless" convention.
    """

    API_URL = "https://api.pmb.ro/api/get-public-procurments"
    ENTITY_NAME = "Primăria Municipiului București"

    _AWARDED_RE = re.compile(r"rezultatul procedurii|declarat[ăa] c[âa][sș]tig[ăa]toare", re.IGNORECASE)
    _ANNOUNCEMENT_RE = re.compile(r"anun[țt] de participare|anun[țt] de publicitate", re.IGNORECASE)
    _PLAN_RE = re.compile(r"program(ul)? anual|strategia anual[ăa]|plan(ul)? anual", re.IGNORECASE)

    def __init__(self):
        super().__init__("PmbAchizitii", rate_limit_delay=1.0, poll_interval_minutes=360)

    @classmethod
    def _procurement_stage(cls, title: str) -> str:
        if cls._AWARDED_RE.search(title):
            return "awarded"
        if cls._ANNOUNCEMENT_RE.search(title):
            return "tender_open"
        if cls._PLAN_RE.search(title):
            return "annual_plan"
        return "notice"

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        body = await self.fetch_url(self.API_URL, timeout=25.0)
        if not body:
            return []
        try:
            items = json.loads(body)
        except json.JSONDecodeError as e:
            self.logger.error(f"[{self.name}] non-JSON response from {self.API_URL}: {e}")
            return []

        current_year = datetime.now().year
        signals: List[RawInstitutionalSignal] = []
        for item in items:
            year = item.get("year")
            if isinstance(year, int) and year < current_year - 1:
                continue

            title = (item.get("title") or "").strip()
            if not title:
                continue
            desc_html = item.get("description") or ""
            desc_soup = BeautifulSoup(desc_html, "html.parser")
            desc_text = desc_soup.get_text(" ", strip=True)

            pdf_link = next(
                (a["href"] for a in desc_soup.find_all("a", href=True) if a["href"].lower().endswith(".pdf")),
                None,
            )
            if pdf_link and pdf_link.startswith("//"):
                pdf_link = f"https:{pdf_link}"

            release_date = (item.get("release_date") or item.get("created_at") or "")[:10]
            category, evidence = classify_with_evidence(self.ENTITY_NAME, title, desc_text)

            signals.append(RawInstitutionalSignal(
                source_id=f"PMB-{item.get('id')}",
                source_type="Primăria Municipiului București - Achiziții Publice",
                category=category,
                sub_category=self._procurement_stage(title).replace("_", " ").capitalize(),
                county="Bucuresti",
                locality="Bucuresti",
                entity_name=self.ENTITY_NAME,
                project_title=title,
                estimated_value_ron=_parse_ro_value(f"{title} {desc_text}"),
                published_date=release_date,
                raw_description=desc_text[:1500] or title,
                source_url=pdf_link or "https://www.pmb.ro/institutie/achizitii",
                document_url=pdf_link,
                metadata={
                    "pmb_item_id": item.get("id"),
                    "procurement_stage": self._procurement_stage(title),
                    "classification_evidence": evidence,
                },
            ))
        return signals


class TimisoaraHclScraper(BaseScraper):
    """Timișoara's Consiliul Local resolution register at
    primariatm.ro/hcl. Unlike Cluj/Iași's PDF-based registers, this page is
    genuinely server-rendered HTML (Next.js SSR) — reverse-engineered live
    by fetching the page directly rather than guessing at a JS-driven API.

    The listing gives HCL number, year and title but, unusually for this
    matrix, no adoption date at all — verified by checking an individual
    resolution's own detail page, which only surfaces internal reference
    dates buried in its legal recitals ("Referatul de aprobare nr.
    .../31.07.2026"), not a clean "adopted on" field. published_date is
    left empty rather than guessed from one of those internal references,
    which would misrepresent an unrelated document's date as the
    resolution's own. Only the most recent two listing pages (40
    resolutions) are read per run — this is a live register, not an
    archive to backfill.
    """

    BASE_URL = "https://www.primariatm.ro"
    LISTING_URL = f"{BASE_URL}/hcl"
    PAGES_TO_READ = 2
    ENTITY_NAME = "Consiliul Local al Municipiului Timișoara"

    # Broader than a single-domain keyword list (Timișoara's register mixes
    # every kind of council business): only resolutions that plausibly
    # represent investment, procurement or infrastructure decisions are
    # kept, filtering out routine governance (personnel appointments,
    # meeting-schedule housekeeping, cotizații).
    RELEVANT_RE = re.compile(
        r"indicatori tehnico-economic|studiu de fezabilitate|deviz general|"
        r"modernizare|reabilitare|construire|extindere|consolidare|"
        r"achizi\w*|licita\w*|contract de (lucr[ăa]ri|furnizare|servicii)|"
        r"proiect tehnic|infrastructur\w*|investi[țt]i\w*|finan[țt]are nerambursabil\w*",
        re.IGNORECASE,
    )

    def __init__(self):
        super().__init__("TimisoaraHcl", rate_limit_delay=1.0, poll_interval_minutes=360)

    def _parse_listing(self, html: str) -> List[RawInstitutionalSignal]:
        soup = BeautifulSoup(html, "html.parser")
        signals: List[RawInstitutionalSignal] = []
        for li in soup.select("li.list-none"):
            a = li.find("a", href=True)
            if not a:
                continue
            text = li.get_text(" ", strip=True)
            match = re.match(r"HCL\s*(\d+)\s*/\s*(\d{4})\s*(.*)", text)
            if not match:
                continue
            hcl_number, hcl_year, title = match.groups()
            title = title.strip(" -")
            if not title or not self.RELEVANT_RE.search(title):
                continue

            href = a["href"]
            url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            category, evidence = classify_with_evidence(self.ENTITY_NAME, title)
            signals.append(RawInstitutionalSignal(
                source_id=f"TIMISOARA-HCL-{hcl_year}-{hcl_number}",
                source_type="Registrul Hotararilor Consiliului Local",
                category=category,
                sub_category="Hotarare Consiliu Local",
                county="Timis",
                locality="Timisoara",
                entity_name=self.ENTITY_NAME,
                project_title=title,
                published_date="",
                raw_description=f"HCL nr. {hcl_number}/{hcl_year}: {title}",
                source_url=url,
                metadata={
                    "hcl_number": hcl_number,
                    "hcl_year": hcl_year,
                    "classification_evidence": evidence,
                    "date_limitation": "adoption date not published in a structured field on this source",
                },
            ))
        return signals

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        collected: dict = {}
        for page in range(1, self.PAGES_TO_READ + 1):
            url = self.LISTING_URL if page == 1 else f"{self.LISTING_URL}?page={page}"
            html = await self.fetch_url(url, timeout=20.0)
            if not html:
                break
            for sig in self._parse_listing(html):
                collected[sig.source_id] = sig
        return list(collected.values())


class ConstantaAchizitiiScraper(BaseScraper):
    """Primăria Constanța's public-procurement + non-reimbursable-funding
    announcement page, one per calendar year at
    .../anunturi-achizitii-publice-si-finantari-nerambursabile/in-anul-{year}/.

    Reverse-engineered live: the page is WordPress/Elementor, and every
    notice is authored as a numbered "<N>. <title>" paragraph followed by
    an Elementor two-column grid of label/value pairs (Tip anunț, Tip
    contract, Data publicării, Documente, Denumirea achiziției, Coduri
    CPV, Valoare estimată, Data limită primire oferte, ...). The page-
    builder markup between those pairs is deeply nested and not worth
    modelling structurally; instead each notice's title paragraph is
    located directly in the raw HTML (`<p><strong>N. ...</strong></p>`),
    and the HTML slice up to the *next* notice's title is parsed as one
    unit for its plain text (for regex field extraction) and its links
    (for the attached PDFs). This is the richest per-notice payload of any
    source in this matrix — genuine CPV codes, explicit RON values and
    real submission deadlines, not just a title.
    """

    BASE_URL = "https://primaria-constanta.ro"
    PAGE_URL_TPL = (
        BASE_URL + "/pagina-pmc/informatii-de-interes-public/achizitii-publice/"
        "anunturi-achizitii-publice-si-finantari-nerambursabile/in-anul-{year}/"
    )
    ENTITY_NAME = "Primăria Municipiului Constanța"

    _TITLE_RE = re.compile(r"<p>\s*<strong>\s*(\d{1,3})\.\s*(.{3,400}?)</strong>\s*</p>", re.DOTALL)
    _HAS_LETTERS_RE = re.compile(r"[A-Za-zĂÂÎȘȚăâîșț]{5,}")
    _CPV_RE = re.compile(r"\b(\d{8}-\d)\b")
    _PUB_DATE_RE = re.compile(r"Data\s*(?:public[ăa]rii|afi[șs][ăa]rii\s*anun[țt])\s*:?\s*(\d{2}\.\d{2}\.\d{4})", re.IGNORECASE)
    _DEADLINE_RE = re.compile(r"Data\s*limit[ăa]\s*(?:de\s*)?(?:primire|depunere)\s*(?:a\s*)?ofert\w*\s*:?\s*(\d{2}\.\d{2}\.\d{4})", re.IGNORECASE)

    def __init__(self):
        super().__init__("ConstantaAchizitii", rate_limit_delay=1.0, poll_interval_minutes=720)

    @staticmethod
    def _to_iso(dotted: str) -> str:
        try:
            return datetime.strptime(dotted, "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            return ""

    def _parse_year_page(self, html: str, year: int) -> List[RawInstitutionalSignal]:
        soup = BeautifulSoup(html, "html.parser")
        block = soup.find("div", class_="elementor-widget-theme-post-content")
        if block is None:
            return []
        raw = str(block)

        matches = [
            (m.group(1), BeautifulSoup(m.group(2), "html.parser").get_text(" ", strip=True), m.start())
            for m in self._TITLE_RE.finditer(raw)
        ]
        entries = [(num, title, start) for num, title, start in matches if self._HAS_LETTERS_RE.search(title)]

        signals: List[RawInstitutionalSignal] = []
        for i, (num, title, start) in enumerate(entries):
            end = entries[i + 1][2] if i + 1 < len(entries) else len(raw)
            segment_html = raw[start:end]
            seg_soup = BeautifulSoup(segment_html, "html.parser")
            text = seg_soup.get_text("\n", strip=True)

            cpv_codes = self._CPV_RE.findall(text)
            pub_match = self._PUB_DATE_RE.search(text)
            deadline_match = self._DEADLINE_RE.search(text)
            pdf_links = [a["href"] for a in seg_soup.find_all("a", href=True) if a["href"].lower().endswith(".pdf")]

            category, evidence = classify_with_evidence(self.ENTITY_NAME, title, text[:800])

            signals.append(RawInstitutionalSignal(
                source_id=f"CONSTANTA-{year}-{num}",
                source_type="Primăria Constanța - Anunțuri Achiziții Publice",
                category=category,
                sub_category="Achizitie directa / consultare piata",
                county="Constanta",
                locality="Constanta",
                entity_name=self.ENTITY_NAME,
                project_title=title,
                estimated_value_ron=_parse_ro_value(text),
                published_date=self._to_iso(pub_match.group(1)) if pub_match else "",
                action_deadline=self._to_iso(deadline_match.group(1)) if deadline_match else None,
                raw_description=text[:1500],
                source_url=pdf_links[0] if pdf_links else self.PAGE_URL_TPL.format(year=year),
                cpv_code=cpv_codes[0] if cpv_codes else None,
                document_url=pdf_links[0] if pdf_links else None,
                metadata={
                    "cpv_codes": cpv_codes,
                    "attachment_urls": pdf_links,
                    "classification_evidence": evidence,
                },
            ))
        return signals

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        year = datetime.now().year
        html = await self.fetch_url(self.PAGE_URL_TPL.format(year=year), timeout=25.0)
        if not html:
            return []
        return self._parse_year_page(html, year)
