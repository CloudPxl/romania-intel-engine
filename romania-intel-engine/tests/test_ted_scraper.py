"""Tests for scrapers/ted_scraper.py and utils/bnr_currency.py.

Fixture payloads below are trimmed copies of real responses captured live
from `POST https://api.ted.europa.eu/v3/notices/search` (Romanian-buyer
notices, ND 449316-2026 / 4304-2026 / 16108-2026) and from
`https://curs.bnr.ro/nbrfxrates.xml` on 2026-08-31/2026-08-28 — see
scrapers/ted_scraper.py's and utils/bnr_currency.py's module docstrings
for the full verification trail. Not invented shapes: in particular,
`notice-title` really is a per-language *string* while
`organisation-name-buyer` really is a per-language *list* on the same
live response — a detail that broke a first draft of `_i18n_text()` and
is deliberately covered below rather than trusted to "look consistent".

Run with `pytest` from romania-intel-engine/ (no DATABASE_URL needed —
db.get_recent_opportunities() degrades to [] with no persistence
configured, exactly like the rest of this app).
"""

import xml.etree.ElementTree as ET

import httpx
import pytest

from scrapers import ted_scraper as mod
from scrapers.ted_scraper import (
    TedRomaniaScraper,
    _i18n_text,
    find_seap_cross_reference,
    match_seap_candidate,
)
from utils import bnr_currency

# --- Real, live-captured TED notices --------------------------------------

# Health, RON-denominated, form-type "competition" (a live open tender).
TED_ITEM_HEALTH_COMPETITION_RON = {
    "ND": "449316-2026",
    "publication-number": "449316-2026",
    "publication-date": "2026-07-01+02:00",
    "buyer-country": ["ROU"],
    "notice-type": "cn-standard",
    "form-type": "competition",
    "classification-cpv": ["33111650", "33111650"],
    "total-value": 1449834.71,
    "total-value-cur": ["RON"],
    "place-of-performance": ["RO321", "ROU", "RO321", "ROU"],
    "organisation-name-buyer": {
        "ron": ["Centrul Medical de Diagnostic, Tratament Ambulatoriu si Medicina Preventiva - Bucuresti"]
    },
    "notice-title": {
        "ron": "România – Aparate de mamografie – Mamograf digital cu modul de tomosinteza",
        "eng": "Romania – Mammography devices – Mamograf digital cu modul de tomosinteza",
    },
    "links": {"html": {"ENG": "https://ted.europa.eu/en/notice/449316-2026/html"}},
}

# Defence, EUR-denominated, form-type "result" (an award notice, multiple
# co-buyers — MApN units).
TED_ITEM_DEFENSE_AWARD_EUR = {
    "ND": "4304-2026",
    "publication-number": "4304-2026",
    "publication-date": "2026-01-06+01:00",
    "buyer-country": ["ROU"],
    "notice-type": "can-standard",
    "form-type": "result",
    "classification-cpv": ["44211100", "44211100"],
    "total-value": 12017083,
    "total-value-cur": ["EUR"],
    "place-of-performance": ["ROU"],
    "organisation-name-buyer": {
        "ron": [
            "MINISTERUL APARARII - UNITATEA MILITARA 02523",
            "Ministerul Apararii - Unitatea Militara 02444 Sibiu",
        ]
    },
    "notice-title": {
        "ron": "România – Construcţii modulare prefabricate – Achiziţionarea de structuri metalice tip container",
        "eng": "Romania – Modular and portable buildings – container structures",
    },
    "links": {"html": {"ENG": "https://ted.europa.eu/en/notice/4304-2026/html"}},
}

# IT/software, EUR-denominated — out of this scraper's declared domain
# scope (infra/defence/health/energy only) and must be dropped.
TED_ITEM_DIGITAL_OUT_OF_SCOPE = {
    "ND": "16108-2026",
    "publication-number": "16108-2026",
    "publication-date": "2026-01-12+01:00",
    "buyer-country": ["ROU"],
    "notice-type": "can-standard",
    "form-type": "result",
    "classification-cpv": ["48517000", "48517000"],
    "total-value": 1487860.32,
    "total-value-cur": ["EUR"],
    "organisation-name-buyer": {
        "ron": ["Autoritatea Nationala pentru Administrare si Reglementare in Comunicatii"]
    },
    "notice-title": {
        "ron": "România – Pachete software IT – Acord-cadru achiziție de licențe software Microsoft",
        "eng": "Romania – IT software package – Microsoft software licences framework agreement",
    },
    "links": {"html": {"ENG": "https://ted.europa.eu/en/notice/16108-2026/html"}},
}

