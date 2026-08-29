import os
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Dict, List

logger = logging.getLogger("CacheEngine")

class MemoryCacheEngine:
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

DATA_DIR = Path(__file__).resolve().parent / "data"
NEWSLETTER_STORE_PATH = DATA_DIR / "newsletter_cache.json"

class NewsletterStore:
    """File-backed store so the daemon process and the API process can share
    the latest refined leads without an in-memory cache or a database."""

    def __init__(self, path: Path = NEWSLETTER_STORE_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, leads: List[Dict[str, Any]]) -> None:
        # ISO string, not a raw epoch float — the Postgres-backed path
        # (api.py:_load_feed) always returns updated_at as an ISO string,
        # and this file-cache fallback previously leaked a bare Unix
        # timestamp (e.g. 1788033181.83) straight through to API
        # responses whenever it served as the fallback, which is an
        # internal implementation detail no client should have to parse.
        updated_at = datetime.now(timezone.utc).isoformat()
        payload = {"updated_at": updated_at, "count": len(leads), "leads": leads}
        tmp_path = self.path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp_path, self.path)
        logger.info(f"📰 [NewsletterStore] Saved {len(leads)} leads to {self.path}")

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"updated_at": None, "count": 0, "leads": []}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"[NewsletterStore] Failed to read store: {e}")
            return {"updated_at": None, "count": 0, "leads": []}

newsletter_store = NewsletterStore()
