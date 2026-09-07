"""Tests for scrapers/matrix/notice_scraper.py — Contract Notices (CN) and
Simplified Contract Notices (SC), e-licitatie.ro's two full-tender feeds.

Fixture payloads below are verbatim copies of real responses captured live
from e-licitatie.ro's api-pub/NoticeCommon/GetCNoticeList endpoint on
2026-09-08 (see the scraper module's docstring for exactly how that
endpoint was found and what else was checked and ruled out) — not invented
shapes. `REAL_CN_ITEM_AWARDED` and `REAL_SC_ITEM_CANCELLED` are two of the
three CN and two SC items returned by a live `pageSize: 3`/`pageSize: 2`
call respectively. Run with `pytest` from romania-intel-engine/ (no
DATABASE_URL needed — persistence degrades to a no-op exactly like the
rest of the app when it's unset).
"""

import pytest

from ai_refinery import IntelligenceRefineryEngine, STAGE_PROFILES
from procurement_notices import ProcurementNotice, split_cui_and_name
from scrapers.matrix.notice_scraper import (
    ContractNoticeScraper,
    SimplifiedContractNoticeScraper,
    _extract_cpv_code,
    _view_url,
)
from scrapers.models import RawInstitutionalSignal

REAL_CN_ITEM_AWARDED = {
    "cNoticeId": 100053648,
    "noticeId": 100159118,
    "procedureId": 100068106,
    "noticeNo": "CN1010402",
    "sysNoticeTypeId": 2,
    "sysNoticeState": {"id": 2, "text": "Publicat", "localeKey": None, "apiActionResult": None},
    "sysProcedureState": {"id": 5, "text": "Atribuita", "localeKey": None, "apiActionResult": None},
    "contractingAuthorityNameAndFN": "4374873 - SPITALUL DE URGENTA PETROSANI",
    "contractTitle": (
        "Acord-cadru furnizare de produse – MEDICAMENTE necesare tratamentului "
        "pacientilor cu afectiuni oncologice (2019-2021)"
    ),
    "sysAcquisitionContractType": {"id": 1, "text": "Furnizare", "localeKey": None, "apiActionResult": None},
    "sysProcedureType": {"id": 1, "text": "Licitatie deschisa", "localeKey": None, "apiActionResult": None},
    "sysContractAssigmentType": {"id": 3, "text": "Acord-cadru", "localeKey": None, "apiActionResult": None},
    "cpvCodeAndName": "33652100-6 - Antineoplazice (Rev.2)",
    "estimatedValueRon": 14867462.0,
    "isOnline": True,
    "hasLots": True,
    "noticeStateDate": "2019-04-02T01:35:01+03:00",
    "minTenderReceiptDeadline": "2019-05-09T15:00:00+03:00",
    "maxTenderReceiptDeadline": "2019-05-09T15:00:00+03:00",
    "errataNo": 0,
    "sysNoticeVersionId": 2,
    "tenderReceiptDeadlineExport": "09.05.2019 15:00",
    "estimatedValueExport": "14867462 RON",
    "sadId": None,
    "hasAppeal": False,
}

