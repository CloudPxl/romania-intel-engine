from typing import List

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from scrapers.matrix.cni_common import HEALTH_CATEGORIES, CniRegisterScraper
from scrapers.matrix.wp_json_common import WordPressCategoryScraper
from scrapers.models import RawInstitutionalSignal
from text_utils import parse_ro_long_date

# Two former fixtures in this module (SicapHealthScraper,
# CountyEmergencyHospitalScraper) both pointed at the same generic
# e-licitatie.ro market-consultation list that ElicitatieLiveScraper now
# scrapes live, so they were redundant and have been removed rather than
# rebuilt. SICAP health consultations still reach the pipeline — they
# arrive through ElicitatieLiveScraper, which classifies by keyword.

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


class ProgramSanatateScraper(WordPressCategoryScraper):
    """MIPE/MFE funding calls filtered to health.

    Reverse-engineered live: funding calls land in categories 2800
    (ultimele-apeluri-prima-pagina) and 2492 (invitatii-de-participare).
    The previously-targeted 'anunturi-pnrr' category (2719) turned out to
    be almost entirely payment lists ('Lista platilor PNRR ...'), which are
    settlement records, not opportunities — hence the switch.

    The keyword gate is what keeps this a *health-domain* source: MFE
    publishes across every operational programme, and its energy calls are
    claimed by ProgramEnergieScraper, so the two partition one feed rather
    than both claiming all of it.

    The shared base (wp_json_common) handles this host's UTF-8 BOM and the
    deadlines that exist only as prose inside the post body.
    """

    API_URL = "https://mfe.gov.ro/wp-json/wp/v2/posts"
    CATEGORIES = "2800,2492"
    PER_PAGE = 60
    TOPIC_KEYWORDS = [
        "sanatate", "sanitar", "spital", "spitalicesc", "medic", "medical",
        "medicala", "clinic", "clinica", "farmaceutic", "oncologic",
        "ambulatoriu", "paliativ", "maternitate", "policlinica", "dispensar",
        "health",
    ]

    SOURCE_PREFIX = "MFE"
    SOURCE_TYPE = "MIPE/MFE - Apeluri Finanțare Sănătate"
    DOMAIN_CATEGORY = "sanatate"
    SUB_CATEGORY = "Apel de finanțare / Ghidul Solicitantului"
    ENTITY_NAME = "Ministerul Investițiilor și Proiectelor Europene (MIPE)"
    FALLBACK_URL = "https://mfe.gov.ro/"

    def __init__(self):
        super().__init__("ProgramSanatate", rate_limit_delay=1.0, poll_interval_minutes=180)


class CniHealthScraper(CniRegisterScraper):
    """CNI's project register, restricted to health facilities ('Unitati
    sanitare*'). Shares one cached fetch with CniInfraScraper — see
    scrapers/matrix/cni_common.py."""

    DOMAIN_CATEGORY = "sanatate"

    def __init__(self):
        super().__init__("CniHealth", rate_limit_delay=1.5, poll_interval_minutes=360)

    def accepts_category(self, category: str) -> bool:
        return category in HEALTH_CATEGORIES
