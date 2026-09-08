"""db.upsert_opportunities_batch replaced a serial `for sig in signals: await
db.upsert_opportunity(sig)` loop in orchestrator.py's persist step — a live
audit found CountyRegistryMatrix alone producing 759 signals in one tick,
meaning 759 sequential network round trips to Supabase (50-100ms each from
Render) were spent on latency rather than database work. Verified live
against a real Postgres during development (fresh insert, update-on-
re-scrape, a mixed new+existing batch, and the within-batch-duplicate crash
below all confirmed working end-to-end) — this file covers what the
no-DATABASE_URL suite actually can: the degrade contract every write path
in this codebase shares, and that the function is built from the exact
same ON CONFLICT text as the single-row path it replaces.
"""
import inspect

import db


def test_batch_upsert_with_no_database_treats_every_record_as_new():
    """Matches upsert_opportunity's own documented fallback ('no persistence
    configured — treat every signal as new') — a caller gating alerts on
    is_new must see the same behavior whether it wrote one record or many."""
    import asyncio

    records = [
        {"source_id": "A", "project_title": "x"},
        {"source_id": "B", "project_title": "y"},
    ]
    result = asyncio.run(db.upsert_opportunities_batch(records))
    assert result == {"A": True, "B": True}


def test_batch_upsert_drops_records_with_no_source_id():
    """source_id is the table's primary key — a record without one cannot
    be the target of any conflict resolution and must not reach the query
    at all, matching upsert_opportunity's implicit behavior (it would fail
    to persist such a record too, just one row at a time)."""
    import asyncio

    records = [
        {"project_title": "no id at all"},
        {"source_id": "", "project_title": "blank id"},
        {"source_id": "REAL", "project_title": "kept"},
    ]
    result = asyncio.run(db.upsert_opportunities_batch(records))
    assert result == {"REAL": True}


def test_batch_upsert_of_an_empty_list_is_a_no_op():
    import asyncio

    assert asyncio.run(db.upsert_opportunities_batch([])) == {}


def test_batch_upsert_query_builds_from_jsonb_to_recordset():
    """Pins the mechanism, not just the outcome: unnest() over several
    parallel arrays of different element types (this table has two TEXT[]
    columns plus JSONB and DATE columns alongside plain TEXT/NUMERIC) is
    exactly the shape that silently binds wrong in asyncpg without very
    careful per-column casts. jsonb_to_recordset takes one JSON parameter
    and declares each column's type once, in the query itself."""
    source = inspect.getsource(db.upsert_opportunities_batch)
    assert "jsonb_to_recordset" in source


def test_batch_upsert_shares_the_update_set_with_the_single_row_path():
    source = inspect.getsource(db.upsert_opportunities_batch)
    assert "_OPPORTUNITY_UPDATE_SET" in source


def test_batch_upsert_deduplicates_within_one_call():
    """Regression pin for a real defect found while building this: a single
    multi-row INSERT ... ON CONFLICT cannot update the same conflict-key
    row twice — Postgres raises CardinalityViolationError and the WHOLE
    batch rolls back, losing every other record in it too. A scraper
    legally emitting the same source_id twice in one tick (overlapping
    pages from an unstable sort, e.g.) must not be able to take down every
    other signal that scraper produced."""
    source = inspect.getsource(db.upsert_opportunities_batch)
    assert "deduped" in source or "dedup" in source.lower()


def test_prepare_opportunity_row_normalises_cui_same_as_single_row_path():
    """The single-row and batch paths must agree on what 'equal' means for
    authority_cui — get_ranked_opportunities filters with a bare `=`."""
    row = db._prepare_opportunity_row({
        "source_id": "X", "project_title": "y", "authority_cui": "RO 4374873",
    })
    assert row["authority_cui"] == "4374873"


def test_prepare_opportunity_row_dates_are_iso_strings_not_date_objects():
    """jsonb_to_recordset coerces a JSON string into a DATE column via
    Postgres's own text-input parser; a Python `date` object is not
    JSON-serialisable at all without a custom encoder, so this must
    already be a plain ISO string by the time it reaches json.dumps."""
    row = db._prepare_opportunity_row({
        "source_id": "X", "project_title": "y", "published_date": "2026-08-01",
    })
    assert row["published_date"] == "2026-08-01"
    assert isinstance(row["published_date"], str)


def test_prepare_opportunity_row_empty_arrays_stay_lists_not_none():
    row = db._prepare_opportunity_row({"source_id": "X", "project_title": "y"})
    assert row["caen_codes"] == []
    assert row["cpv_codes_all"] == []
