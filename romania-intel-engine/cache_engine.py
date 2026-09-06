import os
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Dict, List

logger = logging.getLogger("CacheEngine")

# An expired entry used to be dropped only when that exact key was read
# again — so a user who browsed once and never returned left their cached
# feed in memory for the life of the process. Each entry is a full feed
# payload (up to 500 leads), which makes this a much faster leak than the
# one security.py already fixed in RATE_LIMIT_STORE, and the same fix
# applies: an opportunistic O(n) sweep every few minutes rather than a
# scan on every request.
CACHE_CLEANUP_INTERVAL_SECONDS = 300


class MemoryCacheEngine:
    def __init__(self, default_ttl_seconds: int = 90):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl_seconds
        self._last_cleanup_at = 0.0

    def _purge_expired(self, now: float) -> None:
        if now - self._last_cleanup_at < CACHE_CLEANUP_INTERVAL_SECONDS:
            return
        self._last_cleanup_at = now
        stale = [k for k, entry in self._cache.items() if now > entry["expires_at"]]
        for k in stale:
            del self._cache[k]
        if stale:
            logger.info(f"🧹 [Cache] Purged {len(stale)} expired entries ({len(self._cache)} live).")

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
        now = time.time()
        # Swept on write rather than on read: a read that misses is exactly
        # the case that is about to add an entry, and sweeping there would
        # not bound a store nobody reads from any more.
        self._purge_expired(now)
        self._cache[key] = {
            "value": value,
            "expires_at": now + ttl
        }

    def stats(self) -> Dict[str, int]:
        """Entry count only — the keys embed user ids, and /system/status
        is a public route."""
        return {"entries": len(self._cache)}

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
