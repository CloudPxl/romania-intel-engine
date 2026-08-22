from abc import ABC, abstractmethod
from typing import List, Optional
import hashlib
import time
from src.database.models import RawRecord, SourceCategory, is_record_scraped, save_raw_record, log_adapter_run

class BaseSourceAdapter(ABC):
    def __init__(self, name: str = "", category: SourceCategory = SourceCategory.OPEN_DATA, poll_interval_minutes: int = 60, **kwargs):
        self.name = name or kwargs.get("source_name", "Unnamed Source")
        self.source_name = self.name
        self.category = category
        self.poll_interval_minutes = poll_interval_minutes
        self.last_run_timestamp: float = 0.0

    def generate_source_id(self, raw_unique_str: str) -> str:
        return hashlib.sha256(raw_unique_str.encode("utf-8")).hexdigest()

    @abstractmethod
    async def fetch_latest(self) -> List[RawRecord]:
        pass

    async def execute_safe(self) -> List[RawRecord]:
        t0 = time.time()
        new_records: List[RawRecord] = []
        try:
            fetched = await self.fetch_latest()
            for record in fetched:
                if not is_record_scraped(record.source_id):
                    if save_raw_record(record):
                        new_records.append(record)
            
            exec_time = (time.time() - t0) * 1000
            self.last_run_timestamp = time.time()
            log_adapter_run(self.name, "SUCCESS", len(new_records), None, exec_time)
            return new_records
        except Exception as e:
            exec_time = (time.time() - t0) * 1000
            self.last_run_timestamp = time.time()
            log_adapter_run(self.name, "ERROR", 0, str(e), exec_time)
            print(f"[!] Error in adapter {self.name}: {e}")
            return []
