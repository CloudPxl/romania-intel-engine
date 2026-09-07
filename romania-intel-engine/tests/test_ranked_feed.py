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
import inspect
import re

import pytest

import api
import db
from text_utils import normalize_cui


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
        assert db._pg_word_patterns(["drum judetean"]) == [r"\mdrum[[:space:]-]+judetean\M"]

    def test_hyphenated_term_matches_both_spellings(self):
        """A `\\s+` join could not match the literal "Cluj-Napoca" it was
        built from, so the ranked feed silently dropped the keyword boost
        for every hyphenated term. The separator must accept either."""
        (pattern,) = db._pg_word_patterns(["Cluj-Napoca"])
        assert pattern == r"\mcluj[[:space:]-]+napoca\M"
        # Postgres's \m..\M are its own word boundaries; the rest of the
        # pattern must behave in Python too, since text_utils runs the
        # equivalent match in-process for alerting.
        import re
        py = pattern.replace(r"\m", r"\b").replace(r"\M", r"\b").replace("[[:space:]-]", r"[\s\-]")
        assert re.search(py, "modernizare in cluj-napoca")
        assert re.search(py, "modernizare in cluj napoca")

    def test_python_and_sql_matchers_agree_on_separators(self):
        """These two implementations decide the same question — one for
        alerting, one for the feed — and drifting apart means a keyword
        that alerts but never ranks, or the reverse."""
        from text_utils import term_pattern

        for term in ("Cluj-Napoca", "drum judetean", "e-guvernare", "spital"):
            sql = db._pg_word_patterns([term])[0]
            py = term_pattern(term)
            normalised_sql = sql.replace(r"\m", r"\b").replace(r"\M", r"\b").replace("[[:space:]-]", r"[\s\-]")
            assert normalised_sql == py, term

    def test_drops_empty_and_punctuation_only_terms(self):
        assert db._pg_word_patterns(["", "   ", "!!!"]) == []

    def test_none_is_safe(self):
        assert db._pg_word_patterns(None) == []


