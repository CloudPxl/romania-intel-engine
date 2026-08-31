"""BNR (Banca Națională a României) reference exchange rates.

Live endpoint verified 2026-08-31 by fetching it directly:

    https://curs.bnr.ro/nbrfxrates.xml

Note the host: **not** `www.bnr.ro`. The commonly-cited
`https://www.bnr.ro/nbrfxrates.xml` (and every path variant tried under
`www.bnr.ro`, including the one linked from BNR's own
"Cursurile pieței valutare în format XML" page) 302-redirects to the BNR
homepage behind that host's bot-mitigation layer (F5/TS session cookies) —
confirmed by direct request, not assumed from a stale blog post. The BNR
homepage itself links to `23988-cursurile-pietei-valutare-in-format-xml`,
whose actual body is a JS-hydrated shell with no static link to the feed;
the working `curs.bnr.ro` subdomain was found via a live web search rather
than being guessable from the site itself. If this endpoint ever moves
again, re-verify with a plain `curl` before trusting any cached knowledge
of the URL.

A real fetch on 2026-08-31 (publishing date 2026-08-28, the last business
day) returned:

    <?xml version="1.0" encoding="utf-8"?>
    <DataSet xmlns="https://www.bnr.ro/xsd" ...>
      <Header><Publisher>National Bank of Romania</Publisher>
        <PublishingDate>2026-08-28</PublishingDate><MessageType>DR</MessageType></Header>
      <Body><Subject>Reference rates</Subject><OrigCurrency>RON</OrigCurrency>
        <Cube date="2026-08-28">
          <Rate currency="EUR">5.2584</Rate>
          <Rate currency="USD">4.5171</Rate>
          <Rate currency="HUF" multiplier="100">1.4430</Rate>
          ...
        </Cube>
      </Body>
    </DataSet>

`multiplier` is only present on currencies quoted per 100 units (HUF, JPY,
ISK, IDR, KRW, ...) — absent (i.e. 1) for EUR/USD, but the parser below
reads it defensively for every currency rather than assuming that holds
forever.

Same in-memory TTL-cache idiom as `scrapers/matrix/cni_common.py`
(`_cache_rows`/`_cache_at`/`asyncio.Lock`), reused here rather than
inventing a new caching pattern: one shared 24h-TTL cache so every caller
within a day reuses one HTTP fetch instead of hitting BNR per request.
BNR publishes once per business day, so a 24h TTL never serves a rate
older than the freshest one available anyway.

Resilience: on fetch/parse failure, a hardcoded offline fallback is used
instead of raising — converting an EU-denominated TED value into RON is
better done with a slightly stale rate than not done at all, and every
caller of `get_eur_ron_rate()`/`get_usd_ron_rate()` needs a number instead
of an exception. The fallback is the exact pair captured live above
(EUR/RON 5.2584, USD/RON 4.5171, published 2026-08-28) — a real historical
BNR rate, not an invented one — and every use of it is logged as a
warning and labelled `"source": "fallback_offline_2026-08-28"` in the
returned rates dict, so nothing downstream can mistake it for a live
quote. A fallback result is cached for only 15 minutes rather than the
full 24h — see `_FALLBACK_CACHE_TTL_SECONDS`: it is a retry window, so a
short BNR outage does not pin conversions to the offline rate for a day.
"""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("BnrCurrency")

BNR_XML_URL = "https://curs.bnr.ro/nbrfxrates.xml"
_XML_NAMESPACE = {"ns": "https://www.bnr.ro/xsd"}
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# A real BNR quote, live-verified on 2026-08-31 (see module docstring) —
# not an estimate. Used only when the live fetch/parse fails.
FALLBACK_RATE_DATE = "2026-08-28"
FALLBACK_EUR_RON = 5.2584
FALLBACK_USD_RON = 4.5171
_FALLBACK_SOURCE_LABEL = f"fallback_offline_{FALLBACK_RATE_DATE}"

