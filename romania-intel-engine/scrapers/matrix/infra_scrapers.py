import hashlib
import json
import re
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal

# SICAP market consultations are now covered live by
# scrapers/matrix/elicitatie_scraper.py:ElicitatieLiveScraper — the old
# SicapInfraScraper fixture here was redundant and has been removed.


class CniInfraScraper(BaseScraper):
    """CNI (Compania Nationala de Investitii) publishes its full project
    register through a DataTables server-side JSON endpoint that backs
    https://www.cni.ro/proiecte-in-achizitie — reverse-engineered live via
    that page's inline `ajax: "https://www.cni.ro/ajaxProj.php"` config.
    The endpoint ignores every status/referer filter param we tried and
    always returns its full unfiltered project list (recordsTotal/
    recordsFiltered are also always 0, a server-side bug) — filtering by
    status has to happen client-side, and pagination is done defensively
    with a fixed page count rather than trusting those count fields."""

    AJAX_URL = "https://www.cni.ro/ajaxProj.php"
    LISTING_URL = "https://www.cni.ro/proiecte-in-achizitie"
    TARGET_STATUS = "In achizitie"
    PAGE_SIZE = 500
    MAX_PAGES = 6

    _ID_RE = re.compile(r"-id-(\d+)-cmsid-\d+")
    _LINK_RE = re.compile(r'href="([^"]+)"')

    def __init__(self):
        super().__init__("CniInfra", rate_limit_delay=1.5, poll_interval_minutes=360)

    @staticmethod
    def _parse_ron(value: str) -> float:
        try:
            cleaned = value.replace("lei", "").strip().replace(".", "").replace(",", ".")
            return float(cleaned)
        except (ValueError, AttributeError):
            return 0.0

    async def _fetch_all_rows(self) -> List[list]:
        rows: List[list] = []
        for page in range(self.MAX_PAGES):
            url = f"{self.AJAX_URL}?draw=1&start={page * self.PAGE_SIZE}&length={self.PAGE_SIZE}"
            body = await self.fetch_url(url)
            if not body:
                break
            try:
                page_rows = json.loads(body).get("data", [])
            except json.JSONDecodeError:
                self.logger.error(f"[{self.name}] non-JSON response from {url}")
                break
            rows.extend(page_rows)
            if len(page_rows) < self.PAGE_SIZE:
                break
        return rows

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signals: List[RawInstitutionalSignal] = []
        for row in await self._fetch_all_rows():
            if len(row) < 8 or row[6] != self.TARGET_STATUS:
                continue
            year, category, county, locality, title, budget_str, status, link_html = row[:8]

            link_match = self._LINK_RE.search(link_html or "")
            detail_url = link_match.group(1).replace("\\/", "/") if link_match else self.LISTING_URL
            id_match = self._ID_RE.search(detail_url)
            source_id = (
                f"CNI-{id_match.group(1)}"
                if id_match
                else f"CNI-{hashlib.sha1(f'{year}|{category}|{county}|{locality}|{title}'.encode()).hexdigest()[:16]}"
            )

            signals.append(RawInstitutionalSignal(
                source_id=source_id,
                source_type="CNI Registru Proiecte",
                category="infrastructura",
                sub_category=category or "Nespecificat",
                county=county or "",
                locality=locality or "",
                entity_name="Compania Nationala de Investitii (CNI)",
                project_title=title or "Proiect CNI",
                estimated_value_ron=self._parse_ron(budget_str),
                # CNI's feed only gives a reporting year, not an exact date —
                # left as the bare year rather than fabricating a day/month;
                # db._parse_date() will store this as NULL, not a fake date.
                published_date=str(year) if year else "",
                raw_description=f"Proiect CNI aflat in faza de achizitie publica: {title}, judetul {county}.",
                source_url=detail_url,
                metadata={"reported_year": year, "cni_status": status},
            ))
        return signals

