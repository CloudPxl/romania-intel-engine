"""The feed is a SOFT filter: it returns the whole market, ranked.

The previous behaviour returned only what matched a user's keywords, so a
narrow profile saw an empty dashboard — indistinguishable from a broken
product — and never saw the adjacent work a bidder would have wanted. These
tests pin the two properties that make the replacement trustworthy: nothing
is ever dropped, and the ordering is explainable.

They also pin the whole-word matching. A substring test would let "sala"
match "salariu" and "apa" match "apartament", which is the documented reason
text_utils.contains_term exists — and getting it wrong in SQL would present
as "the feed is full of garbage" rather than as an error.
"""
import pytest

import api
import db


class TestWordPatterns:
    def test_builds_whole_word_pattern(self):
        assert db._pg_word_patterns(["drum"]) == [r"\mdrum\M"]

    def test_folds_romanian_diacritics(self):
        """Keyword lists are written without diacritics; published text is
        full of them. Both sides fold to the same thing."""
        assert db._pg_word_patterns(["sănătate"]) == [r"\msanatate\M"]

    def test_folds_legacy_cedilla_forms(self):
        """Institutional sites emit both the correct comma-below (ș U+0219)
        and the legacy cedilla (ş U+015F) forms, often on one page."""
        assert db._pg_word_patterns(["reabilitaţi"]) == [r"\mreabilitati\M"]

    def test_multi_word_term_becomes_a_phrase(self):
        assert db._pg_word_patterns(["drum judetean"]) == [r"\mdrum\s+judetean\M"]

    def test_drops_empty_and_punctuation_only_terms(self):
        assert db._pg_word_patterns(["", "   ", "!!!"]) == []

    def test_none_is_safe(self):
        assert db._pg_word_patterns(None) == []


class TestRankedQuery:
    @pytest.mark.asyncio
    async def test_no_database_returns_empty(self, monkeypatch):
        class _Ctx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(db, "with_connection", lambda: _Ctx())
        assert await db.get_ranked_opportunities({"keywords": ["drum"]}) == []

    @pytest.mark.asyncio
    async def test_nothing_is_excluded_by_the_query(self, monkeypatch):
        """The soft-filter guarantee, asserted against the SQL itself: an
        excluded keyword must SINK a row, never remove it, so the statement
        carries no WHERE clause."""
        captured = {}

        class _Conn:
            async def fetch(self, query, *args):
                captured["query"] = query
                captured["args"] = args
                return []

        class _Ctx:
            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(db, "with_connection", lambda: _Ctx())
        await db.get_ranked_opportunities({
            "keywords": ["drum"], "exclude_keywords": ["curatenie"],
            "target_counties": ["Cluj"], "domain": "infrastructura",
            "min_value_ron": 100000,
        })

        query = captured["query"]
        assert "WHERE" not in query.upper()
        assert "ORDER BY relevance DESC" in query
        # The exclusion is a large negative weight, not a filter.
        assert str(db.RELEVANCE_WEIGHTS["excluded"]) in query

    @pytest.mark.asyncio
    async def test_counties_are_folded_before_comparison(self, monkeypatch):
        captured = {}

        class _Conn:
            async def fetch(self, query, *args):
                captured["args"] = args
                return []

        class _Ctx:
            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(db, "with_connection", lambda: _Ctx())
        await db.get_ranked_opportunities({"target_counties": ["Iași", "Bistrița"]})
        counties = captured["args"][1]
        assert counties == ["iasi", "bistrita"]


class TestMatchExplanation:
    def test_reports_every_reason_that_fired(self):
        lead = api._ranked_row_to_lead({
            "source_id": "X1", "project_title": "Drum judetean",
            "kw_hit": True, "county_hit": True, "domain_hit": False,
            "value_hit": True, "excluded_hit": False, "relevance": 80.0,
            "search_blob": "drum judetean",
        })
        assert lead["match"]["is_match"] is True
        assert lead["match"]["score"] == 80.0
        assert "cuvânt-cheie" in lead["match"]["reasons"]
        assert "județ vizat" in lead["match"]["reasons"]
        assert "domeniu" not in lead["match"]["reasons"]

    def test_unmatched_row_is_still_returned(self):
        """It just isn't badged — this is the whole point of a soft feed."""
        lead = api._ranked_row_to_lead({
            "source_id": "X2", "project_title": "Altceva",
            "kw_hit": False, "county_hit": False, "domain_hit": False,
            "value_hit": False, "excluded_hit": False, "relevance": 3.0,
        })
        assert lead["match"]["is_match"] is False
        assert lead["match"]["reasons"] == []
        assert lead["source_id"] == "X2"

    def test_excluded_row_is_not_badged_as_a_match(self):
        lead = api._ranked_row_to_lead({
            "source_id": "X3", "project_title": "Curatenie birouri",
            "kw_hit": True, "county_hit": False, "domain_hit": False,
            "value_hit": False, "excluded_hit": True, "relevance": -50.0,
        })
        assert lead["match"]["excluded"] is True
        assert lead["match"]["is_match"] is False

    def test_scoring_columns_do_not_leak_into_the_lead(self):
        """The frontend types the lead shape; internal ranking columns are
        not part of it."""
        lead = api._ranked_row_to_lead({
            "source_id": "X4", "project_title": "T",
            "kw_hit": True, "county_hit": False, "domain_hit": False,
            "value_hit": False, "excluded_hit": False, "relevance": 50.0,
            "search_blob": "t",
        })
        for key in ("kw_hit", "county_hit", "domain_hit", "value_hit",
                    "excluded_hit", "relevance", "search_blob"):
            assert key not in lead
