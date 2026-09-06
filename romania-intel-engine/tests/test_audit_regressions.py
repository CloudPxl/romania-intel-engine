"""Regressions from the full-repo audit.

Each test here pins a defect that was silent in production — no exception,
no log, no wrong-looking output. That is what makes them worth a test
rather than a fix: nothing would have told anyone they had come back.
"""
import asyncio

import pytest

import db
import text_utils
from scrapers.money import parse_ro_number, parse_ro_value


# --------------------------------------------------------------- money

class TestRomanianMoney:
    """One parser replaced seven. The sixth copy had the separators
    reversed, and its output was indistinguishable from a source that
    simply publishes no value."""

    @pytest.mark.parametrize("raw,expected", [
        ("9.844.025,00", 9_844_025.0),
        ("1.234.567,89", 1_234_567.89),
        ("2.500.000", 2_500_000.0),
        # The dangerous one: the broken parser returned 150.0 here — a
        # 150k contract that looks entirely legitimate at 150 RON and
        # sinks below every min_value_ron filter.
        ("150.000", 150_000.0),
        ("1.500,50", 1_500.50),
        ("12345", 12_345.0),
        ("1 234 567,89", 1_234_567.89),
    ])
    def test_romanian_convention(self, raw, expected):
        assert parse_ro_number(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw,expected", [
        # A JSON feed emits a plain decimal. A Romanian thousands group is
        # always exactly three digits, so a two-digit tail can only be a
        # decimal — reading it as thousands inflated these by 100x.
        ("1234567.89", 1_234_567.89),
        ("10302905.76", 10_302_905.76),
        ("1.5", 1.5),
    ])
    def test_json_decimal_convention(self, raw, expected):
        assert parse_ro_number(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["", "   ", None, "abc", "lei"])
    def test_unparseable_is_zero_not_an_exception(self, raw):
        assert parse_ro_number(raw) == 0.0

    def test_every_scraper_copy_now_agrees(self):
        """The seven implementations disagreed about what '150.000' meant.
        Five delegate to the shared one now; digital_scrapers stays
        separate on purpose (its feed is plain decimals)."""
        from scrapers.adapters.generic_portal_adapter import _parse_ro_value as gp
        from scrapers.adapters.indeco_adapter import _parse_ro_value as ind
        from scrapers.adapters.sobis_adapter import _parse_ro_value as sob
        from scrapers.matrix.municipal_scrapers import _parse_ro_value as mun
        from scrapers.matrix.infra_scrapers import UrbanismAcScraper

        for text in ("9.844.025,00 lei", "150.000 lei", "1.500,50 lei"):
            bare = text.replace(" lei", "")
            values = {gp(text), ind(text), sob(text), mun(text), UrbanismAcScraper._parse_ron(bare)}
            assert len(values) == 1, f"{text}: implementations disagree -> {values}"

    def test_sobis_does_not_reparse_a_json_number_as_text(self):
        """It formatted the number into a string and fed it to the
        Romanian text parser, turning 1234567.89 into 123456789.0."""
        from scrapers.adapters.sobis_adapter import _parse_json_value

        assert _parse_json_value(1234567.89) == pytest.approx(1_234_567.89)
        assert _parse_json_value(250000.5) == pytest.approx(250_000.5)
        assert _parse_json_value(None) == 0.0
        assert _parse_json_value(True) == 0.0  # bool is an int subclass


# ------------------------------------------------------------ matching

