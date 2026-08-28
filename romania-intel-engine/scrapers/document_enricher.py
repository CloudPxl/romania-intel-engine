import re
import logging
from typing import List, Optional, Dict, Any

import httpx

from addons.caiet_analyzer import CaietDeSarciniAnalyzer

logger = logging.getLogger("DocumentEnricher")

MAX_DOCUMENTS = 2
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
DOWNLOAD_TIMEOUT = 20.0

# CAEN codes classify the *bidder*, not the tender, so they aren't a native
# e-licitatie listing field — this is best-effort text-mining of attached
# specification documents, not a guaranteed field on every opportunity.
CAEN_PATTERN = re.compile(r"\bCAEN\b[^\d]{0,20}(\d{4})", re.IGNORECASE)


async def extract_caen_codes_from_documents(
    client: httpx.AsyncClient,
    documents: List[Dict[str, Any]],
    download_url_builder,
) -> List[str]:
    """documents: [{"documentID": int, "documentName": str}, ...]
    download_url_builder(document_id) -> (method, url) for fetching that doc's bytes.
    Caps to MAX_DOCUMENTS files, MAX_DOCUMENT_BYTES each, and fails soft —
    a broken/oversized document never aborts the surrounding scrape."""
    caen_codes = set()
    for doc in documents[:MAX_DOCUMENTS]:
        try:
            method, url = download_url_builder(doc["documentID"])
            resp = await client.request(method, url, timeout=DOWNLOAD_TIMEOUT)
            resp.raise_for_status()
            if len(resp.content) > MAX_DOCUMENT_BYTES:
                continue
            text = CaietDeSarciniAnalyzer.extract_text_from_file(resp.content, doc.get("documentName", "document.pdf"))
            for m in CAEN_PATTERN.finditer(text):
                caen_codes.add(m.group(1))
        except Exception as e:
            logger.warning(f"[DocumentEnricher] Failed to enrich document {doc.get('documentID')}: {e}")
    return sorted(caen_codes)