REAL_SC_ITEM_CANCELLED = {
    "cNoticeId": 100059398,
    "noticeId": 100158523,
    "procedureId": 100067748,
    "noticeNo": "SCN1040692",
    "sysNoticeTypeId": 17,
    "sysNoticeState": {"id": 2, "text": "Publicat", "localeKey": None, "apiActionResult": None},
    "sysProcedureState": {"id": 3, "text": "Anulata", "localeKey": None, "apiActionResult": None},
    "contractingAuthorityNameAndFN": "RO 14056826 - Societatea Nationala de Gaze Naturale Romgaz S.A.",
    "contractTitle": "Lucrari de demolare la turnurile de racire de la SC Band, SC Taga, SC Fantanele",
    "sysAcquisitionContractType": {"id": 3, "text": "Lucrari", "localeKey": None, "apiActionResult": None},
    "sysProcedureType": {"id": 20, "text": "Procedura simplificata", "localeKey": None, "apiActionResult": None},
    "sysContractAssigmentType": {"id": 1, "text": "Contract de achizitii publice", "localeKey": None, "apiActionResult": None},
    "cpvCodeAndName": "45111100-9 - Lucrari de demolare (Rev.2)",
    "estimatedValueRon": 1021908.27,
    "isOnline": True,
    "hasLots": False,
    "noticeStateDate": "2019-03-29T09:55:28+02:00",
    "minTenderReceiptDeadline": "2019-04-18T15:00:00+03:00",
    "maxTenderReceiptDeadline": "2019-04-18T15:00:00+03:00",
    "errataNo": 0,
    "sysNoticeVersionId": 2,
    "tenderReceiptDeadlineExport": "18.04.2019 15:00",
    "estimatedValueExport": "1021908,27 RON",
    "sadId": None,
    "hasAppeal": False,
}


class TestCpvCodeExtraction:
    def test_extracts_leading_code_with_check_digit(self):
        assert _extract_cpv_code("33652100-6 - Antineoplazice (Rev.2)") == "33652100-6"

    def test_none_input(self):
        assert _extract_cpv_code(None) is None

    def test_unrecognized_shape_returns_none_not_a_guess(self):
        assert _extract_cpv_code("fara cod cpv") is None


class TestSplitCuiAndNameHyphenFormat:
    """notice_scraper.py's contractingAuthorityNameAndFN uses a hyphen
    separator DA/CAN's contractingAuthority field never did — this is the
    real bug found and fixed in procurement_notices.py while building this
    module: without the fix, both cases below parsed a stray leading '- '
    onto the name."""

    def test_plain_cui_hyphen_name(self):
        cui, name = split_cui_and_name("4374873 - SPITALUL DE URGENTA PETROSANI")
        assert cui == "4374873"
        assert name == "SPITALUL DE URGENTA PETROSANI"

    def test_ro_prefixed_cui_hyphen_name(self):
        cui, name = split_cui_and_name("RO 14056826 - Societatea Nationala de Gaze Naturale Romgaz S.A.")
        assert cui == "14056826"
        assert name == "Societatea Nationala de Gaze Naturale Romgaz S.A."

    def test_da_format_still_works_unchanged(self):
        # Regression guard: the fix must not break the pre-existing,
        # already-tested DA/CAN format (no hyphen at all).
        assert split_cui_and_name("4317975 Unitatea Militara 01714") == ("4317975", "Unitatea Militara 01714")
        assert split_cui_and_name("RO 6865630 DELTA PLUS TRADING S.R.L.") == ("6865630", "DELTA PLUS TRADING S.R.L.")


class TestViewUrl:
    def test_cn_new_format(self):
        assert _view_url(2, 2, 100159118) == "https://e-licitatie.ro/pub/notices/c-notice/v2/view/100159118"

    def test_sc_new_format(self):
        assert _view_url(17, 2, 100158523) == "https://e-licitatie.ro/pub/notices/simplified-notice/v2/view/100158523"

    def test_legacy_format_falls_back_to_v1(self):
        assert _view_url(2, 1, 42) == "https://e-licitatie.ro/pub/notices/c-notice/v1/view/42"

    def test_missing_version_defaults_to_v2(self):
        assert _view_url(2, None, 42) == "https://e-licitatie.ro/pub/notices/c-notice/v2/view/42"