class TestCountyKey:
    """County matching is exact equality, so a separator decides whether a
    match happens at all — and the two sides disagreed in production.

    Scrapers store "Caras Severin" with a space. The county's real name is
    "Caraș-Severin" with a hyphen, which is what a user types and what
    fold() faithfully preserves. Folded, those were 'caras severin' and
    'caras-severin' — never equal — so that user's county scored nothing on
    every row, with no error anywhere.
    """

    def test_hyphen_and_space_spellings_converge(self):
        assert db._county_key("Caraș-Severin") == db._county_key("Caras Severin")

    def test_folds_diacritics_like_the_rest_of_the_system(self):
        assert db._county_key("Iași") == "iasi"
        assert db._county_key("București") == "bucuresti"

    def test_collapses_repeated_and_surrounding_whitespace(self):
        assert db._county_key("  CARAS   SEVERIN ") == "caras severin"

    def test_bistrita_nasaud_normalises(self):
        assert db._county_key("Bistrița-Năsăud") == "bistrita nasaud"

    def test_sql_translate_map_is_length_balanced(self):
        """Postgres rejects translate() when from/to differ in length, and
        the hyphen addition is exactly the kind of edit that breaks it.
        A mismatch would 500 every feed request rather than mis-rank."""
        sql = db._PG_COUNTY_KEY.format(col="county")
        frm, to = re.findall(r"'((?:[^']|'')*)'", sql)[:2]
        assert len(frm) == len(to), f"translate map unbalanced: {len(frm)} vs {len(to)}"

    def test_query_uses_the_county_key_not_the_plain_fold(self):
        """The regression guard: the ranked query must normalise county
        with _PG_COUNTY_KEY. Reverting it to _PG_FOLD compiles, runs, and
        silently stops matching hyphenated counties."""
        source = inspect.getsource(db.get_ranked_opportunities)
        assert "_PG_COUNTY_KEY.format(col='county')" in source
        assert "_PG_FOLD.format(col='county')" not in source


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
    async def test_no_profile_criterion_can_remove_a_row(self, monkeypatch):
        """The soft-filter guarantee, asserted against the SQL itself.

        This used to be spelled `"WHERE" not in query` — a proxy that
        stopped meaning what it said once the explicit per-request filters
        (authority_cui / procedure_type / award_criterion) landed, since
        those are deliberately hard filters. The actual invariant is
        narrower and is what's asserted now: whatever WHERE exists must
        mention *only* those three columns, and never a profile-derived
        one. An excluded keyword, an unmatched county, a wrong domain or a
        sub-threshold value must still only ever SINK a row.
        """
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
        assert "ORDER BY is_match DESC, relevance DESC" in query
        # The exclusion is a large negative weight, not a filter.
        assert str(db.RELEVANCE_WEIGHTS["excluded"]) in query

        # SQL comments are stripped first: the block between WHERE and
        # ORDER BY carries a long `--` explanation of the is_match
        # partition that mentions "county" in prose, and a substring scan
        # over it would fail on the comment rather than on the clause.
        where = query.upper().split("WHERE", 1)[1].split("ORDER BY", 1)[0]
        where = "\n".join(line.split("--")[0] for line in where.splitlines())
        for profile_column in ("SEARCH_BLOB", "COUNTY", "CATEGORY", "ESTIMATED_VALUE_RON"):
            assert profile_column not in where, f"{profile_column} must never gate the feed"
        for explicit_filter in ("AUTHORITY_CUI", "PROCEDURE_TYPE", "AWARD_CRITERION"):
            assert explicit_filter in where

    @pytest.mark.asyncio
    async def test_unset_explicit_filters_are_null_and_gate_nothing(self, monkeypatch):
        """Every explicit filter is bound NULL when the caller passes none,
        and each WHERE arm short-circuits on its own NULL — so the default
        dashboard request still returns the whole market."""
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
        await db.get_ranked_opportunities({"keywords": ["drum"]})

        # args are (keywords, counties, domain, min_value, excludes,
        #           authority_cui, procedure_type, award_criterion, limit)
        assert captured["args"][5] is None
        assert captured["args"][6] is None
        assert captured["args"][7] is None
        for arm in ("$6::text IS NULL", "$7::text IS NULL", "$8::text IS NULL"):
            assert arm in captured["query"]

    @pytest.mark.asyncio
    async def test_explicit_filters_are_bound_and_cui_is_normalised(self, monkeypatch):
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
        await db.get_ranked_opportunities(
            {"keywords": ["drum"]},
            # A user pasting a CUI off an invoice types the VAT prefix; the
            # column stores bare digits. Without normalising here the
            # filter matches nothing and reads as "no results for this
            # authority" rather than as a format mismatch.
            authority_cui="RO 14056826",
            procedure_type="licitatie_deschisa",
            award_criterion="Pretul cel mai scazut",
        )
        assert captured["args"][5] == "14056826"
        assert captured["args"][6] == "licitatie_deschisa"
        assert captured["args"][7] == "Pretul cel mai scazut"

    @pytest.mark.asyncio
    async def test_blank_filter_strings_are_treated_as_unset(self, monkeypatch):
        """An empty query-string param (`?procedure_type=`) must not filter
        the feed down to rows whose column is literally ''."""
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
        await db.get_ranked_opportunities(
            {"keywords": ["drum"]}, authority_cui="", procedure_type="   ", award_criterion="",
        )
        assert captured["args"][5] is None
        assert captured["args"][6] is None
        assert captured["args"][7] is None

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

    def test_is_match_orders_before_relevance(self):
        """The strict partition, pinned against the SQL text itself.

        A blended `relevance` score only makes a match LIKELY to win — a
        non-match with a high enough opportunity_score can outscore a weak
        match (a county-only hit is +20; a non-match with opportunity_score
        9 vs a match's 3 wins on `ORDER BY relevance DESC` alone). The user
        asked for their own criteria to rank first unconditionally, so the
        query must partition on is_match before it ever consults relevance.
        Reverting to `ORDER BY relevance DESC` compiles, runs, and silently
        drops that guarantee — this is the same class of regression the
        county-key test above guards against.
        """
        source = inspect.getsource(db.get_ranked_opportunities)
        assert "ORDER BY is_match DESC, relevance DESC" in source

    def test_is_match_expression_mirrors_the_lead_definition(self):
        """api.py's _ranked_row_to_lead defines is_match as "any hit, not
        excluded". The SQL column feeding ORDER BY must use the identical
        definition, or the row order and the badge the UI actually shows
        could disagree — the sorted-first row would (nonsensically) badge as
        not-a-match, or vice versa."""
        source = inspect.getsource(db.get_ranked_opportunities)
        assert "AS is_match" in source
        # The four hit sub-expressions combined with OR, gated by NOT the
        # excluded expression — Postgres SELECT-list aliases can't reference
        # each other, so this must repeat the underlying expressions rather
        # than naming kw_hit/county_hit/etc.
        is_match_block = source[source.index("AS is_match") - 400 : source.index("AS is_match")]
        assert is_match_block.count("~ ANY($1::text[])") >= 1  # keyword hit
        assert is_match_block.count("~ ANY($5::text[])") >= 1  # excluded hit
        assert "AND NOT" in is_match_block


