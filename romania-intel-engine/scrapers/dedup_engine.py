import hashlib
import logging
from typing import List
from scrapers.models import RawInstitutionalSignal
from supabase import Client

logger = logging.getLogger("DedupEngine")

class IngestionDeduplicator:
    @staticmethod
    def generate_signal_hash(signal: RawInstitutionalSignal) -> str:
        raw = f"{signal.source_type}:{signal.entity_name}:{signal.project_title}:{signal.county}".lower()
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def filter_new_signals(signals: List[RawInstitutionalSignal], supabase: Client = None) -> List[RawInstitutionalSignal]:
        unique = {}
        for s in signals:
            if not s.source_id or len(s.source_id) < 5:
                s.source_id = f"SIG-{IngestionDeduplicator.generate_signal_hash(s)}"
            if s.source_id not in unique:
                unique[s.source_id] = s
        fresh = list(unique.values())
        if supabase:
            try:
                ids = [s.source_id for s in fresh]
                res = supabase.table("opportunities").select("source_id").in_("source_id", ids).execute()
                existing = {row["source_id"] for row in res.data}
                unprocessed = [s for s in fresh if s.source_id not in existing]
                logger.info(f"⚡ [Dedup] Filtered {len(signals)} -> {len(unprocessed)} new signals.")
                return unprocessed
            except Exception as e:
                logger.warning(f"[Dedup] DB check note: {e}")
        return fresh
