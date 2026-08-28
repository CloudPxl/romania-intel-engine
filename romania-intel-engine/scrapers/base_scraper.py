import asyncio
import logging
from abc import ABC, abstractmethod
from typing import List, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from scrapers.models import RawInstitutionalSignal
from scrapers.rate_limiter import DomainRateLimiter

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


class NonRetryableHTTPError(Exception):
    """Raised for 4xx responses so tenacity doesn't burn attempts on errors
    that will never succeed on retry (e.g. a 404)."""


class BaseScraper(ABC):
    def __init__(self, name: str, rate_limit_delay: float = 0.5, poll_interval_minutes: int = 360):
        self.name = name
        self.rate_limit_delay = rate_limit_delay
        self.poll_interval_minutes = poll_interval_minutes
        self.logger = logging.getLogger(name)

    @abstractmethod
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        pass

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError, asyncio.TimeoutError)),
        reraise=True,
    )
    async def _get_with_retry(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        response = await client.get(url)
        if 400 <= response.status_code < 500:
            raise NonRetryableHTTPError(f"{response.status_code} for {url}")
        response.raise_for_status()
        return response

    async def fetch_url(self, url: str) -> Optional[str]:
        async with DomainRateLimiter.acquire(url, self.rate_limit_delay):
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
                    response = await self._get_with_retry(client, url)
                    return response.text
            except (httpx.HTTPError, asyncio.TimeoutError, NonRetryableHTTPError) as e:
                self.logger.error(f"[{self.name}] fetch_url failed for {url}: {e}")
                return None
