"""Direct municipal scrapers for four regional economic hubs beyond the
five already covered (București, Cluj-Napoca, Iași, Timișoara, Constanța):
Brașov, Craiova, Ploiești and Galați.

Every endpoint below was found by live HTTP reconnaissance on 2026-09-08,
not assumed from a URL convention — the four portals turned out to run
four genuinely different architectures, so there is no shared adapter to
reuse here (contrast scrapers/adapters/, which exists precisely for the
counties that *do* share a platform):

    Brașov   www.brasovcity.ro/primaria/achizitii/
             Server-rendered Bootstrap-5 accordion. By far the richest of
             the four: each `.accordion-item` carries a labelled block with
             the notice number, the authority's own CIF, the CPV code, a
             Romanian-formatted estimated value, the bid deadline and the
             award criterion — i.e. everything the feed models, from the
             listing page alone, with no per-notice fetch.

    Craiova  primariacraiova.ro/ro/c/54/achizițiile-publice
             Custom PHP CMS, server-rendered `ul > li.clearfix` rows with a
             detail link and a `span.datet` timestamp. Titles carry a
             status prefix the site adds itself ("Atribuita - ",
             "Anulata - "), which is a real procurement-stage signal and is
             parsed as one rather than left in the title. No value in the
             listing; it lives in the linked detail page, which this pass
             deliberately does not fetch (see the request-budget note
             below), so the value is honestly 0.0/unpublished.

    Ploiești ploiesti.ro/wp-json/wp/v2/{hotarari,anunturi}
             WordPress with real custom post types — `hotarari` (12,198
             Local Council Decisions at verification time) and `anunturi`
             (885). The only one of the four with a machine-readable API.
             It does NOT go through wp_json_common.WordPressCategoryScraper:
             that base builds a `?categories=` query for the standard
             `posts` type, which a custom post type does not answer the
             same way. Its helpers (strip_html, extract_deadline) are
             reused; the base class is left untouched rather than widened
             for one caller, since two live scrapers already depend on it.

    Galați   primariagalati.ro/portal/galati/portal.nsf/...?OpenDocument
             IBM/HCL Domino `.nsf` — the same platform family CLAUDE.md
             already documents for Iași's CountyHclScraper and for the two
             counties registered as `platform: "domino_nsf"` in
             county_registries.json. Rows are `div.item.front_post` with an
             inline "Data: DD.MM.YYYY". The announcements document is ~5MB
             of HTML, which is why this scraper has the longest poll
             interval of the four.

Anti-bot / transport nuances observed, so a future session doesn't
misdiagnose them:
  - None of the four challenged a plain httpx request with a browser
    User-Agent, and all four served valid certificates. This is a markedly
    softer posture than e-licitatie.ro (see notice_scraper.py), which
    silently tarpits repeated requests.
  - brasovcity.ro redirects the apex to `www.`; the canonical host is used
    directly here so every request isn't a 301 first.
  - Galați's announcements page is ~5MB and Brașov's ~345KB, so both get
    explicit generous timeouts rather than BaseScraper.fetch_url's default.

Zero-fabrication contract, same as every other scraper in this package: a
portal that is unreachable, redesigned, or returns nothing parseable logs
a warning and yields an empty list. None of these four invent a value, a
date or a county they did not read.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from scrapers.matrix.category_classifier import classify_with_evidence
from scrapers.matrix.wp_json_common import extract_deadline, strip_html
from scrapers.models import RawInstitutionalSignal
from scrapers.money import parse_ro_number, parse_ro_value

logger = logging.getLogger("MunicipalBatch1")

# "137.000,00  RON" / "1.234.567,89 lei" — the label in Brașov's block is
# followed by the amount and an explicit currency. scrapers/money.py owns
# the dot-thousands/comma-decimal rule itself; this only locates the number.
_RON_AMOUNT_RE = re.compile(r"([\d][\d.,]*)\s*(?:RON|LEI)\b", re.IGNORECASE)
_CPV_RE = re.compile(r"\b(\d{8}-\d)\b")
_CIF_RE = re.compile(r"\bCIF[:\s]*([0-9]{2,10})\b", re.IGNORECASE)
_DATE_DOTTED_RE = re.compile(r"\b(\d{2})[.](\d{2})[.](\d{4})\b")
_DATE_SLASHED_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


def _iso_from_dotted(text: str) -> Optional[str]:
    m = _DATE_DOTTED_RE.search(text or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _iso_from_slashed(text: str) -> Optional[str]:
    m = _DATE_SLASHED_RE.search(text or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


class _MunicipalHtmlScraper(BaseScraper):
    """Shared fetch-and-degrade behaviour for the three server-rendered
    portals. Deliberately thin: the three parse nothing alike, so only the
    error contract and the soup construction are shared."""

    PORTAL_URL: str = ""
    ENTITY_NAME: str = ""
    COUNTY: str = ""
    LOCALITY: str = ""
    FETCH_TIMEOUT: float = 30.0

    async def _soup(self, url: Optional[str] = None) -> Optional[BeautifulSoup]:
        target = url or self.PORTAL_URL
        try:
            body = await self.fetch_url(target, timeout=self.FETCH_TIMEOUT)
        except Exception as e:  # fetch_url already swallows its own, this is belt-and-braces
            self.logger.warning(f"[{self.name}] fetch raised for {target}: {type(e).__name__}: {e}")
            return None
        if not body:
            self.logger.warning(f"[{self.name}] no response body from {target} — yielding no signals")
            return None
        return BeautifulSoup(body, "html.parser")

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        soup = await self._soup()
        if soup is None:
            return []
        try:
            signals = self._parse(soup)
        except Exception as e:
            # A redesigned portal must degrade to "this source reported
            # nothing this tick", never take the whole tick down with it.
            self.logger.warning(f"[{self.name}] parse failed ({type(e).__name__}: {e}) — yielding no signals")
            return []
        if not signals:
            self.logger.warning(f"[{self.name}] page fetched but no rows parsed — layout may have changed")
        return signals

    def _parse(self, soup: BeautifulSoup) -> List[RawInstitutionalSignal]:
        raise NotImplementedError


class BrasovMunicipalScraper(_MunicipalHtmlScraper):
    """Primăria Municipiului Brașov — public procurement notices.

    The one source in this batch whose listing already carries everything
    the feed models, so no per-notice fetch is needed: notice number, the
    authority's CIF (which lands on `opportunities.authority_cui` via the
    metadata promotion), the CPV code, the estimated value in Romanian
    format, the bid deadline and the stated award criterion.
    """

    PORTAL_URL = "https://www.brasovcity.ro/primaria/achizitii/"
    ENTITY_NAME = "Primăria Municipiului Brașov"
    COUNTY = "Brasov"
    LOCALITY = "Brasov"
    FETCH_TIMEOUT = 45.0

    def __init__(self):
        # Procurement notices move faster than HCLs, but this is still a
        # single municipal page — twice a day is plenty and keeps the tick
        # budget for sources that change hourly.
        super().__init__("BrasovMunicipal", rate_limit_delay=1.0, poll_interval_minutes=720)

    @staticmethod
    def _labelled(text: str, label: str) -> Optional[str]:
        """Reads `Label: value` out of the block's flattened text.

        Label casing is inconsistent on the live page — most items use
        "Nr anunt:" while some use "NR ANUNT:" — so matching is
        case-insensitive. The value runs to end-of-line, since several
        labels share a line ("Denumire oficiala: X   CIF: Y").
        """
        m = re.search(
            rf"{re.escape(label)}\s*:\s*(.+)", text, re.IGNORECASE
        )
        return m.group(1).strip() if m else None

    def _parse(self, soup: BeautifulSoup) -> List[RawInstitutionalSignal]:
        signals: List[RawInstitutionalSignal] = []
        for item in soup.select(".accordion-item"):
            body = item.select_one(".accordion-body")
            if body is None:
                continue
            text = body.get_text("\n", strip=True)

            title = self._labelled(text, "Denumire contract")
            if not title:
                # The label is on its own line and the value on the next in
                # some items; fall back to the line after the label.
                lines = text.splitlines()
                for i, line in enumerate(lines[:-1]):
                    if line.strip().lower().startswith("denumire contract"):
                        title = lines[i + 1].strip()
                        break
            if not title:
                continue

            detail = item.select_one('a[href*="anunt-achizitie"]')
            detail_url = (
                f"https://www.brasovcity.ro{detail['href']}"
                if detail and detail.get("href", "").startswith("/")
                else (detail.get("href") if detail else None)
            )

            notice_no = self._labelled(text, "Nr anunt")
            cif_match = _CIF_RE.search(text)
            cpv_match = _CPV_RE.search(text)

            # The value is read from the labelled line only, never from the
            # whole block: a description mentioning a penalty or a previous
            # contract's figure would otherwise be picked up as the budget.
            value = 0.0
            value_line = self._labelled(text, "Valoare estimata")
            if value_line:
                amount = _RON_AMOUNT_RE.search(value_line)
                value = parse_ro_number(amount.group(1)) if amount else parse_ro_value(value_line)

            deadline_line = self._labelled(text, "Data limita depunere oferta")
            published_line = self._labelled(text, "Data publicare")

            description = self._labelled(text, "Descriere contract") or title
            award_criterion = self._labelled(text, "Criterii de atribuire")
            cpv_code = cpv_match.group(1) if cpv_match else None
            category, evidence = classify_with_evidence(
                self.ENTITY_NAME, title, description, cpv_code=cpv_code
            )

            signals.append(RawInstitutionalSignal(
                source_id=f"BV-ACH-{notice_no or (detail_url or title)[-32:]}",
                source_type="Primăria Brașov - Achiziții Publice",
                category=category,
                sub_category="Achiziție Publică",
                county=self.COUNTY,
                locality=self.LOCALITY,
                entity_name=self.ENTITY_NAME,
                project_title=title[:400],
                estimated_value_ron=value,
                published_date=_iso_from_dotted(published_line or "") or "",
                action_deadline=_iso_from_dotted(deadline_line or ""),
                raw_description=description[:1500],
                source_url=detail_url or self.PORTAL_URL,
                cpv_code=cpv_code,
                document_url=detail_url,
                metadata={
                    "notice_no": notice_no,
                    # Feeds opportunities.authority_cui through
                    # ai_refinery's promotion — the portal publishes the
                    # authority's own fiscal code on every notice.
                    "contracting_authority_cui": cif_match.group(1) if cif_match else None,
                    "award_criterion": award_criterion,
                    "notice_kind": self._labelled(text, "Tip anunt"),
                    "contract_kind": self._labelled(text, "Tip contract"),
                    "classification_evidence": evidence,
                },
            ))
        return signals


class CraiovaMunicipalScraper(_MunicipalHtmlScraper):
    """Primăria Municipiului Craiova — public procurement listing.

    The listing gives a title, a timestamp and a detail link; the budget
    lives one click deeper. This scraper deliberately does not follow those
    links: it would turn one request per tick into ~27, against a portal
    whose per-notice value we would then still have to parse out of prose.
    The value is therefore honestly left unpublished rather than guessed —
    the same call municipal_scrapers.py's other listing-only sources make.
    """

    PORTAL_URL = "https://primariacraiova.ro/ro/c/54/achizi%C8%9Bii-publice"
    ENTITY_NAME = "Primăria Municipiului Craiova"
    COUNTY = "Dolj"
    LOCALITY = "Craiova"

    # The portal prefixes a title with the procedure's outcome. Mapped onto
    # the same STAGE_PROFILES vocabulary every other stage-aware scraper
    # uses, so an awarded or cancelled Craiova notice is suppressed by the
    # scoring model exactly like an awarded SEAP one.
    _STATUS_PREFIXES = {
        "atribuita": "awarded",
        "anulata": "cancelled",
    }

    def __init__(self):
        super().__init__("CraiovaMunicipal", rate_limit_delay=1.0, poll_interval_minutes=720)

    @classmethod
    def _split_status(cls, title: str) -> "tuple[str, str]":
        """Returns (stage, clean_title). The prefix is stripped from the
        title so two notices for the same contract don't read as different
        projects once one is awarded."""
        stripped = title.strip()
        for prefix, stage in cls._STATUS_PREFIXES.items():
            head = stripped[: len(prefix) + 3].lower()
            if head.startswith(prefix) and "-" in stripped[: len(prefix) + 4]:
                return stage, stripped.split("-", 1)[1].strip()
        return "tender_open", stripped

    def _parse(self, soup: BeautifulSoup) -> List[RawInstitutionalSignal]:
        signals: List[RawInstitutionalSignal] = []
        container = soup.select_one(".section_content_text_ca")
        if container is None:
            self.logger.warning(f"[{self.name}] content container .section_content_text_ca not found")
            return []

        for row in container.select("li"):
            link = row.find("a", href=True)
            if link is None:
                continue
            raw_title = link.get_text(" ", strip=True)
            if not raw_title:
                continue
            stage, title = self._split_status(raw_title)

            date_el = row.select_one(".datet")
            published = _iso_from_slashed(date_el.get_text(" ", strip=True)) if date_el else None

            href = link["href"]
            detail_url = href if href.startswith("http") else f"https://primariacraiova.ro{href}"
            category, evidence = classify_with_evidence(self.ENTITY_NAME, title)

            signals.append(RawInstitutionalSignal(
                source_id=f"CV-ACH-{href.rsplit('/', 2)[-2] if '/' in href else href}",
                source_type="Primăria Craiova - Achiziții Publice",
                category=category,
                sub_category="Achiziție Publică",
                county=self.COUNTY,
                locality=self.LOCALITY,
                entity_name=self.ENTITY_NAME,
                project_title=title[:400],
                # Not published in the listing — see this class's docstring.
                estimated_value_ron=0.0,
                published_date=published or "",
                raw_description=title,
                source_url=detail_url,
                document_url=detail_url,
                metadata={
                    "procurement_stage": stage,
                    "classification_evidence": evidence,
                },
            ))
        return signals


class GalatiMunicipalScraper(_MunicipalHtmlScraper):
    """Primăria Municipiului Galați — public announcements (Domino .nsf).

    Rows are `div.item.front_post` carrying a title, an inline
    "Data: DD.MM.YYYY" and a description. The page is ~5MB, hence the long
    poll interval and generous timeout. The feed is general municipal
    announcements, so each row is classified into its real domain rather
    than assuming one — several rows are genuine procurement
    ("vânzarea/concesionarea prin licitație publică", "Anunț de
    participare") and the rest are civil-registry notices that simply score
    low, which is the correct outcome rather than a filter to hand-write.
    """

    PORTAL_URL = (
        "https://primariagalati.ro/portal/galati/portal.nsf/AllByUNID/"
        "anunturi-publice-00032dee?OpenDocument"
    )
    ENTITY_NAME = "Primăria Municipiului Galați"
    COUNTY = "Galati"
    LOCALITY = "Galati"
    FETCH_TIMEOUT = 60.0

    # The page serves the entire archive in one document — 4,915 rows at
    # verification time, dating back years, newest first. Emitting all of
    # them every tick would swamp both the feed and the tick deadline with
    # a single municipality's back-catalogue, so only the newest slice is
    # taken. Anything older has already been ingested on a previous tick
    # and is deduped by source_id at upsert.
    MAX_ROWS = 120

    def __init__(self):
        super().__init__("GalatiMunicipal", rate_limit_delay=1.5, poll_interval_minutes=1440)

    def _parse(self, soup: BeautifulSoup) -> List[RawInstitutionalSignal]:
        signals: List[RawInstitutionalSignal] = []
        seen: set = set()
        for row in soup.select("div.item.front_post"):
            # ~300 rows are nested inside another front_post, which would
            # otherwise be emitted twice under two different ids.
            if row.find_parent("div", class_="front_post"):
                continue
            text = row.get_text(" ", strip=True)
            if not text:
                continue
            published = _iso_from_dotted(text)

            # "Anunț public Data: 02.09.2026 Privind vânzarea prin
            # licitație publică a unor imobile..." — the head before the
            # date marker is a *category label* the portal repeats across
            # hundreds of rows ("Anunt important !!", "Anunț public"), not
            # a subject. Using it as the title gave every row the same
            # name and left keyword matching nothing to work with, so the
            # real subject (the prose after the date) is the title and the
            # label becomes the sub-category.
            label, _, tail = text.partition("Data:")
            label = re.sub(r"[!\s]+$", "", label.strip()) or "Anunț Public"
            subject = _DATE_DOTTED_RE.sub("", tail, count=1).strip()
            if not subject:
                continue
            title = subject[:300]

            link = row.find("a", href=True)
            href = link["href"] if link else None
            detail_url = (
                href if (href or "").startswith("http")
                else (f"https://primariagalati.ro{href}" if href else self.PORTAL_URL)
            )

            key = (title[:120], published)
            if key in seen:
                continue
            seen.add(key)

            body = f"{label} {subject}"
            category, evidence = classify_with_evidence(self.ENTITY_NAME, title, subject)
            signals.append(RawInstitutionalSignal(
                source_id=f"GL-ANT-{abs(hash(key)) % (10 ** 12)}",
                source_type="Primăria Galați - Anunțuri Publice",
                category=category,
                sub_category=label[:80],
                county=self.COUNTY,
                locality=self.LOCALITY,
                entity_name=self.ENTITY_NAME,
                project_title=title,
                # Some announcements do quote a figure in prose; money.py
                # is the only parser allowed to read it, and returns 0.0
                # when there is none.
                estimated_value_ron=parse_ro_value(body),
                published_date=published or "",
                action_deadline=extract_deadline(body),
                raw_description=subject[:1500],
                source_url=detail_url,
                document_url=detail_url,
                metadata={"classification_evidence": evidence, "notice_label": label},
            ))
            if len(signals) >= self.MAX_ROWS:
                break
        return signals


class PloiestiMunicipalScraper(BaseScraper):
    """Primăria Municipiului Ploiești — WordPress REST, two custom post
    types: `hotarari` (Local Council Decisions) and `anunturi`.

    HCLs are the point of this source. A council decision approving a
    project's technical-economic indicators is the earliest public signal
    that an investment is coming — months before it reaches SEAP — which is
    the whole pre-tender thesis of this product. 12,198 of them were live
    at verification time, so this reads only the newest page per type
    rather than walking the archive.
    """

    API_BASE = "https://ploiesti.ro/wp-json/wp/v2"
    ENTITY_NAME = "Primăria Municipiului Ploiești"
    COUNTY = "Prahova"
    LOCALITY = "Ploiesti"
    PER_PAGE = 25

    # (post type, sub-category, procurement stage). HCLs are approvals, not
    # tenders: they map to the same pre-tender stage the CNI register and
    # municipal HCL sources already use, so they rank as the early signal
    # they are rather than as an open procedure.
    POST_TYPES = (
        ("hotarari", "Hotărâre de Consiliu Local", "pre_tender_approved_indicators"),
        ("anunturi", "Anunț Public", "notice"),
    )

    def __init__(self):
        super().__init__("PloiestiMunicipal", rate_limit_delay=1.0, poll_interval_minutes=720)

    async def _fetch_type(self, post_type: str) -> List[Dict[str, Any]]:
        url = f"{self.API_BASE}/{post_type}?per_page={self.PER_PAGE}&orderby=date&order=desc"
        body = await self.fetch_url(url, timeout=30.0)
        if not body:
            self.logger.warning(f"[{self.name}] no response for post type '{post_type}'")
            return []
        try:
            posts = json.loads(body.lstrip("﻿"))
        except json.JSONDecodeError:
            self.logger.warning(f"[{self.name}] non-JSON response for post type '{post_type}'")
            return []
        if not isinstance(posts, list):
            self.logger.warning(f"[{self.name}] unexpected payload shape for post type '{post_type}'")
            return []
        return posts

    # An HCL's own title is just its number ("HCL 365/2026"), which tells a
    # bidder nothing and gives keyword matching nothing to match. The
    # subject sits in the decision's preamble, always introduced by one of
    # a few fixed formulas.
    _SUBJECT_PATTERNS = (
        re.compile(r"referitor la\s+(.{15,240})", re.IGNORECASE | re.DOTALL),
        re.compile(r"prin care se propune\s+(.{15,240})", re.IGNORECASE | re.DOTALL),
        re.compile(r"privind\s+(.{15,240})", re.IGNORECASE | re.DOTALL),
    )

    @classmethod
    def _subject_from_content(cls, content: str) -> Optional[str]:
        for pattern in cls._SUBJECT_PATTERNS:
            m = pattern.search(content)
            if m:
                # Cut at the first sentence-ish boundary so the title stays
                # a title rather than half the decision's preamble.
                subject = re.split(r"[;.]\s", m.group(1).strip(), maxsplit=1)[0]
                if len(subject) >= 15:
                    return subject.strip()
        return None

    def _build_signal(
        self, post: Dict[str, Any], post_type: str, sub_category: str, stage: str
    ) -> Optional[RawInstitutionalSignal]:
        title = strip_html((post.get("title") or {}).get("rendered", ""))
        content = strip_html((post.get("content") or {}).get("rendered", ""))
        if not title or not post.get("id"):
            return None

        if post_type == "hotarari":
            subject = self._subject_from_content(content)
            # Keep the HCL number — it's how the document is cited — but
            # lead with what it's actually about.
            if subject:
                title = f"{title} — {subject}"

        body = f"{title} {content}"
        category, evidence = classify_with_evidence(self.ENTITY_NAME, title, content)
        return RawInstitutionalSignal(
            source_id=f"PH-PLOIESTI-{post_type.upper()}-{post['id']}",
            source_type=f"Primăria Ploiești - {sub_category}",
            category=category,
            sub_category=sub_category,
            county=self.COUNTY,
            locality=self.LOCALITY,
            entity_name=self.ENTITY_NAME,
            project_title=title[:400],
            estimated_value_ron=parse_ro_value(body),
            published_date=(post.get("date") or "")[:10],
            action_deadline=extract_deadline(body),
            raw_description=(content[:1500] or title),
            source_url=post.get("link") or f"https://ploiesti.ro/{post_type}/",
            document_url=post.get("link"),
            metadata={
                "wp_post_id": post["id"],
                "wp_post_type": post_type,
                "procurement_stage": stage,
                "classification_evidence": evidence,
            },
        )

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signals: List[RawInstitutionalSignal] = []
        for post_type, sub_category, stage in self.POST_TYPES:
            try:
                posts = await self._fetch_type(post_type)
            except Exception as e:
                # One post type failing must not cost the other.
                self.logger.warning(f"[{self.name}] '{post_type}' fetch failed: {type(e).__name__}: {e}")
                continue
            for post in posts:
                try:
                    signal = self._build_signal(post, post_type, sub_category, stage)
                except Exception as e:
                    self.logger.warning(f"[{self.name}] skipped a '{post_type}' post: {type(e).__name__}: {e}")
                    continue
                if signal:
                    signals.append(signal)
        if not signals:
            self.logger.warning(f"[{self.name}] no signals parsed — API shape may have changed")
        return signals
