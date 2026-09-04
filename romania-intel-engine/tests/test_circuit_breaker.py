"""An honest empty result and a silently-broken parser look identical to
the circuit breaker above — it only reacts to thrown exceptions, never to
a source quietly returning zero records forever. These pin the second,
independent staleness signal: a dual gate (tick count AND wall-clock time,
scaled by each source's own poll_interval_minutes) that fires an alert
once per zero-result streak without touching circuit_state.
"""
import pytest

import db
from scrapers import circuit_breaker


class TestIsStaleStreak:
    def test_below_tick_floor_does_not_fire(self):
        row = {"consecutive_zero_result_runs": 4, "poll_interval_minutes": 1440, "stale_alert_fired_at": None}
        assert circuit_breaker._is_stale_streak(row) is False

    def test_slow_source_at_five_tick_floor_fires(self):
        # 5 ticks * 1440 min = 5 days — the 24h-interval sources are bound
        # by the tick floor, not the 48h wall-clock minimum.
        row = {"consecutive_zero_result_runs": 5, "poll_interval_minutes": 1440, "stale_alert_fired_at": None}
        assert circuit_breaker._is_stale_streak(row) is True

    def test_fast_source_needs_wall_clock_not_just_tick_count(self):
        # 5 ticks * 10 min = 50 min — nowhere near 48h, must not fire yet
        # even though the tick-count floor is met.
        row = {"consecutive_zero_result_runs": 5, "poll_interval_minutes": 10, "stale_alert_fired_at": None}
        assert circuit_breaker._is_stale_streak(row) is False

    def test_fast_source_fires_once_wall_clock_minimum_reached(self):
        row = {"consecutive_zero_result_runs": 288, "poll_interval_minutes": 10, "stale_alert_fired_at": None}
        assert circuit_breaker._is_stale_streak(row) is True

    def test_already_fired_does_not_fire_again(self):
        row = {
            "consecutive_zero_result_runs": 50, "poll_interval_minutes": 1440,
            "stale_alert_fired_at": "2026-01-01T00:00:00",
        }
        assert circuit_breaker._is_stale_streak(row) is False


class TestRecordResultFiresOncePerStreak:
    @pytest.mark.asyncio
    async def test_success_past_threshold_fires_and_marks(self, monkeypatch):
        async def fake_record_source_run(source_name, status, records, error=None, poll_interval_minutes=360):
            return {"consecutive_zero_result_runs": 5, "poll_interval_minutes": 1440, "stale_alert_fired_at": None}

        marked = []
        fired = []

        async def fake_mark_stale_alert_fired(source_name):
            marked.append(source_name)

        async def fake_close_circuit(source_name):
            pass

        async def fake_fire_stale_alert(source_name, streak, interval_minutes):
            fired.append((source_name, streak, interval_minutes))

        monkeypatch.setattr(db, "record_source_run", fake_record_source_run)
        monkeypatch.setattr(db, "mark_stale_alert_fired", fake_mark_stale_alert_fired)
        monkeypatch.setattr(db, "close_circuit", fake_close_circuit)
        monkeypatch.setattr(circuit_breaker, "_fire_stale_alert", fake_fire_stale_alert)

        await circuit_breaker.record_result("CnairCfrScraper", success=True, error=None, records=0,
                                             poll_interval_minutes=1440)

        assert marked == ["CnairCfrScraper"]
        assert fired == [("CnairCfrScraper", 5, 1440)]

    @pytest.mark.asyncio
    async def test_non_zero_result_does_not_fire(self, monkeypatch):
        async def fake_record_source_run(source_name, status, records, error=None, poll_interval_minutes=360):
            # A non-zero run resets the streak server-side — the returned
            # row reflects that.
            return {"consecutive_zero_result_runs": 0, "poll_interval_minutes": 1440, "stale_alert_fired_at": None}

        fired = []

        async def fake_fire_stale_alert(source_name, streak, interval_minutes):
            fired.append((source_name, streak, interval_minutes))

        async def fake_close_circuit(source_name):
            pass

        monkeypatch.setattr(db, "record_source_run", fake_record_source_run)
        monkeypatch.setattr(db, "close_circuit", fake_close_circuit)
        monkeypatch.setattr(circuit_breaker, "_fire_stale_alert", fake_fire_stale_alert)

        await circuit_breaker.record_result("CnairCfrScraper", success=True, error=None, records=12)

        assert fired == []