REAL_BNR_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<DataSet xmlns="https://www.bnr.ro/xsd" xmlns:xsi="https://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="https://curs.bnr.ro/xsd/nbrfxrates.xsd"><Header><Publisher>National Bank of Romania</Publisher><PublishingDate>2026-08-28</PublishingDate><MessageType>DR</MessageType></Header><Body><Subject>Reference rates</Subject><OrigCurrency>RON</OrigCurrency><Cube date="2026-08-28"><Rate currency="AED">1.2299</Rate><Rate currency="EUR">5.2584</Rate><Rate currency="HUF" multiplier="100">1.4430</Rate><Rate currency="USD">4.5171</Rate></Cube></Body></DataSet>"""

FAKE_RATES = {"eur_ron": 5.2584, "usd_ron": 4.5171, "rate_date": "2026-08-28", "source": "live"}


class TestI18nText:
    def test_plain_string_field(self):
        # notice-title's per-language values are plain strings, live-verified.
        assert _i18n_text({"ron": "Titlu RO", "eng": "Title EN"}) == "Titlu RO"

    def test_list_valued_field(self):
        # organisation-name-buyer's per-language values are lists, live-verified.
        assert _i18n_text({"ron": ["Autoritatea A", "Autoritatea B"]}) == "Autoritatea A"

    def test_falls_back_to_english_then_anything(self):
        assert _i18n_text({"eng": "English only"}) == "English only"
        assert _i18n_text({"fra": "Francais seulement"}) == "Francais seulement"

    def test_empty_or_missing(self):
        assert _i18n_text({}) == ""
        assert _i18n_text(None) == ""
        assert _i18n_text("Plain string") == "Plain string"


class TestBuildSignal:
    @pytest.mark.asyncio
    async def test_health_competition_ron_no_conversion(self):
        scraper = TedRomaniaScraper()
        signal = await scraper._build_signal(TED_ITEM_HEALTH_COMPETITION_RON, FAKE_RATES)
        assert signal is not None
        assert signal.source_id == "TED-449316-2026"
        assert signal.category == "sanatate"
        assert signal.entity_name == "Centrul Medical de Diagnostic, Tratament Ambulatoriu si Medicina Preventiva - Bucuresti"
        assert signal.estimated_value_ron == 1449834.71  # RON passthrough, no rate applied
        assert signal.metadata["value"]["original_currency"] == "RON"
        assert "eur_ron_rate_used" not in signal.metadata["value"]
        assert signal.published_date == "2026-07-01"
        assert signal.metadata["procurement_stage"] == "in_procurement"
        assert signal.metadata["place_of_performance_nuts"] == ["RO321", "ROU", "RO321", "ROU"]
        assert signal.county == "Necunoscut"  # honestly unmapped, see module docstring
        assert signal.caen_codes == []
        assert signal.metadata["live_fetch_verified"] is True

    @pytest.mark.asyncio
    async def test_defence_award_eur_converted_via_bnr_rate(self):
        scraper = TedRomaniaScraper()
        signal = await scraper._build_signal(TED_ITEM_DEFENSE_AWARD_EUR, FAKE_RATES)
        assert signal is not None
        # Not "aparare": category_classifier.py's keyword list requires
        # the exact whole word "militar"/"aparare", and this real buyer
        # name/title only carry the inflected Romanian forms "militara"/
        # "apararii" (genitive/plural) — a pre-existing limitation of the
        # shared classifier (no stemming, just diacritic-folding) that
        # this scraper inherits rather than works around, since fixing it
        # would change classification for every other scraper that shares
        # it too. It falls through to the documented infrastructure
        # default instead, which is still inside ALLOWED_CATEGORIES.
        assert signal.category == "infrastructura"
        assert signal.entity_name == "MINISTERUL APARARII - UNITATEA MILITARA 02523"  # first co-buyer
        # 12017083 EUR * 5.2584 RON/EUR
        assert signal.estimated_value_ron == pytest.approx(12017083 * 5.2584, rel=1e-9)
        assert signal.metadata["value"]["original_currency"] == "EUR"
        assert signal.metadata["value"]["original_amount"] == 12017083
        assert signal.metadata["value"]["eur_ron_rate_used"] == 5.2584
        assert signal.metadata["value"]["rate_date"] == "2026-08-28"
        assert signal.metadata["procurement_stage"] == "awarded"

    @pytest.mark.asyncio
    async def test_out_of_scope_category_dropped(self):
        scraper = TedRomaniaScraper()
        signal = await scraper._build_signal(TED_ITEM_DIGITAL_OUT_OF_SCOPE, FAKE_RATES)
        assert signal is None  # digitalizare is out of this scraper's declared scope

    @pytest.mark.asyncio
    async def test_missing_id_or_title_returns_none(self):
        scraper = TedRomaniaScraper()
        assert await scraper._build_signal({"notice-title": {"ron": "x"}}, FAKE_RATES) is None
        assert await scraper._build_signal({"ND": "1-2026"}, FAKE_RATES) is None


