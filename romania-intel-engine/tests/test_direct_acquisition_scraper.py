"""Tests for scrapers/matrix/direct_acquisition_scraper.py and
procurement_notices.py.

Fixture payloads below are trimmed copies of real responses captured live
from e-licitatie.ro's api-pub/DirectAcquisitionCommon and
api-pub/DaAwardNoticeCommon endpoints on 2026-08-31 (see the scraper
module's docstring) — not invented shapes. There is deliberately no
fixture for CN/SC/CAN-general/MC here: this suite only covers the notice
types this module actually ingests. Run with `pytest` from
romania-intel-engine/ (no DATABASE_URL needed — persistence degrades to a
no-op exactly like the rest of the app when it's unset, which is also
what lets these tests run without a real database).
"""

import pytest

from procurement_notices import ProcurementNotice, split_cui_and_name
from scrapers.matrix.direct_acquisition_scraper import DaAwardNoticeScraper, DirectAcquisitionScraper

REAL_DA_ITEM_OPEN = {
    "directAcquisitionId": 103063481,
    "directAcquisitionName": "Anvelopa 185/65R15 88T vara Matador MP47",
    "sysDirectAcquisitionState": {"id": 5, "text": "Publicat", "localeKey": None},
    "uniqueIdentificationCode": "DA22780457",
    "cpvCode": "34351100-3 - Pneuri pentru autovehicule (Rev.2)",
    "publicationDate": "2019-04-08T14:17:43+03:00",
    "finalizationDate": None,
    "caDecisionDeadline": "2019-04-13T17:00:00+03:00",
    "supplierDecisionDeadline": "2019-04-17T17:00:00+03:00",
    "supplier": None,
    "contractingAuthority": "4317975 Unitatea Militara 01714",
    "estimatedValueRon": 1132.16,
    "estimatedValueOtherCurrency": 238.31,
    "closingValue": None,
}

REAL_DA_ITEM_CLOSED = {
    **REAL_DA_ITEM_OPEN,
    "sysDirectAcquisitionState": {"id": 7, "text": "Oferta acceptata", "localeKey": None},
    "supplier": "RO 6865630 DELTA PLUS TRADING S.R.L.",
    "closingValue": 1000.0,
}

REAL_DA_AWARD_ITEM = {
    "daAwardNoticeId": 100000001,
    "contractObject": "SERVICII DE TRANSMITERE TELEVIZATA IN DIRECT A SEDINTELOR CONSILIULUI LOCAL MOTRU - 27 SEDINTE",
    "noticeNo": "DAN1000002",
    "sysNoticeState": {"id": 2, "text": "Publicat", "localeKey": None},
    "supplier": "RO27655088 SUD MEDIA PRODUCTION",
    "contractingAuthority": "5455844 MUNICIPIUL MOTRU",
    "cpvCode": "64228100-1 - Transmisie de programe de televiziune (Rev.2)",
    "cpvCategory": "SERVICII ",
    "publicationDate": "2018-04-02T11:53:49+03:00",
    "awardedValue": 113400.0,
}


class TestSplitCuiAndName:
    def test_ro_prefixed(self):
        cui, name = split_cui_and_name("RO 6865630 DELTA PLUS TRADING S.R.L.")
        assert cui == "6865630"
        assert name == "DELTA PLUS TRADING S.R.L."

    def test_no_ro_prefix(self):
        cui, name = split_cui_and_name("4317975 Unitatea Militara 01714")
        assert cui == "4317975"
        assert name == "Unitatea Militara 01714"

    def test_no_leading_digits_falls_back_to_whole_string(self):
        cui, name = split_cui_and_name("Some Authority Without A Cui")
        assert cui is None
        assert name == "Some Authority Without A Cui"

    def test_empty(self):
        assert split_cui_and_name(None) == (None, "")
        assert split_cui_and_name("") == (None, "")


