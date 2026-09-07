"""Tests for scrapers/cpv_taxonomy.py and its two wiring points:
scrapers/matrix/category_classifier.py (CPV-first classification) and
ai_refinery.py (procedure_type inference).

CPV_DIVISIONS itself is not re-verified here against the live TED source —
that was done once by hand when the table was built (see cpv_taxonomy.py's
module docstring) and re-fetching it on every test run would make the suite
depend on a network call for data that never changes. What these tests do
guard is the part that regresses silently: the hierarchy arithmetic, the
CPV-before-keyword precedence, and that a scraper's real cpv_code actually
reaches the classifier instead of being dropped or stuffed into free text.
"""
from datetime import date

import pytest

from ai_refinery import IntelligenceRefineryEngine, PROCEDURE_TYPES
from scrapers import cpv_taxonomy
from scrapers.matrix.category_classifier import classify_category, classify_with_evidence
from scrapers.models import RawInstitutionalSignal


class TestCpvHierarchy:
    def test_decomposes_a_real_code_by_tier(self):
        # 45233120 = Road construction works, a real CPV leaf code.
        result = cpv_taxonomy.cpv_hierarchy("45233120")
        assert result == {
            "division": "45000000",
            "group": "45200000",
            "class_": "45230000",
            "category": "45233000",
        }

    def test_strips_the_check_digit_suffix(self):
        # Real scraped codes carry a "-N" checksum; the hierarchy is over
        # the 8-digit code alone.
        assert cpv_taxonomy.cpv_hierarchy("45233120-6") == cpv_taxonomy.cpv_hierarchy("45233120")

    def test_none_for_missing_or_garbage_input(self):
        assert cpv_taxonomy.cpv_hierarchy(None) is None
        assert cpv_taxonomy.cpv_hierarchy("") is None
        assert cpv_taxonomy.cpv_hierarchy("not a cpv code") is None
        assert cpv_taxonomy.cpv_hierarchy("123") is None  # too short to be a real code

    def test_division_code_is_the_bare_two_digit_key(self):
        assert cpv_taxonomy.division_code("45233120-6") == "45"
        assert cpv_taxonomy.division_code(None) is None


class TestCpvDivisionTable:
    """CPV_DIVISIONS was parsed from TED's official eForms reference table,
    not hand-typed — these are structural sanity checks (every key really
    is a 2-digit division, every entry has both labels), not a re-check of
    the content itself."""

    def test_exactly_45_divisions(self):
        # The CPV 2008 vocabulary has 45 divisions — the gaps (36, 40, 49,
        # 74, 93...) are genuine absences in the standard, not omissions.
        assert len(cpv_taxonomy.CPV_DIVISIONS) == 45

    def test_every_key_is_a_two_digit_code(self):
        assert all(len(k) == 2 and k.isdigit() for k in cpv_taxonomy.CPV_DIVISIONS)

    def test_every_entry_has_both_labels_non_empty(self):
        for code, info in cpv_taxonomy.CPV_DIVISIONS.items():
            assert info["label_en"].strip(), code
            assert info["label_ro"].strip(), code

    def test_spot_check_against_the_verified_source(self):
        # Cross-checked directly against docs.ted.europa.eu's official CPV
        # table when this module was built — pinned so a future edit to
        # the table can't silently drift from what was actually verified.
        assert cpv_taxonomy.CPV_DIVISIONS["45"]["label_en"] == "Construction work"
        assert cpv_taxonomy.CPV_DIVISIONS["33"]["label_en"] == (
            "Medical equipments, pharmaceuticals and personal care products"
        )
        assert cpv_taxonomy.CPV_DIVISIONS["72"]["label_en"] == (
            "IT services: consulting, software development, Internet and support"
        )

    def test_division_label_looks_up_by_full_code(self):
        info = cpv_taxonomy.division_label("45233120-6")
        assert info["label_en"] == "Construction work"