class CnairCfrScraper(BaseScraper):
    """CNAIR's own procurement-plan (PAAP) PDF, live-verified, is a 278-page
    export with zero extractable text (confirmed via pdfplumber: page images
    present, page.extract_text() empty on every sampled page) — it's a
    scanned/rasterized document, not a real digital table. OCR could recover
    it but needs a Tesseract binary and heavy per-tick CPU time that aren't
    viable on a free-tier dyno, and OCR'd table cells (CPV codes, RON values)
    would be too error-prone to trust for scoring. Rather than fabricate
    fixture data or pretend to have parsed it, this scraper only verifies
    the source page is still live and reports zero signals — this is an
    honest gap, not a placeholder."""

    ACHIZITII_PAGE_URL = "https://www.cnadnr.ro/ro/transparenta/programul-anual-al-achizitiilor-publice"

    def __init__(self):
        super().__init__("CnairCfr", rate_limit_delay=1.0, poll_interval_minutes=1440)

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        body = await self.fetch_url(self.ACHIZITII_PAGE_URL)
        if body is None:
            self.logger.error(f"[{self.name}] source page unreachable — {self.ACHIZITII_PAGE_URL}")
        else:
            self.logger.info(f"[{self.name}] source page live, but its PAAP export is a scanned PDF with no extractable text — 0 signals by design.")
        return []


