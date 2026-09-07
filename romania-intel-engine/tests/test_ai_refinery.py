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


class TestPromotedProcurementMetadata:
    """authority_cui and award_criterion live on `opportunities` as real,
    indexable columns so the feed can filter by them. refine_signal is what
    lifts them out of the scraper's metadata blob onto the top-level keys
    db.upsert_opportunity persists — without this promotion the columns
    exist but nothing ever writes them."""

    def test_cui_is_promoted_from_scraper_metadata(self):
        signal = _signal(metadata={"contracting_authority_cui": "4374873"})
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["authority_cui"] == "4374873"

    def test_vat_prefixed_cui_is_normalised_to_the_stored_form(self):
        """SEAP emits the same authority both bare and RO-prefixed. The
        column has to hold one form or an exact-match filter silently
        misses a chunk of a user's own leads."""
        signal = _signal(metadata={"contracting_authority_cui": "RO 14056826"})
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["authority_cui"] == "14056826"

    def test_absent_cui_is_null_not_empty_string(self):
        # An empty string would be a value the filter can match, creating a
        # bucket of "authorities with no CUI" that looks like a real one.
        result = IntelligenceRefineryEngine.refine_signal(_signal(metadata={}))
        assert result["authority_cui"] is None

    def test_unparseable_cui_is_null(self):
        signal = _signal(metadata={"contracting_authority_cui": "n/a"})
        assert IntelligenceRefineryEngine.refine_signal(signal)["authority_cui"] is None

    def test_award_criterion_is_promoted_when_a_source_supplies_one(self):
        signal = _signal(metadata={"award_criterion": "Pretul cel mai scazut"})
        result = IntelligenceRefineryEngine.refine_signal(signal)
        assert result["award_criterion"] == "Pretul cel mai scazut"

    def test_award_criterion_is_null_for_every_live_scraper_today(self):
        """Honest state: no live scraper populates it yet — see
        notice_scraper.py's docstring for the e-licitatie.ro endpoint that
        was looked for and not found. The plumbing exists so landing it is
        a scraper change, not a migration."""
        result = IntelligenceRefineryEngine.refine_signal(_signal(metadata={}))
        assert result["award_criterion"] is None

    def test_promoted_keys_survive_into_the_search_blob(self):
        """End-to-end with the write path: the blob db.upsert_opportunity
        builds must fold the promoted CUI, or a free-text search for a
        fiscal code finds nothing."""
        import db

        signal = _signal(metadata={"contracting_authority_cui": "RO 14056826"})
        record = IntelligenceRefineryEngine.refine_signal(signal)
        assert "14056826" in db.build_search_blob(record)
