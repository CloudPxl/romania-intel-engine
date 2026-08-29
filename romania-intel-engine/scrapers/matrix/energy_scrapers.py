from typing import List

from scrapers.base_scraper import BaseScraper
from scrapers.matrix.wp_json_common import WordPressCategoryScraper
from scrapers.models import RawInstitutionalSignal

# Two former fixtures in this module pointed at the generic e-licitatie.ro
# market-consultation list that ElicitatieLiveScraper now scrapes live, so
# they duplicated an existing source rather than adding one and have been
# removed: SicapEnergyScraper, and ModernizationFundScraper — the latter
# despite its name, its source_url was the same e-licitatie listing.
#
# MunicipalTermoScraper (primariatm.ro) has also been removed: Timisoara's
# "Achizitii Publice" page was checked live and is a description of the
# department's statutory duties, with zero notices, zero dates and zero
# attached documents. There is no feed there to parse, so no scraper can
# honestly be built against it.


class ProgramEnergieScraper(WordPressCategoryScraper):
    """MIPE/MFE funding calls filtered to energy.

    Same live WordPress REST API as the health-domain scraper (categories
    2800 "ultimele-apeluri-prima-pagina" and 2492 "invitatii-de-participare"),
    keyword-gated to energy so the two domains partition one national feed
    instead of both claiming all of it.

    The category originally targeted here, "anunturi-pnrr" (2719), was
    checked live and is almost entirely payment lists ("Lista platilor
    PNRR C9 ..."), which are settlement records rather than opportunities.
    """

    API_URL = "https://mfe.gov.ro/wp-json/wp/v2/posts"
    CATEGORIES = "2800,2492"
    PER_PAGE = 60
    TOPIC_KEYWORDS = [
        "energie", "energetic", "energetica", "eficienta energetica",
        "fotovoltaic", "fotovoltaice", "regenerabil", "regenerabila",
        "cogenerare", "termoficare", "electric", "electrica", "eolian",
        "biomasa", "hidrogen", "panouri solare", "repowereu",
    ]

    SOURCE_PREFIX = "MFE-ENERGIE"
    SOURCE_TYPE = "MIPE/MFE - Apeluri Finanțare Energie"
    DOMAIN_CATEGORY = "energie"
    SUB_CATEGORY = "Apel de finanțare / Ghidul Solicitantului"
    ENTITY_NAME = "Ministerul Investițiilor și Proiectelor Europene (MIPE)"
    FALLBACK_URL = "https://mfe.gov.ro/"

    def __init__(self):
        super().__init__("ProgramEnergie", rate_limit_delay=1.0, poll_interval_minutes=180)


class ApmPermitScraper(BaseScraper):
    """ANPM (Agenția Națională pentru Protecția Mediului) publishes the
    environmental-permit decisions that precede large energy projects —
    genuinely valuable, because a permit decision appears well before any
    tender notice.

    It cannot currently be scraped: anpm.ro does not resolve in DNS at all
    (checked live — no A record for either anpm.ro or www.anpm.ro, and every
    scheme/host variant fails to connect). This is an outage or a
    decommissioned domain on the publisher's side, not a parsing problem,
    so this scraper reports zero signals and logs the failure rather than
    inventing permit records. The circuit breaker will trip it after
    repeated failures; if ANPM returns, the URL below is the entry point.
    """

    LANDING_URL = "https://www.anpm.ro"

    def __init__(self):
        super().__init__("ApmPermits", rate_limit_delay=1.0, poll_interval_minutes=1440)

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        body = await self.fetch_url(self.LANDING_URL)
        if body is None:
            self.logger.warning(
                f"[{self.name}] ANPM unreachable ({self.LANDING_URL}) — 0 signals. "
                "Domain does not resolve; no permit data can be retrieved."
            )
        else:
            self.logger.info(f"[{self.name}] ANPM reachable again — a real parser can now be implemented.")
        return []
