"""upsert_opportunity's ON CONFLICT clause used to refresh only 6 of ~21
columns on a re-scrape — the other 15 (title, county, entity name, funding
source, ...) froze at whatever was written on first insert and never
updated again, even when the same source_id was re-scraped and the source
corrected itself. This pins the fix with the same inspect.getsource()
technique test_ranked_feed.py already uses to guard the county-key fix
from a silent revert — a future edit that quietly drops a column back out
of the UPDATE SET fails this test, not silently in production.
"""
import inspect

import db


def test_all_descriptive_columns_refresh_on_rescrape():
    source = inspect.getsource(db.upsert_opportunity)
    conflict_clause = source[source.index("ON CONFLICT") :]

    previously_frozen_columns = [
        "source_type", "category", "sub_category", "county", "locality",
        "entity_name", "project_title", "caen_codes", "cpv_code",
        "published_date", "executive_summary", "sales_pitch_angle",
        "funding_source", "source_url", "document_url",
    ]
    for column in previously_frozen_columns:
        assert f"{column} = EXCLUDED.{column}" in conflict_clause, (
            f"{column} is not refreshed on re-scrape — it will freeze at whatever "
            "was written on first insert."
        )

    # Unaffected by this change — first_seen_at must stay the true
    # first-seen timestamp, and source_id is the conflict key itself.
    assert "first_seen_at = EXCLUDED.first_seen_at" not in conflict_clause
    assert "source_id = EXCLUDED.source_id" not in conflict_clause
