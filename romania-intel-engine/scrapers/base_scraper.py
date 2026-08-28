import asyncio
import logging
from abc import ABC, abstractmethod
from typing import List, Optional
import httpx
from scrapers.models import RawInstitutionalSignal

class BaseScraper(ABC):
    _semaphore = asyncio.Semaphore(15)

    def __init__(self, name: str, rate_limit_delay: float = 0.5):
        self.name = name
        self.rate_limit_delay = rate_limit_delay
        self.logger = logging.getLogger(name)

    @abstractmethod
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        pass

    async def fetch_url(self, url: str) -> Optional[str]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}
        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=headers) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response.text
            except (httpx.HTTPError, asyncio.TimeoutError) as e:
                self.logger.error(f"[{self.name}] fetch_url failed for {url}: {e}")
                return None