class TestDirectAcquisitionScraper:
    def test_build_signal_open_item(self):
        scraper = DirectAcquisitionScraper()
        signal = scraper._build_signal(REAL_DA_ITEM_OPEN)
        assert signal is not None
        assert signal.source_id == "SEAP-DA-DA22780457"
        assert signal.entity_name == "Unitatea Militara 01714"
        assert signal.estimated_value_ron == 1132.16
        assert signal.published_date == "2019-04-08"
        assert signal.metadata["contracting_authority_cui"] == "4317975"
        assert signal.metadata["live_fetch_verified"] is True

    def test_build_signal_missing_id_returns_none(self):
        scraper = DirectAcquisitionScraper()
        assert scraper._build_signal({"directAcquisitionName": "x"}) is None
        assert scraper._build_signal({"directAcquisitionId": 1}) is None  # no title

    def test_build_notice_open_item_has_no_award(self):
        scraper = DirectAcquisitionScraper()
        notice = scraper._build_notice(REAL_DA_ITEM_OPEN)
        assert isinstance(notice, ProcurementNotice)
        assert notice.notice_type == "DA"
        assert notice.award_details is None  # no supplier/closingValue yet — honestly absent, not fabricated
        assert notice.contracting_authority.cui == "4317975"
        assert notice.caen_codes == []
        assert notice.raw_attachments == []

    def test_build_notice_closed_item_has_award_with_discount(self):
        scraper = DirectAcquisitionScraper()
        notice = scraper._build_notice(REAL_DA_ITEM_CLOSED)
        assert notice.award_details is not None
        assert notice.award_details.winning_bidder_cui == "6865630"
        assert notice.award_details.winning_bidder_name == "DELTA PLUS TRADING S.R.L."
        assert notice.award_details.awarded_value_ron == 1000.0
        # (1132.16 - 1000) / 1132.16 * 100 ≈ 11.68%
        assert notice.award_details.discount_pct == pytest.approx(11.68, abs=0.01)


class TestDaAwardNoticeScraper:
    def test_build_signal(self):
        scraper = DaAwardNoticeScraper()
        signal = scraper._build_signal(REAL_DA_AWARD_ITEM)
        assert signal is not None
        assert signal.source_id == "SEAP-CAN-DA-DAN1000002"
        assert signal.entity_name == "MUNICIPIUL MOTRU"
        assert signal.estimated_value_ron == 113400.0
        assert signal.published_date == "2018-04-02"

    def test_build_notice(self):
        scraper = DaAwardNoticeScraper()
        notice = scraper._build_notice(REAL_DA_AWARD_ITEM)
        assert notice.notice_type == "CAN"
        assert notice.award_details.winning_bidder_name == "SUD MEDIA PRODUCTION"
        assert notice.award_details.winning_bidder_cui == "27655088"
        assert notice.award_details.awarded_value_ron == 113400.0


class TestProcurementNoticeFingerprint:
    def _make(self, notice_id="DA1", notice_type="DA", value=1000.0):
        return ProcurementNotice(
            notice_id=notice_id,
            notice_type=notice_type,
            contracting_authority={"name": "Test CA"},
            financial={"estimated_value_ron": value},
        )

    def test_stable_for_identical_input(self):
        assert self._make().fingerprint() == self._make().fingerprint()

    def test_changes_when_value_changes(self):
        # Documents the deliberate behaviour: the fingerprint is a
        # content-change marker, not the dedup key (see fingerprint()'s
        # docstring) — (notice_id, notice_type) is the real identity, and
        # that's what upsert_procurement_notice() conflicts on, not this.
        assert self._make(value=1000.0).fingerprint() != self._make(value=2000.0).fingerprint()

    def test_changes_when_type_changes(self):
        assert self._make(notice_type="DA").fingerprint() != self._make(notice_type="CAN").fingerprint()

    def test_all_five_notice_types_are_valid_schema_values(self):
        # The schema is ready for CN/SC/MC even though only DA/CAN are
        # actually ingested today — see the scraper module's docstring.
        for t in ("CN", "SC", "DA", "CAN", "MC"):
            assert self._make(notice_type=t).notice_type == t

    def test_invalid_notice_type_rejected(self):
        with pytest.raises(Exception):
            self._make(notice_type="NOT_A_REAL_TYPE")


@pytest.mark.asyncio
async def test_fetch_market_consultations_stops_at_empty_page(monkeypatch):
    """End-to-end pagination wiring, without touching the network: proves
    the loop stops on an empty page rather than looping forever, and that
    it degrades cleanly with no DATABASE_URL configured (the default in
    any dev/CI environment that hasn't set one, exactly like the rest of
    this codebase's tests)."""
    import httpx

    from scrapers.matrix import direct_acquisition_scraper as mod

    second_item = {**REAL_DA_ITEM_OPEN, "directAcquisitionId": 999, "uniqueIdentificationCode": "DA99999999"}
    calls = {"pages": []}

    async def fake_post_json(client, url, body):
        calls["pages"].append(body["pageIndex"])
        if body["pageIndex"] == 0:
            return {"items": [REAL_DA_ITEM_OPEN, second_item]}
        return {"items": []}

    async def fake_get(self, url, *args, **kwargs):
        return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(mod, "_post_json", fake_post_json)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    scraper = DirectAcquisitionScraper()
    scraper.page_size = 2  # matches the fixture's page-0 item count, so a full
    # page is fetched and the loop must check page 1 (not short-circuit on a
    # page that merely looks shorter than a much larger default page_size)
    signals = await scraper.fetch_market_consultations()

    assert calls["pages"] == [0, 1]  # stopped after the first empty page
    assert len(signals) == 2
    assert {s.source_id for s in signals} == {"SEAP-DA-DA22780457", "SEAP-DA-DA99999999"}