class TestCurrencyConversion:
    def test_ron_passthrough(self):
        scraper = TedRomaniaScraper()
        value, meta = scraper._convert_to_ron(1000.0, "RON", FAKE_RATES)
        assert value == 1000.0
        assert meta["original_currency"] == "RON"

    def test_eur_conversion(self):
        scraper = TedRomaniaScraper()
        value, meta = scraper._convert_to_ron(1000.0, "EUR", FAKE_RATES)
        assert value == pytest.approx(5258.4)
        assert meta["eur_ron_rate_used"] == 5.2584

    def test_unsupported_currency_honestly_zeroed(self):
        scraper = TedRomaniaScraper()
        value, meta = scraper._convert_to_ron(1000.0, "USD", FAKE_RATES)
        assert value == 0.0
        assert meta["conversion"] == "unsupported_currency"

    def test_missing_amount_or_currency(self):
        scraper = TedRomaniaScraper()
        assert scraper._convert_to_ron(None, "EUR", FAKE_RATES)[0] == 0.0
        assert scraper._convert_to_ron(1000.0, None, FAKE_RATES)[0] == 0.0


class TestSeapCrossReferenceHeuristic:
    def _candidate(self, source_id="SEAP-CN1058291", cpv="44211100-1", value=12017083 * 5.2584, name="Ministerul Apararii - Unitatea Militara 02523"):
        return {"source_id": source_id, "cpv_code": cpv, "estimated_value_ron": value, "entity_name": name}

    def test_all_three_signals_agree(self):
        match = match_seap_candidate("44211100", 12017083 * 5.2584, "MINISTERUL APARARII - UNITATEA MILITARA 02523", self._candidate())
        assert match is not None
        assert match["matched_source_id"] == "SEAP-CN1058291"
        assert set(match["basis"]) == {"cpv_prefix", "value_within_tolerance", "buyer_name"}

    def test_only_one_signal_agrees_is_not_enough(self):
        # Same CPV prefix only — value and name both differ. A single
        # coincidental signal must not be treated as a real match.
        candidate = self._candidate(value=500.0, name="Cu totul altă autoritate")
        match = match_seap_candidate("44211100", 12017083 * 5.2584, "MINISTERUL APARARII - UNITATEA MILITARA 02523", candidate)
        assert match is None

    def test_two_of_three_is_enough(self):
        # CPV differs, but value and name both agree.
        candidate = self._candidate(cpv="99999999-9")
        match = match_seap_candidate("44211100", 12017083 * 5.2584, "MINISTERUL APARARII - UNITATEA MILITARA 02523", candidate)
        assert match is not None
        assert set(match["basis"]) == {"value_within_tolerance", "buyer_name"}

    def test_no_signals_agree(self):
        candidate = self._candidate(cpv="11111111-1", value=5.0, name="Nimic in comun")
        assert match_seap_candidate("44211100", 12017083 * 5.2584, "MINISTERUL APARARII", candidate) is None

    @pytest.mark.asyncio
    async def test_find_seap_cross_reference_degrades_to_none_with_no_db(self, monkeypatch):
        # No DATABASE_URL in test env -> db.get_recent_opportunities()
        # returns [] exactly like every other read in db.py without
        # persistence configured.
        result = await find_seap_cross_reference("44211100", 1000.0, "Some Authority")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_seap_cross_reference_uses_db_candidates(self, monkeypatch):
        async def fake_get_recent(limit=500):
            return [self._candidate()]

        monkeypatch.setattr(mod.db, "get_recent_opportunities", fake_get_recent)
        result = await find_seap_cross_reference(
            "44211100", 12017083 * 5.2584, "MINISTERUL APARARII - UNITATEA MILITARA 02523"
        )
        assert result is not None
        assert result["matched_source_id"] == "SEAP-CN1058291"


