"""The pipeline must survive its own stored timestamps.

`GET /api/v1/me/pipeline/metrics` returned a 500 the moment a user saved
their first deal. The two persistence paths disagreed about tzinfo:

* Postgres stores `created_at` as TIMESTAMPTZ, and db._deal_row_to_dict
  renders it with `.isoformat()`, which keeps the `+00:00` offset.
* The in-memory fallback stored `datetime.now().isoformat()` — naive.

`get_pipeline_metrics` then did `datetime.now() - entered_at` with a naive
`now`, which raises `TypeError: can't subtract offset-naive and
offset-aware datetimes` against the Postgres value. It escaped to the
global handler as an opaque "A apărut o eroare neașteptată pe server".

The reason this shipped is worth keeping in the test name: the suite runs
without DATABASE_URL, so every existing test exercised the in-memory path,
where both sides are naive and the bug cancels out. These tests use the
Postgres-shaped timestamp explicitly.
"""
from datetime import datetime, timedelta, timezone

import pytest

import workflow_engine
from workflow_engine import ConcurrentWorkflowEngine as Engine


def _pg_deal(**overrides):
    """A deal shaped the way db._deal_row_to_dict returns one."""
    deal = {
        "deal_id": "DEAL-TEST",
        "user_id": "u1",
        "project_title": "Modernizare DJ 103",
        "stage": "discovery",
        "estimated_value_ron": 1_200_000.0,
        "proposed_price": None,
        # The offset is the whole point.
        "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        "stage_history": [],
    }
    deal.update(overrides)
    return deal


def test_aware_created_at_does_not_crash_duration_maths():
    durations = Engine._stage_durations_days(_pg_deal(), workflow_engine._now())
    assert durations["discovery"] == pytest.approx(3.0, abs=0.01)


def test_naive_created_at_still_works():
    """The in-memory fallback path must keep working — it is what runs
    when DATABASE_URL is unset."""
    deal = _pg_deal(created_at=(datetime.now() - timedelta(days=2)).isoformat())
    durations = Engine._stage_durations_days(deal, workflow_engine._now())
    assert durations["discovery"] == pytest.approx(2.0, abs=0.01)


def test_mixed_aware_history_against_naive_created_at():
    """A deal created before the fix (naive) that transitioned after it
    (aware) has both shapes in one record."""
    deal = _pg_deal(
        created_at=(datetime.now() - timedelta(days=5)).isoformat(),
        stage="bid_submitted",
        stage_history=[
            {"from": "discovery", "to": "bid_submitted",
             "at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},
        ],
    )
    durations = Engine._stage_durations_days(deal, workflow_engine._now())
    assert durations["discovery"] == pytest.approx(4.0, abs=0.01)
    assert durations["bid_submitted"] == pytest.approx(1.0, abs=0.01)


def test_unparseable_created_at_degrades_to_empty_not_an_exception():
    assert Engine._stage_durations_days(_pg_deal(created_at="nu-i o dată"), workflow_engine._now()) == {}
    assert Engine._stage_durations_days(_pg_deal(created_at=None), workflow_engine._now()) == {}


@pytest.mark.asyncio
async def test_metrics_end_to_end_over_postgres_shaped_deals(monkeypatch):
    """The actual 500: the route calls get_pipeline_metrics, which calls
    _stage_durations_days for every deal."""
    deals = [
        _pg_deal(deal_id="D1", stage="discovery"),
        _pg_deal(deal_id="D2", stage="bid_submitted", estimated_value_ron=500_000.0,
                 stage_history=[{"from": "discovery", "to": "bid_submitted",
                                 "at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}]),
        _pg_deal(deal_id="D3", stage="won", proposed_price=900_000.0),
    ]
    monkeypatch.setattr(workflow_engine.db, "get_deals_for_user", _async_return(deals))

    metrics = await Engine.get_pipeline_metrics("u1")

    assert metrics["total_deals"] == 3
    assert metrics["won_deals"] == 1
    assert metrics["active_deals"] == 2
    # A won deal uses its proposed_price over the estimate.
    assert metrics["won_value_ron"] == 900_000.0
    # 1_200_000 * 0.10 + 500_000 * 0.70
    assert metrics["weighted_pipeline_value_ron"] == pytest.approx(470_000.0)
    assert metrics["average_days_in_stage"]["discovery"] > 0


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


def test_new_timestamps_are_timezone_aware():
    """Writes must be aware too: asyncpg reads a naive datetime into a
    TIMESTAMPTZ column as UTC, so on a host whose clock is not UTC every
    deal timestamp was silently shifted by the offset."""
    assert workflow_engine._now().tzinfo is not None