_CACHE_TTL_SECONDS = 24 * 60 * 60
# A fallback result is cached far more briefly than a live one: it is not a
# quote, it is the absence of one. At the full 24h TTL a single failed fetch
# pinned every conversion to the offline rate for a whole day even if BNR
# came back a minute later. Not caching it at all would swing the other way
# and pay the 15s HTTP timeout on every single call for the duration of an
# outage, so this is a retry window, not a cache lifetime.
_FALLBACK_CACHE_TTL_SECONDS = 15 * 60
_cache_rates: Optional[Dict[str, Any]] = None
_cache_at: float = 0.0
_cache_lock = asyncio.Lock()


def _parse_rates_xml(xml_bytes: bytes) -> Dict[str, Any]:
    """Raises on any malformed/unexpected document rather than returning a
    partial result — the caller decides what to do (fall back) on failure,
    this function never silently guesses a rate."""
    root = ET.fromstring(xml_bytes)
    cube = root.find(".//ns:Body/ns:Cube", _XML_NAMESPACE)
    if cube is None:
        raise ValueError("nbrfxrates.xml: no <Cube> element found")

    rate_date = cube.get("date") or ""
    rates: Dict[str, float] = {}
    for rate_el in cube.findall("ns:Rate", _XML_NAMESPACE):
        currency = rate_el.get("currency")
        text = rate_el.text
        if not currency or not text:
            continue
        multiplier = float(rate_el.get("multiplier") or 1)
        rates[currency] = float(text) / multiplier

    if "EUR" not in rates or "USD" not in rates:
        raise ValueError(f"nbrfxrates.xml: missing EUR/USD in parsed rates {list(rates.keys())}")

    return {
        "eur_ron": rates["EUR"],
        "usd_ron": rates["USD"],
        "rate_date": rate_date,
        "source": "live",
    }


async def _fetch_live_rates() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT}) as client:
        response = await client.get(BNR_XML_URL)
        response.raise_for_status()
        return _parse_rates_xml(response.content)


def _fallback_rates() -> Dict[str, Any]:
    logger.warning(
        f"[BnrCurrency] Using stale offline fallback rates (EUR/RON {FALLBACK_EUR_RON}, "
        f"USD/RON {FALLBACK_USD_RON}, dated {FALLBACK_RATE_DATE}) — live BNR fetch failed."
    )
    return {
        "eur_ron": FALLBACK_EUR_RON,
        "usd_ron": FALLBACK_USD_RON,
        "rate_date": FALLBACK_RATE_DATE,
        "source": _FALLBACK_SOURCE_LABEL,
    }


async def get_rates(force_refresh: bool = False) -> Dict[str, Any]:
    """Returns {"eur_ron": float, "usd_ron": float, "rate_date": "YYYY-MM-DD",
    "source": "live" | "fallback_offline_<date>"} — cached in-process for
    up to 24h, same TTL-cache idiom as cni_common.py's `_fetch_all_rows`,
    except that a fallback result is only held for
    `_FALLBACK_CACHE_TTL_SECONDS` so the first caller after a brief BNR
    outage gets a live rate again instead of the offline one.
    Never raises: a live-fetch failure degrades to the hardcoded fallback
    rather than propagating, since every caller just needs a number."""
    global _cache_rates, _cache_at
    async with _cache_lock:
        if not force_refresh and _cache_rates is not None:
            ttl = _CACHE_TTL_SECONDS if _cache_rates.get("source") == "live" else _FALLBACK_CACHE_TTL_SECONDS
            if (time.monotonic() - _cache_at) < ttl:
                return _cache_rates

        try:
            rates = await _fetch_live_rates()
        except Exception as e:
            logger.error(f"[BnrCurrency] Live fetch of {BNR_XML_URL} failed: {e}")
            rates = _fallback_rates()

        _cache_rates, _cache_at = rates, time.monotonic()
        return rates


async def get_eur_ron_rate() -> float:
    rates = await get_rates()
    return rates["eur_ron"]


async def get_usd_ron_rate() -> float:
    rates = await get_rates()
    return rates["usd_ron"]