@pytest.mark.asyncio
async def test_fetch_market_consultations_stops_at_short_page(monkeypatch):
    """End-to-end pagination wiring, without touching the network: proves
    the loop stops once a page comes back shorter than page_size, and
    applies the same BNR rates fetched once per run to every item."""

    async def fake_post_json(client, url, body):
        assert body["query"].startswith("buyer-country = ROU AND form-type IN (planning, competition, result)")
        if body["page"] == 1:
            return {"notices": [TED_ITEM_HEALTH_COMPETITION_RON, TED_ITEM_DEFENSE_AWARD_EUR], "totalNoticeCount": 2}
        return {"notices": []}

    async def fake_get_rates(force_refresh=False):
        return FAKE_RATES

    monkeypatch.setattr(mod, "_post_json", fake_post_json)
    monkeypatch.setattr(bnr_currency, "get_rates", fake_get_rates)

    scraper = TedRomaniaScraper(page_size=2, max_pages=3)
    signals = await scraper.fetch_market_consultations()

    assert {s.source_id for s in signals} == {"TED-449316-2026", "TED-4304-2026"}


class TestBnrCurrency:
    def test_parses_real_live_xml(self):
        rates = bnr_currency._parse_rates_xml(REAL_BNR_XML)
        assert rates["eur_ron"] == 5.2584
        assert rates["usd_ron"] == 4.5171
        assert rates["rate_date"] == "2026-08-28"
        assert rates["source"] == "live"

    def test_multiplier_attribute_is_honoured(self):
        # HUF is quoted per 100 units on the real feed; not EUR/USD, but
        # the parser must not assume multiplier is always absent.
        xml = b"""<DataSet xmlns="https://www.bnr.ro/xsd"><Body><Cube date="2026-08-28">
            <Rate currency="EUR">5.0</Rate><Rate currency="USD">4.0</Rate>
            <Rate currency="HUF" multiplier="100">150.0</Rate>
        </Cube></Body></DataSet>"""
        rates = bnr_currency._parse_rates_xml(xml)
        assert rates["eur_ron"] == 5.0

    def test_malformed_xml_raises(self):
        with pytest.raises(ET.ParseError):
            bnr_currency._parse_rates_xml(b"not xml at all")

    def test_missing_eur_or_usd_raises(self):
        xml = b"""<DataSet xmlns="https://www.bnr.ro/xsd"><Body><Cube date="2026-08-28">
            <Rate currency="USD">4.0</Rate>
        </Cube></Body></DataSet>"""
        with pytest.raises(ValueError):
            bnr_currency._parse_rates_xml(xml)

    @pytest.mark.asyncio
    async def test_get_rates_falls_back_when_live_fetch_fails(self, monkeypatch):
        async def fake_fetch_live_rates():
            raise httpx.ConnectError("simulated network failure")

        # Force a fresh fetch (bypass any cache another test may have warmed).
        monkeypatch.setattr(bnr_currency, "_cache_rates", None)
        monkeypatch.setattr(bnr_currency, "_cache_at", 0.0)
        monkeypatch.setattr(bnr_currency, "_fetch_live_rates", fake_fetch_live_rates)

        rates = await bnr_currency.get_rates(force_refresh=True)
        assert rates["eur_ron"] == bnr_currency.FALLBACK_EUR_RON
        assert rates["usd_ron"] == bnr_currency.FALLBACK_USD_RON
        assert rates["source"] == f"fallback_offline_{bnr_currency.FALLBACK_RATE_DATE}"

    @pytest.mark.asyncio
    async def test_get_rates_uses_cache_within_ttl(self, monkeypatch):
        calls = {"n": 0}

        async def fake_fetch_live_rates():
            calls["n"] += 1
            return {"eur_ron": 5.1, "usd_ron": 4.4, "rate_date": "2026-08-31", "source": "live"}

        monkeypatch.setattr(bnr_currency, "_cache_rates", None)
        monkeypatch.setattr(bnr_currency, "_cache_at", 0.0)
        monkeypatch.setattr(bnr_currency, "_fetch_live_rates", fake_fetch_live_rates)

        first = await bnr_currency.get_rates(force_refresh=True)
        second = await bnr_currency.get_rates()  # should hit the cache, not fetch again
        assert first == second
        assert calls["n"] == 1
