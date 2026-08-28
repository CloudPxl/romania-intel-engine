import asyncio
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from typing import Dict


class DomainRateLimiter:
    """Per-domain concurrency cap + minimum spacing between requests, so a
    slow or rate-limited host can't starve fetches to unrelated domains
    (which a single global semaphore does today)."""

    _semaphores: Dict[str, asyncio.Semaphore] = {}
    _last_request_at: Dict[str, float] = {}
    _lock = asyncio.Lock()

    @classmethod
    def _domain(cls, url: str) -> str:
        return urlparse(url).netloc or url

    @classmethod
    async def _get_semaphore(cls, domain: str, max_concurrent: int) -> asyncio.Semaphore:
        async with cls._lock:
            if domain not in cls._semaphores:
                cls._semaphores[domain] = asyncio.Semaphore(max_concurrent)
            return cls._semaphores[domain]

    @classmethod
    @asynccontextmanager
    async def acquire(cls, url: str, min_delay_seconds: float, max_concurrent: int = 4):
        """Usage: `async with DomainRateLimiter.acquire(url, delay):`.
        Caps concurrent in-flight requests per domain and enforces a minimum
        delay since the last request to that same domain."""
        domain = cls._domain(url)
        semaphore = await cls._get_semaphore(domain, max_concurrent)
        async with semaphore:
            last = cls._last_request_at.get(domain, 0.0)
            wait_for = min_delay_seconds - (time.monotonic() - last)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            cls._last_request_at[domain] = time.monotonic()
            yield