class TestDomainFromCpv:
    def test_mapped_divisions_resolve_to_the_expected_domain(self):
        assert cpv_taxonomy.domain_from_cpv("45233120-6") == "infrastructura"
        assert cpv_taxonomy.domain_from_cpv("33100000-1") == "sanatate"
        assert cpv_taxonomy.domain_from_cpv("09300000-2") == "energie"
        assert cpv_taxonomy.domain_from_cpv("72000000-5") == "digitalizare"
        assert cpv_taxonomy.domain_from_cpv("35000000-0") == "aparare"

    def test_every_mapped_value_is_one_of_the_apps_five_domains(self):
        # DIVISION_TO_DOMAIN must never introduce a domain the rest of the
        # app (CATEGORY_KEYWORDS, the frontend's closed onboarding list)
        # doesn't already know about.
        allowed = {"aparare", "sanatate", "energie", "digitalizare", "infrastructura"}
        assert set(cpv_taxonomy.DIVISION_TO_DOMAIN.values()) <= allowed

    def test_unmapped_division_returns_none_rather_than_guessing(self):
        # Division 15 (food/beverages/tobacco) has no honest correspondence
        # to any of the app's five domains — must fall through, not guess.
        assert cpv_taxonomy.domain_from_cpv("15000000-8") is None

    def test_no_cpv_code_returns_none(self):
        assert cpv_taxonomy.domain_from_cpv(None) is None
        assert cpv_taxonomy.domain_from_cpv("") is None


class TestClassifierPrefersCpvOverKeywords:
    """The real bug this closed: direct_acquisition_scraper.py and
    ted_scraper.py already fetch a genuine cpv_code and were either
    discarding it or feeding the raw digits into the keyword matcher, where
    an 8-digit number can never match a Romanian keyword string."""

    def test_cpv_wins_even_when_text_would_suggest_a_different_domain(self):
        # Title text screams "infrastructura" (drum = road), but a genuine
        # CPV code for medical equipment should still win — it is what the
        # contracting authority actually declared.
        category = classify_category(
            "Spitalul Județean", "Reabilitare drum de acces", cpv_code="33100000-1"
        )
        assert category == "sanatate"

    def test_falls_back_to_keywords_when_cpv_code_is_absent(self):
        category = classify_category("Primăria X", "Reabilitare drum comunal DC12")
        assert category == "infrastructura"

    def test_falls_back_to_keywords_when_cpv_division_is_unmapped(self):
        # A genuine CPV code (food products, division 15) that just isn't
        # in DIVISION_TO_DOMAIN — must not silently win with a None-derived
        # category; must fall through to the keyword text.
        category = classify_category(
            "Primăria X", "Achiziție software pentru primărie",
            cpv_code="15000000-8",
        )
        assert category == "digitalizare"

    def test_evidence_reports_the_cpv_code_when_it_drove_the_decision(self):
        category, evidence = classify_with_evidence(
            "Autoritate", "Titlu oarecare", cpv_code="72000000-5"
        )
        assert category == "digitalizare"
        assert evidence == ["CPV 72000000-5"]

    def test_evidence_reports_keyword_hits_when_cpv_is_absent(self):
        category, evidence = classify_with_evidence("Primăria X", "reabilitare drum comunal")
        assert category == "infrastructura"
        assert evidence  # non-empty — real keyword hits, not a CPV placeholder


class TestDirectAcquisitionScraperPassesRealCpv:
    """Regression guard for the exact bug found while wiring this: both
    _build_signal methods used to hand the numeric CPV string to
    classify_category's free-text `description` parameter, where it could
    never match a keyword. Confirmed by source inspection rather than a
    live HTTP call, matching this test module's existing convention of not
    hitting real scraper endpoints."""

    def test_source_passes_cpv_via_the_cpv_code_parameter(self):
        import inspect

        import scrapers.matrix.direct_acquisition_scraper as das

        source = inspect.getsource(das)
        assert "classify_category(ca_name, title, cpv or \"\")" not in source
        assert source.count("cpv_code=cpv") >= 2