class TestContractNoticeScraper:
    def test_build_signal(self):
        scraper = ContractNoticeScraper()
        signal = scraper._build_signal(REAL_CN_ITEM_AWARDED)
        assert isinstance(signal, RawInstitutionalSignal)
        assert signal.source_id == "ELICITATIE-CN-100159118"
        assert signal.entity_name == "SPITALUL DE URGENTA PETROSANI"
        assert signal.cpv_code == "33652100-6"
        assert signal.estimated_value_ron == 14867462.0
        assert signal.published_date == "2019-04-02"
        assert signal.action_deadline == "2019-05-09"
        assert signal.metadata["contracting_authority_cui"] == "4374873"
        assert signal.metadata["notice_id"] == "CN1010402"
        assert signal.metadata["notice_type"] == "CN"
        assert signal.metadata["procedure_type"] == "licitatie_deschisa"
        assert signal.metadata["procurement_stage"] == "awarded"
        assert signal.metadata["live_fetch_verified"] is True
        assert signal.source_url == "https://e-licitatie.ro/pub/notices/c-notice/v2/view/100159118"

    def test_category_driven_by_real_cpv_code(self):
        # CPV 33652100-6 (division 33, medical) must win over the title's
        # own text, which carries no obvious domain keyword of its own —
        # this is the exact CPV-classification wiring added earlier this
        # session, exercised here against genuine live data rather than a
        # synthetic example.
        scraper = ContractNoticeScraper()
        signal = scraper._build_signal(REAL_CN_ITEM_AWARDED)
        assert signal.category == "sanatate"

    def test_missing_notice_id_or_title_returns_none(self):
        scraper = ContractNoticeScraper()
        assert scraper._build_signal({**REAL_CN_ITEM_AWARDED, "noticeId": None}) is None
        assert scraper._build_signal({**REAL_CN_ITEM_AWARDED, "contractTitle": ""}) is None

    def test_build_notice(self):
        scraper = ContractNoticeScraper()
        notice = scraper._build_notice(REAL_CN_ITEM_AWARDED)
        assert isinstance(notice, ProcurementNotice)
        assert notice.notice_id == "CN1010402"
        assert notice.notice_type == "CN"
        assert notice.cpv_code == "33652100-6"
        assert notice.contracting_authority.cui == "4374873"
        assert notice.contracting_authority.name == "SPITALUL DE URGENTA PETROSANI"
        assert notice.financial.estimated_value_ron == 14867462.0
        assert notice.timeline.bid_deadline_date == "2019-05-09"
        assert notice.caen_codes == []
        assert notice.raw_attachments == []

    def test_awarded_stage_does_not_fabricate_an_award_value(self):
        """The bug caught and fixed while building this module: this
        endpoint reports only that a procedure concluded in an award
        (sysProcedureState), never a genuine post-award value — populating
        awarded_value_ron from estimatedValueRon would silently present
        the original estimate as a confirmed outcome, the same shape of
        mistake this project self-caught earlier (an estimate==awarded
        assumption that would have reported a fabricated 0% median
        discount on live CAN data)."""
        scraper = ContractNoticeScraper()
        notice = scraper._build_notice(REAL_CN_ITEM_AWARDED)
        assert notice.award_details is None
        signal = scraper._build_signal(REAL_CN_ITEM_AWARDED)
        assert signal.metadata["procurement_stage"] == "awarded"  # stage is still honestly reported

    def test_award_criterion_is_honestly_none(self):
        # See this module's docstring: the per-notice award-criterion
        # endpoint was not found this pass, despite the filter parameter
        # and its enum both being confirmed live.
        scraper = ContractNoticeScraper()
        notice = scraper._build_notice(REAL_CN_ITEM_AWARDED)
        assert notice.award_criterion is None


