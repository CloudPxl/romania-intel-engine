"""refine_signal is the one place ingested values/dates get a sanity check
before reaching the database. These pin the two bounds added alongside the
pre-existing negative-value clamp: an implausible value or date is treated
as unpublished/null (the same "honest gap" convention this file already
uses for a missing deadline) rather than displayed as-is or discarded
along with an otherwise-good signal.
"""
from datetime import date, timedelta

from ai_refinery import IntelligenceRefineryEngine, MAX_PLAUSIBLE_VALUE_RON
from scrapers.models import RawInstitutionalSignal


def _signal(**overrides) -> RawInstitutionalSignal:
    base = dict(
        source_id="TEST-1",
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
    )
    base.update(overrides)
    return RawInstitutionalSignal(**base)


class TestValueUpperBound:
    def test_implausible_value_treated_as_unpublished(self, caplog):
        signal = _signal(estimated_value_ron=MAX_PLAUSIBLE_VALUE_RON + 1)
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["financial_value_ron"] == 0.0
        assert result["value_is_published"] is False
        assert any("Implausible estimated_value_ron" in r.message for r in caplog.records)

    def test_plausible_value_unaffected(self):
        signal = _signal(estimated_value_ron=5_000_000.0)
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["financial_value_ron"] == 5_000_000.0
        assert result["value_is_published"] is True


class TestDatePlausibility:
    def test_implausible_future_deadline_nulled(self):
        signal = _signal(action_deadline="2099-01-01")
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["action_deadline"] is None
        assert result["estimated_timeline"]["action_deadline"] is None

    def test_near_future_deadline_unaffected(self):
        near = (date.today() + timedelta(days=30)).isoformat()
        signal = _signal(action_deadline=near)
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["action_deadline"] == near

    def test_missing_published_date_no_false_positive(self, caplog):
        signal = _signal(published_date="")
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["published_date"] is None
        assert not any("Implausible published_date" in r.message for r in caplog.records)

    def test_implausible_old_published_date_nulled(self):
        signal = _signal(published_date="1999-01-01")
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["published_date"] is None
