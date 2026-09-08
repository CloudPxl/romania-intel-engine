"""upsert_opportunity's ON CONFLICT clause used to refresh only 6 of ~21
columns on a re-scrape — the other 15 (title, county, entity name, funding
source, ...) froze at whatever was written on first insert and never
updated again, even when the same source_id was re-scraped and the source
corrected itself. This pins the fix.

Checked against db._OPPORTUNITY_UPDATE_SET rather than
inspect.getsource(db.upsert_opportunity)'s own text: the clause was
factored out into that module-level constant so upsert_opportunity and the
batch write path (db.upsert_opportunities_batch, added alongside a
performance pass that stopped persisting a whole tick's signals one
network round trip at a time) share the literal same SQL text and cannot
silently diverge on which columns "latest scrape wins" covers. Asserting
against the shared constant guards both call sites from one place instead
of needing an independent regex per query string; a
test_upsert_opportunity_query_references_the_shared_clause test below pins
that upsert_opportunity actually uses it, so the two checks together give
the same protection the single inspect.getsource() check used to.
"""
import inspect

import db


PREVIOUSLY_FROZEN_COLUMNS = [
    "source_type", "category", "sub_category", "county", "locality",
    "entity_name", "project_title", "caen_codes", "cpv_code",
    "published_date", "executive_summary", "sales_pitch_angle",
    "funding_source", "source_url", "document_url",
]


def test_all_descriptive_columns_refresh_on_rescrape():
    conflict_clause = db._OPPORTUNITY_UPDATE_SET

    for column in PREVIOUSLY_FROZEN_COLUMNS:
        assert f"{column} = EXCLUDED.{column}" in conflict_clause, (
            f"{column} is not refreshed on re-scrape — it will freeze at whatever "
            "was written on first insert."
        )

    # Unaffected by this change — first_seen_at must stay the true
    # first-seen timestamp, and source_id is the conflict key itself.
    assert "first_seen_at = EXCLUDED.first_seen_at" not in conflict_clause
    assert "source_id = EXCLUDED.source_id" not in conflict_clause


def test_upsert_opportunity_query_references_the_shared_clause():
    """Pins that upsert_opportunity actually builds its query from the
    constant above, rather than a second, independently-typed copy of the
    same SQL that could quietly drift from it."""
    source = inspect.getsource(db.upsert_opportunity)
    assert "_OPPORTUNITY_UPDATE_SET" in source


def test_batch_upsert_query_references_the_shared_clause():
    """Same guarantee for the batch write path — both must stay built from
    the one shared string, or a future edit to only one of them silently
    reintroduces the exact divergence this test file exists to prevent."""
    source = inspect.getsource(db.upsert_opportunities_batch)
    assert "_OPPORTUNITY_UPDATE_SET" in source