class UrbanismAcScraper(BaseScraper):
    """Cluj-Napoca publishes a genuine, text-based annual procurement plan
    (PAAP) PDF each year under /achizitii-publice/planul-anual-de-achizitii/
    — reverse-engineered live: it's a real pdfplumber-extractable table
    (row no., object/title, CPV code, estimated value RON, funding source,
    procedure type, planned initiation month, planned award month, online/
    offline, responsible person). Only the planned initiation *month* is
    given, never a day, and there's no reliable per-row status flag telling
    us if a line item has already gone to tender — both are genuine limits
    of the source document, not something we can improve on without a
    different feed. published_date is set to the plan's own approval date
    (parsed from its cover page) since that's the one real, exact date
    available; the planned month is kept in metadata instead of being
    fabricated into a fake day-level deadline."""

    LISTING_PAGE_URL = "https://primariaclujnapoca.ro/achizitii-publice/planul-anual-de-achizitii/"
    PDF_LINK_RE = re.compile(r'href="(https://files\.primariaclujnapoca\.ro/[^"]*plan[^"]*achizitii[^"]*\.pdf)"', re.IGNORECASE)
    APPROVAL_DATE_RE = re.compile(r"NR\.\s*\d+/\s*(\d{2}\.\d{2}\.\d{4})")

    def __init__(self):
        super().__init__("UrbanismAC", rate_limit_delay=1.0, poll_interval_minutes=1440)

    @staticmethod
    def _parse_ron(value: str) -> float:
        try:
            return float(value.replace(",", "").strip())
        except (ValueError, AttributeError):
            return 0.0

    @staticmethod
    def _parse_ro_date(value: str) -> str:
        try:
            from datetime import datetime as _dt
            return _dt.strptime(value.strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            return ""

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        from scrapers.pdf_table_extractor import extract_table_rows, extract_first_page_text, normalize_cell

        listing_html = await self.fetch_url(self.LISTING_PAGE_URL)
        if not listing_html:
            return []
        link_match = self.PDF_LINK_RE.search(listing_html)
        if not link_match:
            self.logger.warning(f"[{self.name}] no annual plan PDF link found on {self.LISTING_PAGE_URL}")
            return []
        pdf_url = link_match.group(1)

        pdf_bytes = await self.fetch_bytes(pdf_url)
        if not pdf_bytes:
            return []

        rows = extract_table_rows(pdf_bytes)
        approval_match = self.APPROVAL_DATE_RE.search(extract_first_page_text(pdf_bytes))
        published_date = self._parse_ro_date(approval_match.group(1)) if approval_match else ""

        signals: List[RawInstitutionalSignal] = []
        for row in rows:
            if len(row) < 9 or not (row[0] or "").strip().isdigit():
                continue
            row_no, title, cpv, value_ron, funding, procedure, init_month, award_month, mode = [normalize_cell(c) for c in row[:9]]

            signals.append(RawInstitutionalSignal(
                source_id=f"CLUJ-PAAP-{row_no}-{pdf_url.rsplit('/', 1)[-1]}",
                source_type="Planul Anual al Achizitiilor Publice",
                category="infrastructura",
                sub_category=procedure or "Nespecificat",
                county="Cluj",
                locality="Cluj-Napoca",
                entity_name="Primaria Municipiului Cluj-Napoca",
                project_title=title or "Achizitie planificata",
                estimated_value_ron=self._parse_ron(value_ron),
                published_date=published_date,
                raw_description=f"Achizitie planificata in PAAP Cluj-Napoca: {title}. Sursa de finantare: {funding}.",
                source_url=pdf_url,
                cpv_code=cpv or None,
                document_url=pdf_url,
                metadata={"planned_initiation_month": init_month, "planned_award_month": award_month, "delivery_mode": mode},
            ))
        return signals


class CountyHclScraper(BaseScraper):
    """Iasi's Consiliul Local publishes a real, text-based yearly register
    of adopted resolutions (HCL) as a PDF — reverse-engineered live from
    the register listing page under
    /dm_iasi/portal.nsf/pagini/registrul+pentru+evidenta+hotararilor+adoptate-00001A3A
    (confirmed pdfplumber-extractable: Nr.HCL, adoption date, communication
    date, title, initiator, follow-up events). The register mixes every
    council decision (school networks, budgets, personnel, etc.), so this
    keeps only resolutions whose title matches infrastructure/investment
    keywords — the same kind of signal the old fixture invented by hand
    (technical-economic indicator approvals, feasibility studies, public
    works), except these are real HCL numbers and real dates. The register
    file only covers full closed years (the most recent one currently
    published covers 2025, updated Feb 2026) — Primaria Iasi hasn't yet
    published a 2026 edition, so this is the latest real data available,
    not a stale fallback we chose over a fresher one."""

    REGISTER_PAGE_URL = "https://www.primaria-iasi.ro/dm_iasi/portal.nsf/pagini/registrul+pentru+evidenta+hotararilor+adoptate-00001A3A?Open"
    PDF_LINK_RE = re.compile(r'href="(/dm_iasi/portal\.nsf/atasament/[^"]*\$FILE/[^"]*\.pdf(?:\?Open)?)"[^>]*>Registru hotarari adoptate (\d{4})', re.IGNORECASE)
    INFRA_KEYWORDS = re.compile(
        r"indicatori tehnico-economic|studiu de fezabilitate|documenta\w* de avizare|"
        r"modernizare|reabilitare|construire|extindere|achizi\w*|infrastructur\w*",
        re.IGNORECASE,
    )

    def __init__(self):
        super().__init__("CountyHcl", rate_limit_delay=1.0, poll_interval_minutes=1440)

    @staticmethod
    def _parse_ro_date(value: str) -> str:
        try:
            from datetime import datetime as _dt
            return _dt.strptime(value.strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            return ""

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        from scrapers.pdf_table_extractor import extract_table_rows, normalize_cell

        listing_html = await self.fetch_url(self.REGISTER_PAGE_URL)
        if not listing_html:
            return []
        link_match = self.PDF_LINK_RE.search(listing_html)
        if not link_match:
            self.logger.warning(f"[{self.name}] no HCL register PDF link found on {self.REGISTER_PAGE_URL}")
            return []
        pdf_url = "https://www.primaria-iasi.ro" + link_match.group(1)
        register_year = link_match.group(2)

        pdf_bytes = await self.fetch_bytes(pdf_url)
        if not pdf_bytes:
            return []

        signals: List[RawInstitutionalSignal] = []
        for row in extract_table_rows(pdf_bytes):
            if len(row) < 4 or not (row[0] or "").strip().isdigit():
                continue
            nr_hcl, data_adoptarii, _data_comunicarii, titlu = [normalize_cell(c) for c in row[:4]]
            if not self.INFRA_KEYWORDS.search(titlu):
                continue

            signals.append(RawInstitutionalSignal(
                source_id=f"IASI-HCL-{register_year}-{nr_hcl}",
                source_type="Registrul Hotararilor Consiliului Local",
                category="infrastructura",
                sub_category="Hotarare Consiliu Local",
                county="Iasi",
                locality="Iasi",
                entity_name="Consiliul Local Iasi",
                project_title=titlu or f"HCL {nr_hcl}/{register_year}",
                published_date=self._parse_ro_date(data_adoptarii),
                raw_description=f"HCL nr. {nr_hcl}/{register_year}, adoptata {data_adoptarii}: {titlu}",
                source_url=pdf_url,
                document_url=pdf_url,
                metadata={"hcl_number": nr_hcl, "hcl_year": register_year},
            ))
        return signals
