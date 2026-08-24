import asyncio
import logging
import random
import httpx
from typing import Optional, Dict, Any

logger = logging.getLogger("BaseScraper")
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
]

class BaseScraper:
    def __init__(self, name: str, rate_limit_delay: float = 0.5):
        self.name = name
        self.rate_limit_delay = rate_limit_delay

    def get_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json,text/html,*/*",
            "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8"
        }

    async def fetch_with_retry(self, url: str, method: str = "GET", max_retries: int = 3) -> Optional[httpx.Response]:
        await asyncio.sleep(self.rate_limit_delay)
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                    res = await client.get(url, headers=self.get_headers())
                    if res.status_code == 200:
                        return res
            except Exception as e:
                logger.warning(f"[{self.name}] Attempt {attempt} failed: {e}")
                await asyncio.sleep(attempt * 1.0)
        return None
