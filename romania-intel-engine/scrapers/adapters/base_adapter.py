"""Polymorphic CMS adapter contract for county/municipal portals.

Romanian local-government portals cluster around a handful of platforms
rather than being fully bespoke per site: Indeco Soft (ASP.NET WebForms,
routes under /monitorul-oficial-local/ and /achizitii-publice/), Sobis
Public Administration Suite (a JSON API under /api/public/), and plain
WordPress/Drupal municipal templates. Rather than writing one bespoke
scraper class per county — which is what municipal_scrapers.py already
does for the 3 cities it covers, and what infra_scrapers.py does for
Cluj-Napoca/Iași — an adapter is written once per *platform* and reused
across every county confirmed to run it. `scrapers/config/county_registries.json`
holds the per-county {base_url, platform} binding; `scrapers/matrix/municipal_matrix.py`
is what actually turns a registry entry + adapter into RawInstitutionalSignal
records for the orchestrator.

This intentionally does NOT reuse BaseScraper: a BaseScraper subclass is
one fixed live source, but an adapter here is a reusable *strategy*
instantiated once and pointed at N different base_urls (one per county),
so it can't own a single `self.name`/`self.poll_interval_minutes` the way
BaseScraper expects. `municipal_matrix.py`'s wrapper scraper is the
BaseScraper; each adapter is a stateless strategy it delegates to.

Adapters work in a plain Dict[str, Any] shape (see MunicipalNoticeDict
below), not RawInstitutionalSignal — an adapter has no domain classifier,
no CAEN/CPV enrichment, and shouldn't need to import the app's Pydantic
model to stay portable. municipal_matrix.py's AdapterMunicipalScraper is
the one place that maps a MunicipalNoticeDict onto RawInstitutionalSignal,
same separation of concerns as the rest of this matrix (an adapter parses
a page; a scraper decides what a signal means to this product).

MunicipalNoticeDict keys (all adapters agree on this shape):
    source_id: str            deterministic, stable across reruns
    source_type: str          one of HCL_LOCAL | PAAP_LOCAL | CONSULTARE_LOCALA | DISPOZITIE_PRIMAR
    county: str                Romanian county name, normalized (see county_registries.json)
    locality: str
    entity_name: str
    project_title: str
    financial_value_ron: float  0.0 if not stated — undisclosed, not worthless (matches this
                                 codebase's existing convention in municipal_scrapers.py)
    published_date: str        "YYYY-MM-DD" or "" if not available
    action_deadline: Optional[str]
    source_url: str
    raw_text: str
    document_url: Optional[str]
    cpv_code: Optional[str]
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

from scrapers.rate_limiter import DomainRateLimiter

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


class NonRetryableHTTPError(Exception):
    """4xx response — tenacity shouldn't burn attempts on something that
    will never succeed on retry (e.g. a path this portal doesn't have)."""


class BaseCMSAdapter(ABC):
    """One instance per platform (not per county). Stateless: every method
    takes the county's own base_url so the same adapter instance serves
    every county confirmed to run that platform."""

    platform_name: str = "unknown"

    def __init__(self, rate_limit_delay: float = 1.0):
        self.rate_limit_delay = rate_limit_delay
        self.logger = logging.getLogger(f"CMSAdapter.{self.platform_name}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def _get_with_retry(self, client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
        response = await client.get(url, **kwargs)
        if 400 <= response.status_code < 500:
            raise NonRetryableHTTPError(f"{response.status_code} for {url}")
        response.raise_for_status()
        return response

    async def _get(self, client: httpx.AsyncClient, url: str, **kwargs) -> Optional[httpx.Response]:
        async with DomainRateLimiter.acquire(url, self.rate_limit_delay):
            try:
                return await self._get_with_retry(client, url, **kwargs)
            except (httpx.HTTPError, NonRetryableHTTPError) as e:
                self.logger.debug(f"[{self.platform_name}] GET failed for {url}: {e}")
                return None

    async def _post(self, client: httpx.AsyncClient, url: str, **kwargs) -> Optional[httpx.Response]:
        async with DomainRateLimiter.acquire(url, self.rate_limit_delay):
            try:
                response = await client.post(url, **kwargs)
                if 400 <= response.status_code < 500:
                    raise NonRetryableHTTPError(f"{response.status_code} for {url}")
                response.raise_for_status()
                return response
            except (httpx.HTTPError, NonRetryableHTTPError) as e:
                self.logger.debug(f"[{self.platform_name}] POST failed for {url}: {e}")
                return None

    def _new_client(self, timeout: float = 20.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})

    @abstractmethod
    async def detect(self, base_url: str, client: httpx.AsyncClient) -> bool:
        """Cheap, evidence-based platform fingerprint check against a live
        base_url. Must not assume the platform — return False rather than
        a low-confidence guess; the registry-building script tries every
        adapter in turn and keeps whichever one (if any) returns True."""

    @abstractmethod
    async def extract_procurement_notices(self, base_url: str, county: str, days_back: int) -> List[Dict[str, Any]]:
        """Returns MunicipalNoticeDict records with source_type in
        {"PAAP_LOCAL", "CONSULTARE_LOCALA"} — procurement plans and
        pre-tender market consultations. days_back bounds how far back to
        look; a portal with no date filter should filter client-side after
        fetching rather than fetching its entire unbounded history."""

    @abstractmethod
    async def extract_hcl_decisions(self, base_url: str, county: str, keywords: List[str]) -> List[Dict[str, Any]]:
        """Returns MunicipalNoticeDict records with source_type in
        {"HCL_LOCAL", "DISPOZITIE_PRIMAR"} — council resolutions / mayoral
        dispositions whose title matches `keywords` (case/diacritic
        insensitive — use text_utils.matching_terms, same as the rest of
        this matrix, so a caller can pass undiacriticized keywords)."""

    async def download_document(self, doc_url: str) -> bytes:
        """Fetches a linked attachment (PDF annex, etc.) as raw bytes."""
        async with self._new_client(timeout=30.0) as client:
            response = await self._get(client, doc_url)
            if response is None:
                raise RuntimeError(f"Failed to download document: {doc_url}")
            return response.content
