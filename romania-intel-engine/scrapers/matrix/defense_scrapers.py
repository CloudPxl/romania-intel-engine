import re
from typing import List

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from scrapers.models import RawInstitutionalSignal
from text_utils import matching_terms, parse_ro_long_date

# Four of the five fixtures in this module have been removed rather than
# rebuilt, because each target was checked live and cannot support a real
# scraper:
#
#   SicapDefenseScraper  — pointed at the same generic e-licitatie.ro
#       market-consultation list ElicitatieLiveScraper already scrapes.
#   MapnInfraScraper     — ddi.mapn.ro no longer accepts connections (its
#       host resolves to a WAF that refuses every request). MApN's actual
#       procurement arm, DGArm/dpa.ro, publishes no notices of its own:
#       its "Achiziții publice" page simply refers operators to
#       e-licitatie.ro, which we already cover.
#   StsSpecialCommsScraper — sts.ro exposes no procurement section at all.
#   CriticalInfraPortAirportScraper — aeroport-iasi.ro is a client-rendered
#       SPA whose 1.8 KB shell contains no data, and its JS bundle exposes
#       no data API to call.
#
# This leaves the defence domain thinner than the others, which reflects
# reality: most Romanian defence procurement is either classified or
# published exclusively through SICAP (covered by ElicitatieLiveScraper),
# rather than on institutional sites. Inventing sources to fill the gap
# would have been the only way to keep five scrapers here.


class BorderPoliceProcurementScraper(BaseScraper):
    """Inspectoratul General al Poliției de Frontieră publishes its
    procurement programmes in the same news stream as operational press
    releases, under /ro/main/n-informaii-de-interes-public-achizitii-publice-27/.

    Verified live: of 35 listed items, 8 are genuine procurement
    programmes (radar maintenance for the Integrated Border Surveillance
    System, ABC gate servicing, maritime patrol vessel maintenance). The
    rest are press releases about seizures and official visits, so the
    stream is keyword-gated — without that filter this source would inject
    news articles into the opportunity feed as if they were tenders.

    The list carries no dates; those live on the detail page in a <time>
    element rendered as Romanian prose ("Marți, 04 August 2026"), so
    matching items are enriched with one extra request each. Only matching
    items are fetched, which keeps that cost proportional to real signal.
    """

    BASE_URL = "https://www.politiadefrontiera.ro"
    LISTING_URL = f"{BASE_URL}/ro/main/n-informaii-de-interes-public-achizitii-publice-27/"

    PROCUREMENT_KEYWORDS = [
        "achizitii", "achizitie", "licitatie", "programul achizitiilor",
        "invitatie de participare", "mentenanta", "furnizare", "dotare",
        "contract", "anunt de participare",
    ]
    # Press-release shapes that contain a procurement word but are not
    # opportunities (a completed-project notice is a closing record).
    EXCLUDE_KEYWORDS = ["anunt de finalizare", "rezultatul", "concurs", "angajare"]

    MAX_DETAIL_FETCHES = 12
    _ID_RE = re.compile(r"-(\d+)\.html$")

    def __init__(self):
        super().__init__("BorderPolice", rate_limit_delay=1.0, poll_interval_minutes=1440)

    async def _enrich(self, detail_url: str) -> tuple:
        """Returns (published_date, document_url). Fails soft: a detail page
        that will not load must not discard the listing entry we already
        have."""
        html = await self.fetch_url(detail_url)
        if not html:
            return "", None
        soup = BeautifulSoup(html, "lxml")
        time_el = soup.find("time")
        published = parse_ro_long_date(time_el.get_text(" ", strip=True)) if time_el else ""

        document_url = None
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if re.search(r"\.(pdf|docx?|xlsx?)$", href, re.IGNORECASE):
                document_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                break
        return published, document_url

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        html = await self.fetch_url(self.LISTING_URL)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        candidates = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if "/ro/main/i-" not in href:
                continue
            title = " ".join(anchor.get_text(" ", strip=True).split())
            if not title:
                continue
            if matching_terms(title, self.EXCLUDE_KEYWORDS):
                continue
            if not matching_terms(title, self.PROCUREMENT_KEYWORDS):
                continue
            detail_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
            candidates.append((title, detail_url))

        signals: List[RawInstitutionalSignal] = []
        seen = set()
        for title, detail_url in candidates[: self.MAX_DETAIL_FETCHES]:
            id_match = self._ID_RE.search(detail_url)
            article_id = id_match.group(1) if id_match else detail_url.rsplit("/", 1)[-1][:60]
            source_id = f"PFR-{article_id}"
            if source_id in seen:
                continue
            seen.add(source_id)

            published, document_url = await self._enrich(detail_url)

            signals.append(RawInstitutionalSignal(
                source_id=source_id,
                source_type="Poliția de Frontieră - Achiziții Publice",
                category="aparare",
                sub_category="Securitate Frontieră & Supraveghere",
                county="Bucuresti",
                locality="Bucuresti",
                entity_name="Inspectoratul General al Poliției de Frontieră (IGPF)",
                project_title=title,
                published_date=published,
                # IGPF announces programmes without stating a value in the
                # listing; the figure, when it exists, is inside the linked
                # document. Left unset rather than guessed.
                raw_description=title,
                source_url=detail_url,
                document_url=document_url,
                metadata={"article_id": article_id},
            ))
        return signals
