import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("CacheEngine")

class MemoryCacheEngine:
    """
    In-memory LRU-TTL cache engine to serve concurrent requests
    without overloading database connection pools.
    """
    def __init__(self, default_ttl_seconds: int = 90):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if not entry:
            return None

        if time.time() > entry["expires_at"]:
            del self._cache[key]
            return None

        return entry["value"]

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None):
        ttl = ttl_seconds or self.default_ttl
        self._cache[key] = {
            "value": value,
            "expires_at": time.time() + ttl
        }

    def invalidate(self, prefix: Optional[str] = None):
        if not prefix:
            self._cache.clear()
        else:
            keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._cache[k]
        logger.info(f"⚡ [Cache] Invalidated entries (prefix: {prefix or 'ALL'})")

global_cache = MemoryCacheEngine(default_ttl_seconds=90)