class TestProcedureTypeInference:
    def _signal(self, **overrides) -> RawInstitutionalSignal:
        base = dict(
            source_id="TEST-PT-1",
            source_type="test_source",
            category="infrastructura",
            sub_category="drumuri",
            county="Cluj",
            locality="Cluj-Napoca",
            entity_name="Primăria Cluj-Napoca",
            project_title="Reabilitare drum județean",
            estimated_value_ron=5_000_000.0,
            published_date=date.today().isoformat(),
            action_deadline=None,
            raw_description="Anunț de test.",
            source_url="https://example.ro/test",
            metadata={},
        )
        base.update(overrides)
        return RawInstitutionalSignal(**base)

    def test_declared_direct_purchase_is_honored(self):
        signal = self._signal(metadata={"procedure_type": "cumparare_directa"})
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["procedure_type"] == "cumparare_directa"

    def test_declared_market_consultation_is_honored(self):
        signal = self._signal(metadata={"procedure_type": "consultare_piata"})
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["procedure_type"] == "consultare_piata"

    def test_undeclared_procedure_type_is_null_not_guessed(self):
        # No text heuristic exists for this field on purpose — a title
        # cannot honestly distinguish an open auction from a restricted
        # one, unlike procurement_stage which does have a text fallback.
        signal = self._signal(metadata={})
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["procedure_type"] is None

    def test_unrecognized_declared_value_is_rejected_not_passed_through(self):
        # Same discipline as _infer_stage's `declared in STAGE_PROFILES`
        # check — a typo'd or made-up value must not silently reach
        # persistence as if it were a real, closed-vocabulary fact.
        # 'contract_de_concesiune' stands in for "not yet a real ingested
        # type" — unlike 'licitatie_deschisa'/'procedura_simplificata',
        # which notice_scraper.py's CN/SC scrapers now genuinely declare.
        signal = self._signal(metadata={"procedure_type": "contract_de_concesiune"})
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["procedure_type"] is None
        assert "contract_de_concesiune" not in PROCEDURE_TYPES


class TestCanAwardNoticeDeclaresAwardedStage:
    """Found while wiring procedure_type: DaAwardNoticeScraper was the only
    stage-aware source (compare ted_scraper.py's STAGE_BY_FORM_TYPE,
    cni_common.py's STAGE_BY_STATUS, municipal_scrapers.py's
    _procurement_stage) that never declared procurement_stage at all —
    despite being literally an award notice, it fell through to "unknown"
    (weight 0.6) instead of the deliberately negative "awarded" (weight
    -1.0) every other award-adjacent source uses to keep closed procedures
    from outranking live opportunities."""

    def test_source_declares_awarded_stage(self):
        import inspect

        import scrapers.matrix.direct_acquisition_scraper as das

        source = inspect.getsource(das.DaAwardNoticeScraper)
        assert '"procurement_stage": "awarded"' in source

    def test_awarded_stage_actually_resolves_to_the_negative_weight_profile(self):
        from ai_refinery import STAGE_PROFILES

        signal = RawInstitutionalSignal(
            source_id="SEAP-CAN-DA-TEST",
            source_type="SEAP Anunț de Atribuire — Achiziție Directă (Live)",
            category="infrastructura",
            sub_category="Anunț de Atribuire",
            county="Necunoscut",
            locality="",
            entity_name="Autoritate Contractantă",
            project_title="Achiziție directă atribuită",
            estimated_value_ron=100_000.0,
            published_date=date.today().isoformat(),
            action_deadline=None,
            raw_description="Achiziție directă atribuită",
            source_url="https://example.ro/test",
            metadata={"notice_type": "CAN", "procedure_type": "cumparare_directa", "procurement_stage": "awarded"},
        )
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["procurement_stage"] == "awarded"
        assert STAGE_PROFILES["awarded"]["weight"] < 0
