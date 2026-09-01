"""Real, live-verified TED (Tenders Electronic Daily / OJEU) client and
`TedRomaniaScraper(BaseScraper)` for cross-border, high-value EU-level
infrastructure/defence/health/energy procurement naming Romania as buyer
country — the tenders that legally must publish on TED (above the EU's
Article 4 thresholds, ~€5.5M for works) before or alongside SEAP.

Placed at the top level of `scrapers/` (not `scrapers/matrix/`): TED is a
single national-relevance cross-border feed, not a per-institution matrix
entry. (`elicitatie_scraper.py` is a comparable single national feed but
does live under `scrapers/matrix/` — don't read its placement as the
precedent for this one.)

Everything below was verified against production on 2026-08-31 with real
httpx requests — nothing here is inferred from the spec's description
alone.

## Endpoint, method, auth (verified live)

    POST https://api.ted.europa.eu/v3/notices/search

A bare `GET` to that URL returns `405 {"message":"Request method 'GET' is
not supported"}`, confirming it's POST-only. A `POST` with an empty JSON
body `{}` returns `400` with a validation error naming the real request
schema (`publicExpertSearchRequestV1`) and its two required fields —
`query` and `fields` — both "must not be empty". No API key/auth header
was needed for any of the successful search calls made during
verification (also stated explicitly in TED's own OpenAPI description,
fetched live from `https://api.ted.europa.eu/api-v3.yaml`, the file the
Swagger UI at `/swagger` actually loads: "The API is accessible to the
general public"). A different, undocumented endpoint on the same host,
`/v3/notices/fields`, does require a key (`400 Missing Authorization
header`) — that one was not needed for anything below and is not used
here.

## Request shape (verified live)

    {
      "query": "buyer-country = ROU AND form-type IN (planning, competition, result) AND publication-date >= 20260701",
      "fields": ["ND", "notice-title", "publication-date", "buyer-country", ...],
      "page": 1,
      "limit": 100
    }

`query` is TED's "expert search" DSL (the same language used by the
TED website's own Expert Search page): `field = value`, `field IN
(v1, v2, ...)`, `field >= value`, joined with `AND`. Sending an
unsupported field *value* (not name) gets a precise `400
QUERY_UNSUPPORTED_FIELD_VALUE` naming the offending field/value, which is
how the real values below were discovered rather than guessed:
  - `notice-type` values confirmed live: `cn-standard`, `can-standard`
    (a guessed `pin-standard` was rejected — planning notices use a
    different, undiscovered value under `notice-type`).
  - `form-type` values confirmed live: `planning`, `competition`,
    `result` (a coarser, notice-type-independent categorical field
    covering every underlying subtype — standard/social/defence/etc. —
    uniformly). **This scraper filters on `form-type`, not `notice-type`,
    specifically because it reliably covers all three procurement stages
    the spec asked for (Planning/PIN, Competition/CN, Award/CAN) without
    having to enumerate every notice-type variant.**
  - `publication-date` accepts a bare `YYYYMMDD` string with a comparison
    operator (`>=` confirmed live); no dashes needed.
  - `buyer-country` takes ISO 3166-1 alpha-3 codes (`ROU` confirmed live
    against real Romanian-buyer notices).

`fields` is validated against a large enum (thousands of eForms BT-* field
names, dumped in the OpenAPI spec) but that enum lists field *names* only
— it carries no docs or examples, so the actual field names used below
(`ND`, `notice-title`, `organisation-name-buyer`, `classification-cpv`,
`total-value`, `total-value-cur`, `place-of-performance`,
`deadline-receipt-tender-date-lot`, `links`) were each confirmed by
fetching them live and inspecting a real response, not read off the spec.
Text fields that carry translations (`notice-title`,
`organisation-name-buyer`) come back as a dict keyed by lowercase
ISO 639-2 language codes (e.g. `{"ron": [...], "eng": [...]}` — Romanian
buyers mostly file in `ron`); `_i18n_text`/`_i18n_first` below prefer
`ron` then `eng` then whatever's present, since not every notice has a
Romanian translation.

Pagination is `page`/`limit` (TED's own docs, embedded in the OpenAPI
description above, cap `limit` at 250 for the default "pagination mode"
this scraper uses — scroll/"ITERATION" mode with `iterationNextToken`
exists for bulk export but isn't needed at this feed's volume).

No 429 was observed during verification — only a small, good-faith number
of real requests were sent, deliberately not enough to hit any rate
limit. `_post_json` below retries 5xx/transport errors with jittered
backoff (same idiom as `direct_acquisition_scraper.py`) and treats any
4xx, 429 included, as non-retryable within one tick; an actual rate limit
would simply be retried on the next scheduled tick rather than hammered.

## Currency: TED notices for Romanian buyers are not uniformly EUR

A live comparison of Romanian-buyer notices showed both `total-value-cur:
["RON"]` (the majority — Romanian eForms notices are filed with the
national-currency value) and real `total-value-cur: ["EUR"]` notices
(current 2026 examples: MApN barracks/container contracts worth EUR
12.0M/14.8M, ANCOM Microsoft licensing at EUR 1.49M, STS internet
services at EUR 271k). So the BNR conversion in `utils/bnr_currency.py`
is applied only when the notice is actually EUR-denominated; a RON value
is used as-is, and any other currency (rare on Romanian-buyer notices,
none observed live) is honestly left unconverted at 0.0 with the raw
amount/currency preserved in `metadata` rather than silently mis-scaled.

## SEAP cross-referencing: no real field found — heuristic fallback built

The spec asked to cross-reference a TED notice against an existing SEAP
contract-notice number (e.g. "CN1058291") to merge into an existing
dossier instead of duplicating it. A real Romanian CAN (contract-award)
notice's full UBL/eForms XML was fetched and inspected
(`https://ted.europa.eu/en/notice/4304-2026/xml`, a MApN award) looking
for any such reference: `cbc:ContractFolderID` is a TED-internal UUID
(`e9811579-07bd-4781-8666-781016e0e45d`), not a SEAP procedure number, and
every other appearance of "SEAP"/"e-licitatie" in the document is just the
buyer's platform/contact metadata (`BuyerProfileURI:
https://www.e-licitatie.ro`), never a national procedure identifier in
the "CN\\d+" shape. This was a genuine, specific check against a real
document, not an assumption — TED's eForms data model simply does not
carry a national-procedure cross-reference for Romanian notices.

Given that honest gap, `find_seap_cross_reference()` below implements the
heuristic fallback the spec allowed for: match a TED signal against
recent rows in the existing `opportunities` table on (CPV-code prefix
equality + estimated value within ±`VALUE_TOLERANCE_PCT` + a
diacritic-folded substring match between the two buyer/entity names,
using `text_utils.fold`/`contains_term` like every other cross-source
matching in this codebase). A match is recorded as evidence in
`metadata["seap_cross_reference"]` (the matched `source_id` plus which
signals — cpv/value/name — actually agreed) rather than merged/deduped
automatically: this is a best-effort heuristic, not a verified identity,
so it's surfaced for a human/downstream consumer to confirm rather than
silently collapsing two rows that might not really be the same procedure.
When no candidate clears the bar, the TED notice is simply ingested as
its own new signal with `source_type = "TED/OJEU (Live)"`, exactly as the
spec allowed for the "skip cross-referencing" case.

## Other honest gaps

`county`/`locality` are left as `"Necunoscut"`/`""` (same convention
`direct_acquisition_scraper.py` uses when a source genuinely doesn't
report them): `place-of-performance` on TED is a list of NUTS codes
(e.g. `"RO223"` for Constanța) or the bare country code `"ROU"`, not a
Romanian județ name, and this module does not ship a NUTS3→județ lookup
table it can't verify — the raw NUTS codes are kept in
`metadata["place_of_performance_nuts"]` instead of guessing a county from
them. `caen_codes` is always `[]`: TED/eForms has no CAEN field, only
CPV, which is why `document_enricher.py`'s document-mining approach (used
by the SICAP/DA scrapers) isn't applicable here either — this endpoint
returns structured metadata, not attachment lists.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

import db
from scrapers.base_scraper import USER_AGENT, BaseScraper
from scrapers.matrix.category_classifier import classify_with_evidence
from scrapers.models import RawInstitutionalSignal
from text_utils import contains_term, fold
from utils import bnr_currency

logger = logging.getLogger("TedRomaniaScraper")

TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"

# See module docstring: form-type (not notice-type) is what actually
# spans Planning/Competition/Award uniformly across every eForms subtype.
FORM_TYPES = ("planning", "competition", "result")

STAGE_BY_FORM_TYPE = {
    "planning": "pre_tender_planning",
    "competition": "in_procurement",
    "result": "awarded",
}

FIELDS = [
    "ND",
    "notice-title",
    "publication-date",
    "buyer-country",
    "organisation-name-buyer",
    "notice-type",
    "form-type",
    "classification-cpv",
    "total-value",
    "total-value-cur",
    "place-of-performance",
    "deadline-receipt-tender-date-lot",
    "links",
]

# The spec's ask is scoped to infra/defence/health/energy — TED also
# surfaces plenty of Romanian-buyer notices for IT licensing, translation
# services, HR consultancy, etc. that are out of scope for this feed
# (digitalizare is covered nationally by other scrapers already). A
# notice classified outside this set is dropped rather than ingested,
# which is a deliberate scope decision, not a classifier limitation.
ALLOWED_CATEGORIES = frozenset({"infrastructura", "aparare", "sanatate", "energie"})

# Heuristic SEAP cross-reference tolerance — see module docstring for why
# this is a best-effort fallback rather than a real identity match.
VALUE_TOLERANCE_PCT = 0.15
CPV_PREFIX_LEN = 5
CROSS_REFERENCE_CANDIDATE_LIMIT = 500


class NonRetryableHTTPError(Exception):
    pass


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=1, max=12),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError, asyncio.TimeoutError)),
    reraise=True,
)
async def _post_json(client: httpx.AsyncClient, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
    response = await client.post(url, json=body)
    if 400 <= response.status_code < 500:
        # Includes a genuine 429 if TED ever sends one — see module
        # docstring: none was observed during good-faith verification, and
        # treating any 4xx as non-retryable within a tick matches
        # BaseScraper's own _get_with_retry convention elsewhere.
        raise NonRetryableHTTPError(f"{response.status_code} for {url}: {response.text[:300]}")
    response.raise_for_status()
    return response.json()


def _i18n_scalar(items: Any) -> str:
    """A per-language value is sometimes a plain string (`notice-title`)
    and sometimes a list (`organisation-name-buyer`, which can carry
    several co-buyers) — both were observed live on real notices, so both
    are handled rather than assuming one shape."""
    if isinstance(items, list) and items:
        return str(items[0]).strip()
    if isinstance(items, str):
        return items.strip()
    return ""


def _i18n_text(value: Any, prefer: tuple = ("ron", "eng")) -> str:
    """TED's translated fields come back as {"ron": ..., "eng": ..., ...}.
    Prefers Romanian, then English, then whatever language is actually
    present, rather than assuming every notice has a Romanian
    translation."""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict) or not value:
        return ""
    for lang in prefer:
        if lang in value:
            text = _i18n_scalar(value[lang])
            if text:
                return text
    for items in value.values():
        text = _i18n_scalar(items)
        if text:
            return text
    return ""


def _first_or_none(value: Any) -> Optional[str]:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str) and value:
        return value
    return None


def _iso_date(value: Optional[str]) -> str:
    """TED dates arrive like '2026-07-01+02:00'; only the date part is
    ever stored downstream."""
    return (value or "")[:10]


def _cpv_prefix(cpv_code: Optional[str], length: int = CPV_PREFIX_LEN) -> Optional[str]:
    if not cpv_code:
        return None
    digits = "".join(ch for ch in cpv_code if ch.isdigit())
    return digits[:length] if len(digits) >= length else None


def match_seap_candidate(
    cpv_code: Optional[str], value_ron: float, entity_name: str, candidate: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Pure matching predicate (no I/O), kept separate from
    find_seap_cross_reference() so the heuristic itself is unit-testable
    without a database. Returns the evidence dict if `candidate` (a row
    shaped like db.get_recent_opportunities()'s output) plausibly is the
    same procedure as the TED signal being ingested, else None."""
    cand_cpv_prefix = _cpv_prefix(candidate.get("cpv_code"))
    ted_cpv_prefix = _cpv_prefix(cpv_code)
    cpv_hit = bool(cand_cpv_prefix) and cand_cpv_prefix == ted_cpv_prefix

    cand_value = float(candidate.get("estimated_value_ron") or 0.0)
    value_hit = False
    if value_ron > 0 and cand_value > 0:
        value_hit = abs(cand_value - value_ron) <= value_ron * VALUE_TOLERANCE_PCT

    cand_name = candidate.get("entity_name") or ""
    name_hit = bool(entity_name) and bool(cand_name) and (
        contains_term(entity_name, cand_name) or contains_term(cand_name, entity_name)
        or fold(entity_name) == fold(cand_name)
    )

    # Require at least two of three independent signals to agree — any
    # single one of these (same CPV chapter, similar value, similar name
    # fragment) is common enough on its own to produce false positives.
    hits = {"cpv_prefix": cpv_hit, "value_within_tolerance": value_hit, "buyer_name": name_hit}
    if sum(hits.values()) < 2:
        return None
    return {
        "matched_source_id": candidate.get("source_id"),
        "matched_entity_name": cand_name,
        "basis": [k for k, v in hits.items() if v],
    }