class TestHyphenatedKeywords:
    """Keyword evidence is a MANDATORY gate for alerting, and a hyphenated
    keyword compiled to a pattern that could not match the very text it
    was built from. A profile keyed on "Cluj-Napoca" got no alerts, ever,
    with nothing anywhere reporting why."""

    @pytest.mark.parametrize("text,term", [
        ("Modernizare strazi in Cluj-Napoca", "Cluj-Napoca"),
        ("Modernizare strazi in Cluj Napoca", "Cluj-Napoca"),
        ("platforma de e-guvernare", "e-guvernare"),
        ("achizitie CT-scan pentru spital", "CT-scan"),
        ("Reabilitare DN1 Bistrita-Nasaud", "bistrita-nasaud"),
    ])
    def test_both_spellings_match(self, text, term):
        assert text_utils.contains_term(text, term)
        assert text_utils.matching_terms(text, [term]) == [term]

    def test_whole_word_matching_is_preserved(self):
        """The fix must not reintroduce substring matching."""
        assert not text_utils.contains_term("crestere salariu", "sala")
        assert not text_utils.contains_term("bloc de apartamente", "apa")

    def test_sql_and_python_matchers_stay_in_step(self):
        for term in ("Cluj-Napoca", "drum judetean", "e-guvernare", "spital"):
            sql = db._pg_word_patterns([term])[0]
            normalised = (
                sql.replace(r"\m", r"\b").replace(r"\M", r"\b").replace("[[:space:]-]", r"[\s\-]")
            )
            assert normalised == text_utils.term_pattern(term), term

    def test_unmatchable_terms_produce_no_pattern(self):
        assert text_utils.term_pattern("***") == ""
        assert text_utils.term_pattern("") == ""
        assert db._pg_word_patterns(["***", "!!!"]) == []


class TestPreTenderStageBonus:
    """The bonus read `metadata.procurement_stage`, but the refinery writes
    the resolved stage to the TOP-LEVEL key and passes metadata through
    untouched — so every stage inferred from a title (the majority) scored
    0.8 lower than the same signal with the stage declared, which is
    enough to drop it below ALERT_THRESHOLD and cancel the alert."""

    PROFILE = {
        "domain": "infrastructura",
        "target_counties": ["Cluj"],
        "keywords": ["drum"],
        "exclude_keywords": [],
        "min_value_ron": 0,
    }

    def _opportunity(self, **overrides):
        base = {
            "project_title": "Studiu de fezabilitate reabilitare drum judetean",
            "entity_name": "CJ Cluj",
            "county": "Cluj",
            "category": "infrastructura",
            "financial_value_ron": 1_000_000,
            "metadata": {},
        }
        base.update(overrides)
        return base

    def test_top_level_stage_earns_the_bonus(self):
        from matching_engine import RelevanceEngine

        without = RelevanceEngine.evaluate(self._opportunity(), self.PROFILE)["score"]
        with_stage = RelevanceEngine.evaluate(
            self._opportunity(procurement_stage="pre_tender_approved_indicators"), self.PROFILE
        )["score"]
        assert with_stage > without

    def test_declared_and_inferred_stages_score_identically(self):
        """The whole defect in one assertion."""
        from matching_engine import RelevanceEngine

        inferred = RelevanceEngine.evaluate(
            self._opportunity(procurement_stage="pre_tender_documentation_review"), self.PROFILE
        )["score"]
        declared = RelevanceEngine.evaluate(
            self._opportunity(metadata={"procurement_stage": "pre_tender_documentation_review"}),
            self.PROFILE,
        )["score"]
        assert inferred == declared


# ------------------------------------------------------- orchestration

class TestTickAlwaysCompletes:
    """db.finish_tick was a bare statement after the loop, so an exception
    anywhere in between left the tick row with completed_at NULL and
    /system/status reporting is_stale forever while ingestion was actually
    running — the exact failure run_tick's docstring claims to have fixed."""

    @pytest.mark.asyncio
    async def test_setup_failure_still_records_the_tick(self, monkeypatch):
        from scrapers.orchestrator import OpportunityOrchestrator

        recorded = {}

        async def start_tick():
            return 42

        async def finish_tick(tick_id, sources, new, errors):
            recorded["args"] = (tick_id, sources, new, errors)

        async def boom(*args, **kwargs):
            raise RuntimeError("transient asyncpg failure")

        monkeypatch.setattr(db, "start_tick", start_tick)
        monkeypatch.setattr(db, "finish_tick", finish_tick)
        monkeypatch.setattr(db, "get_onboarded_profiles", boom)

        with pytest.raises(RuntimeError):
            await OpportunityOrchestrator().run_tick(deadline_seconds=5)

        # The failure still propagates — the caller must know — but the
        # tick row is closed either way.
        assert recorded["args"] == (42, 0, 0, 0)


