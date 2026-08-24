import logging
from abc import ABC, abstractmethod
from typing import List
from scrapers.models import RawInstitutionalSignal

class BaseScraper(ABC):
    def __init__(self, name: str, rate_limit_delay: float = 0.5):
        self.name = name
        self.rate_limit_delay = rate_limit_delay
        self.logger = logging.getLogger(name)

    @abstractmethod
    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        pass