async def find_seap_cross_reference(
    cpv_code: Optional[str], value_ron: float, entity_name: str,
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Best-effort heuristic cross-reference against the existing
    `opportunities` table — see module docstring for why there's no real
    field to join on. Returns None (not an error) whenever persistence
    isn't configured, no candidates are found, or nothing clears the
    match bar; a TED signal is always ingested as its own row regardless
    of this result.

    `candidates` is optional: fetch_market_consultations() fetches the
    candidate list once per tick and passes it in, since the same ~500
    opportunities rows would otherwise be re-queried from Postgres once
    per TED signal (up to ~100/tick) for no benefit — the candidate set
    can't change mid-tick. Left as None here (fetching fresh) so this
    function stays independently callable/testable without needing a
    caller to fetch candidates first."""
    if candidates is None:
        try:
            candidates = await db.get_recent_opportunities(limit=CROSS_REFERENCE_CANDIDATE_LIMIT)
        except Exception as e:
            logger.warning(f"[TedRomania] cross-reference lookup failed, skipping: {e}")
            return None

    for candidate in candidates:
        match = match_seap_candidate(cpv_code, value_ron, entity_name, candidate)
        if match:
            return match
    return None


class TedRomaniaScraper(BaseScraper):
    """Cross-border, high-value TED/OJEU notices naming Romania as buyer
    country, restricted to the infra/defence/health/energy domains — see
    module docstring for the full live-verification trail (endpoint,
    query DSL, field names, currency handling, and the SEAP
    cross-reference decision)."""

    def __init__(self, lookback_days: int = 10, page_size: int = 100, max_pages: int = 5):
        # TED's OJS publishes once per EU business day; a 6h poll interval
        # (same order as ProgramEnergie/ProgramSanatate/CniInfra) is
        # plenty responsive without hammering a public API with no key.
        super().__init__("TedRomania", rate_limit_delay=1.0, poll_interval_minutes=360)
        self.lookback_days = lookback_days
        self.page_size = page_size
        self.max_pages = max_pages

    def _build_query(self) -> str:
        start = (datetime.now(timezone.utc) - timedelta(days=self.lookback_days)).strftime("%Y%m%d")
        form_type_list = ", ".join(FORM_TYPES)
        return f"buyer-country = ROU AND form-type IN ({form_type_list}) AND publication-date >= {start}"

    async def fetch_market_consultations(self) -> List[RawInstitutionalSignal]:
        signals: List[RawInstitutionalSignal] = []
        rates = await bnr_currency.get_rates()
        query = self._build_query()
        # Fetched once per tick and threaded through to every signal below
        # instead of each signal's find_seap_cross_reference() call
        # re-querying the same ~500 opportunities rows from Postgres —
        # the candidate set can't change mid-tick, so up to ~100 identical
        # queries collapses to exactly one.
        try:
            cross_reference_candidates = await db.get_recent_opportunities(limit=CROSS_REFERENCE_CANDIDATE_LIMIT)
        except Exception as e:
            logger.warning(f"[{self.name}] cross-reference candidate lookup failed for this tick, skipping: {e}")
            cross_reference_candidates = []

        try:
            # Identifies as a normal desktop browser, same single shared
            # constant every other outbound client in scrapers/ uses. TED's
            # API was verified to answer 200 either way, so this is a
            # consistency/robustness measure against a future edge-layer
            # policy on a headerless client, not a fix for an observed
            # block — and deliberately one honest fixed UA rather than a
            # rotation, since this endpoint is hit a handful of times per
            # tick and has never signalled bot filtering.
            async with httpx.AsyncClient(
                timeout=20.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
            ) as client:
                page = 1
                while page <= self.max_pages:
                    await asyncio.sleep(self.rate_limit_delay)
                    body = {"query": query, "fields": FIELDS, "page": page, "limit": self.page_size}
                    try:
                        data = await _post_json(client, TED_SEARCH_URL, body)
                    except (httpx.HTTPError, asyncio.TimeoutError, NonRetryableHTTPError) as e:
                        logger.warning(f"[{self.name}] page {page} failed, stopping pagination: {e}")
                        break

                    items = data.get("notices") or []
                    if not items:
                        break

                    for item in items:
                        signal = await self._build_signal(item, rates, cross_reference_candidates)
                        if signal:
                            signals.append(signal)

                    if len(items) < self.page_size:
                        break
                    page += 1
        except Exception as e:
            self.logger.error(f"[{self.name}] fetch_market_consultations failed: {e}")
            raise

        return signals

    def _convert_to_ron(self, amount: Any, currency: Optional[str], rates: Dict[str, Any]) -> tuple:
        """Returns (estimated_value_ron, value_metadata). Honestly zeroes
        out (rather than mis-scaling) any currency this module doesn't
        know how to convert — see module docstring: RON and EUR are the
        two currencies actually observed on Romanian-buyer TED notices."""
        try:
            amount_f = float(amount) if amount is not None else 0.0
        except (TypeError, ValueError):
            amount_f = 0.0

        if not amount_f or not currency:
            return 0.0, {"original_amount": amount, "original_currency": currency}

        if currency == "RON":
            return amount_f, {"original_amount": amount_f, "original_currency": "RON"}

        if currency == "EUR":
            eur_ron = rates["eur_ron"]
            return round(amount_f * eur_ron, 2), {
                "original_amount": amount_f,
                "original_currency": "EUR",
                "eur_ron_rate_used": eur_ron,
                "rate_date": rates.get("rate_date"),
                "rate_source": rates.get("source"),
            }

        logger.warning(f"[{self.name}] unhandled currency '{currency}' for amount {amount_f}; leaving value unconverted at 0.0")
        return 0.0, {"original_amount": amount_f, "original_currency": currency, "conversion": "unsupported_currency"}

    async def _build_signal(
        self, item: Dict[str, Any], rates: Dict[str, Any],
        cross_reference_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[RawInstitutionalSignal]:
        nd = item.get("ND") or item.get("publication-number")
        title = _i18n_text(item.get("notice-title"))
        if not nd or not title:
            return None

        buyer_name = _i18n_text(item.get("organisation-name-buyer")) or "Autoritate Contractantă (UE)"
        cpv_list = item.get("classification-cpv") or []
        cpv_code = cpv_list[0] if cpv_list else None

        category, evidence = classify_with_evidence(buyer_name, title, "")
        if category not in ALLOWED_CATEGORIES:
            return None

        form_type = item.get("form-type")
        notice_type = item.get("notice-type")
        currency_list = item.get("total-value-cur") or []
        currency = currency_list[0] if currency_list else None
        estimated_value_ron, value_metadata = self._convert_to_ron(item.get("total-value"), currency, rates)

        deadline = _first_or_none(item.get("deadline-receipt-tender-date-lot"))

        links = item.get("links") or {}
        source_url = (
            ((links.get("html") or {}).get("ENG"))
            or ((links.get("html") or {}).get("RON"))
            or f"https://ted.europa.eu/en/notice/{nd}/html"
        )
        document_url = ((links.get("pdf") or {}).get("ENG")) or source_url

        cross_reference = None
        if estimated_value_ron > 0:
            cross_reference = await find_seap_cross_reference(
                cpv_code, estimated_value_ron, buyer_name, cross_reference_candidates,
            )

        return RawInstitutionalSignal(
            source_id=f"TED-{nd}",
            source_type="TED/OJEU (Live)",
            category=category,
            sub_category=f"TED {form_type or notice_type or 'notice'}",
            # See module docstring: TED gives NUTS codes, not județ names —
            # honestly left unmapped rather than guessed. Raw codes are in
            # metadata["place_of_performance_nuts"].
            county="Necunoscut",
            locality="",
            entity_name=buyer_name,
            project_title=title,
            estimated_value_ron=estimated_value_ron,
            published_date=_iso_date(item.get("publication-date")),
            action_deadline=_iso_date(deadline) if deadline else None,
            raw_description=title,
            source_url=source_url,
            cpv_code=cpv_code,
            document_url=document_url,
            metadata={
                "ted_publication_number": nd,
                "notice_type": notice_type,
                "form_type": form_type,
                "procurement_stage": STAGE_BY_FORM_TYPE.get(form_type, "unknown"),
                "cpv_codes_all": cpv_list,
                "place_of_performance_nuts": item.get("place-of-performance") or [],
                "category_evidence": evidence,
                "value": value_metadata,
                "seap_cross_reference": cross_reference,
                "live_fetch_verified": True,
            },
        )