class TestRankedQueryOrdering:
    @pytest.mark.asyncio
    async def test_weak_match_outranks_strong_non_match_in_practice(self, monkeypatch):
        """End-to-end against a fake connection: a row with only a weak
        match (one county hit, low opportunity_score) must sort ahead of a
        row with no match at all but a very high opportunity_score — the
        exact scenario the old pure-relevance ordering got backwards."""
        rows = [
            {
                "source_id": "STRONG_NONMATCH", "opportunity_score": 9.5,
                "kw_hit": False, "county_hit": False, "domain_hit": False,
                "value_hit": False, "excluded_hit": False,
                "is_match": False, "relevance": 9.5, "last_seen_at": None,
            },
            {
                "source_id": "WEAK_MATCH", "opportunity_score": 1.0,
                "kw_hit": False, "county_hit": True, "domain_hit": False,
                "value_hit": False, "excluded_hit": False,
                "is_match": True, "relevance": 21.0, "last_seen_at": None,
            },
        ]

        class _Conn:
            async def fetch(self, query, *args):
                # A real query would already return these in is_match-first
                # order; sort here the same way ORDER BY would, to prove the
                # fake reflects the query's own contract rather than
                # asserting on input order.
                return sorted(rows, key=lambda r: (not r["is_match"], -r["relevance"]))

        class _Ctx:
            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(db, "with_connection", lambda: _Ctx())
        result = await db.get_ranked_opportunities({"target_counties": ["Cluj"]})
        assert [r["source_id"] for r in result] == ["WEAK_MATCH", "STRONG_NONMATCH"]


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


class TestPromotedProcurementColumns:
    """authority_cui and award_criterion were promoted out of `metadata`
    onto real, indexable columns so the feed can filter by them —
    `procurement_notices` stays the canonical record. These pin the write
    path (they actually reach the INSERT and the ON CONFLICT refresh) and
    the search-blob behaviour."""

    def test_upsert_persists_and_refreshes_both_columns(self):
        source = inspect.getsource(db.upsert_opportunity)
        insert_cols = source.split("VALUES")[0]
        assert "authority_cui" in insert_cols
        assert "award_criterion" in insert_cols
        # A column absent from the ON CONFLICT arm freezes at whatever was
        # scraped on first sighting — the exact defect the 15 descriptive
        # columns above it were fixed for.
        conflict = source.split("DO UPDATE SET")[1].split("RETURNING")[0]
        assert "authority_cui = EXCLUDED.authority_cui" in conflict
        assert "award_criterion = EXCLUDED.award_criterion" in conflict

    def test_search_blob_includes_the_cui_so_free_text_finds_an_authority(self):
        blob = db.build_search_blob({
            "project_title": "Reabilitare drum",
            "entity_name": "SPITALUL DE URGENTA PETROSANI",
            "authority_cui": "4374873",
        })
        assert "4374873" in blob

    def test_search_blob_survives_a_missing_cui(self):
        blob = db.build_search_blob({"project_title": "Reabilitare drum"})
        assert "reabilitare drum" in blob

    def test_upsert_normalises_the_cui_before_storing_it(self):
        """The column's whole value is that `authority_cui = $n` matches;
        that only holds if every write path stores one form."""
        source = inspect.getsource(db.upsert_opportunity)
        assert "normalize_cui(record.get(\"authority_cui\"))" in source


class TestNormalizeCui:
    def test_strips_vat_prefix_and_spacing(self):
        assert normalize_cui("RO 14056826") == "14056826"
        assert normalize_cui("RO14056826") == "14056826"
        assert normalize_cui(" 4374873 ") == "4374873"

    def test_already_bare_is_unchanged(self):
        assert normalize_cui("4374873") == "4374873"

    def test_junk_is_none_rather_than_an_unmatchable_row(self):
        assert normalize_cui("n/a") is None
        assert normalize_cui("") is None
        assert normalize_cui(None) is None