# --------------------------------------------------------- LLM contract

class TestLlmResponseHandling:
    @pytest.mark.asyncio
    async def test_truncated_response_is_flagged_not_passed_off_as_complete(self, monkeypatch):
        """finish_reason=length means the answer was cut at max_tokens.
        This text goes into documents filed with an evaluation commission."""
        import ai_copilot

        self._fake_provider(monkeypatch, ai_copilot, content="raspuns taiat", finish="length")
        out = await ai_copilot.complete_text("sys", "usr")
        assert out.startswith("raspuns taiat")
        assert "incomplet" in out

    @pytest.mark.asyncio
    async def test_null_content_fails_over_instead_of_raising(self, monkeypatch):
        """A reasoning model can spend its budget on hidden thinking and
        return content: null. `.strip()` raised AttributeError, which the
        broad handler then mislabelled 'completion call failed'."""
        import ai_copilot

        self._fake_provider(monkeypatch, ai_copilot, content=None, finish="length")
        assert await ai_copilot.complete_text("sys", "usr") is None

    @pytest.mark.asyncio
    async def test_normal_response_is_untouched(self, monkeypatch):
        import ai_copilot

        self._fake_provider(monkeypatch, ai_copilot, content="  raspuns complet  ", finish="stop")
        assert await ai_copilot.complete_text("sys", "usr") == "raspuns complet"

    @staticmethod
    def _fake_provider(monkeypatch, ai_copilot, content, finish):
        payload = {"choices": [{"message": {"content": content}, "finish_reason": finish}]}

        class _Resp:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return payload

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, **kwargs):
                return _Resp()

        monkeypatch.setattr(ai_copilot, "list_llm_providers", lambda: [("groq", "https://x", "m", "k")])
        monkeypatch.setattr(ai_copilot.httpx, "AsyncClient", lambda **kw: _Client())


# ------------------------------------------------------------ scenarios

class TestQualificationEdgeCases:
    def test_unpublished_estimate_with_a_stated_requirement_does_not_crash(self):
        """`(ceiling or 0)` made this branch reachable with ceiling=None,
        and the f-string then formatted None -> TypeError -> 500, after two
        live ANAF round-trips. An unpublished value is a first-class state
        everywhere else in this codebase."""
        from addons.qualification_scenarios import evaluate_qualification

        verification = {
            "found": True,
            "company": {"cui": 1, "company_name": "X", "is_inactive_taxpayer": False},
            "financials": {"found": True, "turnover_ron": 5_000_000.0},
            "sources": [],
        }
        result = evaluate_qualification(
            verification, estimated_value_ron=0, required_turnover_ron=5_000_000
        )
        assert result["scenario_a_leader"]["max_lawful_turnover_requirement_ron"] is None
        assert any("nu este publicată" in f for f in result["scenario_a_leader"]["findings"])


# ---------------------------------------------------------------- cache

class TestResponseCacheIsBounded:
    def test_expired_entries_are_swept(self):
        """Entries were dropped only when their own key was read again, so
        a user who browsed once and never returned left a full feed payload
        (up to 500 leads) resident for the life of the process."""
        import time

        from cache_engine import MemoryCacheEngine

        cache = MemoryCacheEngine(default_ttl_seconds=0.01)
        for i in range(50):
            cache.set(f"feed:user{i}:all:0", {"leads": [1] * 100})
        assert cache.stats()["entries"] == 50

        time.sleep(0.05)
        cache._last_cleanup_at = 0.0  # open the sweep window
        cache.set("feed:fresh:all:0", {"leads": []})
        assert cache.stats()["entries"] == 1

    def test_invalidate_by_prefix_only_removes_that_user(self):
        from cache_engine import MemoryCacheEngine

        cache = MemoryCacheEngine()
        cache.set("feed:alice:all:0", {"a": 1})
        cache.set("feed:bob:all:0", {"b": 2})
        cache.invalidate(prefix="feed:alice:")
        assert cache.get("feed:alice:all:0") is None
        assert cache.get("feed:bob:all:0") == {"b": 2}