class TestSimplifiedContractNoticeScraper:
    def test_build_signal(self):
        scraper = SimplifiedContractNoticeScraper()
        signal = scraper._build_signal(REAL_SC_ITEM_CANCELLED)
        assert signal.source_id == "ELICITATIE-SC-100158523"
        assert signal.entity_name == "Societatea Nationala de Gaze Naturale Romgaz S.A."
        assert signal.metadata["contracting_authority_cui"] == "14056826"
        assert signal.cpv_code == "45111100-9"
        assert signal.metadata["procedure_type"] == "procedura_simplificata"
        assert signal.metadata["notice_type"] == "SC"

    def test_cancelled_procedure_state_maps_to_cancelled_stage(self):
        # sysProcedureState.id == 3 ("Anulata"), observed live on two real
        # SC notices — must not fall through to ai_refinery's generic
        # "unknown" (positive-ish weight) the way an undeclared source
        # would, and must not be mislabelled "awarded" either.
        scraper = SimplifiedContractNoticeScraper()
        signal = scraper._build_signal(REAL_SC_ITEM_CANCELLED)
        assert signal.metadata["procurement_stage"] == "cancelled"
        assert STAGE_PROFILES["cancelled"]["weight"] < 0
        assert STAGE_PROFILES["cancelled"]["label"] != STAGE_PROFILES["awarded"]["label"]

    def test_build_notice_type_is_sc(self):
        scraper = SimplifiedContractNoticeScraper()
        notice = scraper._build_notice(REAL_SC_ITEM_CANCELLED)
        assert notice.notice_type == "SC"
        assert notice.award_details is None


class TestEndToEndThroughAiRefinery:
    """Confirms the declared procedure_type/procurement_stage in metadata
    actually survive ai_refinery.refine_signal's own inference logic
    (which prefers a declared value over guessing from text) rather than
    only being correct at the scraper boundary."""

    def test_cn_signal_keeps_its_declared_procedure_type_and_stage(self):
        scraper = ContractNoticeScraper()
        signal = scraper._build_signal(REAL_CN_ITEM_AWARDED)
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["procedure_type"] == "licitatie_deschisa"
        assert result["procurement_stage"] == "awarded"

    def test_sc_signal_keeps_its_declared_procedure_type_and_stage(self):
        scraper = SimplifiedContractNoticeScraper()
        signal = scraper._build_signal(REAL_SC_ITEM_CANCELLED)
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["procedure_type"] == "procedura_simplificata"
        assert result["procurement_stage"] == "cancelled"


@pytest.mark.asyncio
async def test_fetch_market_consultations_stops_at_empty_page(monkeypatch):
    """Same pagination-wiring proof as
    test_direct_acquisition_scraper.py's equivalent test: the loop stops
    on an empty page, and it degrades cleanly with no DATABASE_URL
    configured."""
    import httpx

    from scrapers.matrix import notice_scraper as mod

    second_item = {**REAL_CN_ITEM_AWARDED, "noticeId": 999, "noticeNo": "CN9999999"}
    calls = {"pages": [], "bodies": []}

    async def fake_post_json(client, url, body):
        calls["pages"].append(body["pageIndex"])
        calls["bodies"].append(body)
        if body["pageIndex"] == 0:
            return {"items": [REAL_CN_ITEM_AWARDED, second_item]}
        return {"items": []}

    async def fake_get(self, url, *args, **kwargs):
        return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(mod, "_post_json", fake_post_json)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    scraper = ContractNoticeScraper()
    scraper.page_size = 2  # matches the fixture's page-0 item count
    signals = await scraper.fetch_market_consultations()

    assert calls["pages"] == [0, 1]
    assert calls["bodies"][0]["sysNoticeTypeIds"] == [2]
    assert "startPublicationDate" in calls["bodies"][0]
    assert len(signals) == 2
    assert {s.source_id for s in signals} == {"ELICITATIE-CN-100159118", "ELICITATIE-CN-999"}


def test_orchestrator_registers_both_scrapers_behind_the_feature_flag(monkeypatch):
    monkeypatch.setenv("ENABLE_LIVE_CONTRACT_NOTICES", "true")
    # Reload-free check: import fresh and construct, same pattern this
    # suite's sibling files use for orchestrator wiring checks.
    import importlib

    from scrapers import orchestrator as orch_mod
    importlib.reload(orch_mod)
    orchestrator = orch_mod.OpportunityOrchestrator()
    names = {s.name for s in orchestrator.scrapers}
    assert "SeapContractNotice" in names
    assert "SeapSimplifiedContractNotice" in names
