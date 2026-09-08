"""Per-tick execution-weight admission control (_admit_within_weight_budget,
SCRAPER_EXECUTION_WEIGHT, MAX_TICK_WEIGHT).

due.sort(key=poll_interval_minutes) orders scrapers by time-sensitivity, but
every due scraper's task starts concurrently via asyncio.create_task — sort
order alone never bounded how much CPU-bound work actually ran together in
one tick. A live audit found real, working scrapers (CountyRegistryMatrix
fanning out across 35 counties, ElicitatieLive issuing a detail fetch per
item) losing the tick deadline race on Render's 0.1 CPU whenever enough
other sources were simultaneously due — not occasionally, but on every
single attempt, since all tasks start together regardless of list position.
This bounds how many of the due sources are even attempted together, so the
heaviest ones stop competing with the entire rest of the due list at once.
"""
from datetime import datetime, timedelta, timezone

from scrapers.orchestrator import (
    MAX_TICK_WEIGHT,
    SCRAPER_EXECUTION_WEIGHT,
    _admit_within_weight_budget,
    _due_with_priority,
    _feature_enabled,
    _scraper_weight,
)


class _FakeScraper:
    def __init__(self, name):
        self.name = name


def test_unlisted_scraper_defaults_to_weight_one():
    assert _scraper_weight(_FakeScraper("SomeBrandNewScraper")) == 1


def test_the_multi_county_fan_out_is_the_heaviest_source():
    """CountyRegistryMatrix is the one genuine fan-out (up to 35 counties x
    2 adapter calls, measured 65-100s), so nothing may be weighted above
    it and it must stay well clear of the baseline."""
    assert SCRAPER_EXECUTION_WEIGHT["CountyRegistryMatrix"] == max(SCRAPER_EXECUTION_WEIGHT.values())
    assert SCRAPER_EXECUTION_WEIGHT["CountyRegistryMatrix"] >= 5


def test_elicitatie_is_moderate_not_fan_out_heavy():
    """It was weighted 5 — the same as the 35-county fan-out — for issuing
    a detail fetch per item, when it actually pulls one 20-item page and
    one GET each (~21 bounded requests, ~20s).

    The absolute number matters less than this relationship, which is what
    was wrong: paired with its 10-minute interval, weight 5 made this one
    source demand 66% of the fleet's entire daily weight budget and take 5
    of every 6 units whenever it was due, starving the heavy daily sources
    it was mistakenly grouped with.
    """
    assert SCRAPER_EXECUTION_WEIGHT["ElicitatieLive"] > 1, "still above the light baseline"
    assert SCRAPER_EXECUTION_WEIGHT["ElicitatieLive"] < SCRAPER_EXECUTION_WEIGHT["CountyRegistryMatrix"]


def test_a_single_source_cannot_monopolise_the_tick_budget():
    """The concrete invariant behind the two tests above: no source may be
    heavy enough to take the whole budget on its own, or admitting it
    defers everything else by construction (which is what happened)."""
    for name, weight in SCRAPER_EXECUTION_WEIGHT.items():
        assert weight < MAX_TICK_WEIGHT, f"{name} alone consumes the entire per-tick budget"


def test_admits_sources_until_the_budget_is_exhausted():
    due = [_FakeScraper("ElicitatieLive"), _FakeScraper("SeapDirectAcquisition")]  # weights 2, 1
    admitted, deferred = _admit_within_weight_budget(due, max_weight=6)
    assert [s.name for s in admitted] == ["ElicitatieLive", "SeapDirectAcquisition"]
    assert deferred == []


def test_defers_a_source_that_would_overflow_the_budget():
    due = [_FakeScraper("CountyRegistryMatrix"), _FakeScraper("GalatiMunicipal")]  # 5, 3
    admitted, deferred = _admit_within_weight_budget(due, max_weight=6)
    assert [s.name for s in admitted] == ["CountyRegistryMatrix"]
    assert [s.name for s in deferred] == ["GalatiMunicipal"]


def test_a_single_heavy_source_is_always_admitted_even_over_budget():
    """Otherwise a source heavier than MAX_TICK_WEIGHT could never run, on
    any tick, ever — the exact permanent-starvation failure mode this
    whole feature exists to fix, just moved to a different cause."""
    due = [_FakeScraper("CountyRegistryMatrix")]  # weight 5
    admitted, deferred = _admit_within_weight_budget(due, max_weight=3)
    assert [s.name for s in admitted] == ["CountyRegistryMatrix"]
    assert deferred == []


def test_first_fit_lets_a_later_light_source_through_after_a_skip():
    """A source that doesn't fit is skipped, not a hard stop — scanning
    continues so a smaller source further down the priority-sorted list
    can still be admitted in the remaining budget."""
    due = [
        _FakeScraper("CountyRegistryMatrix"),  # 5 -> admitted (5/6)
        _FakeScraper("GalatiMunicipal"),        # 3 -> doesn't fit (5+3=8>6), deferred
        _FakeScraper("SeapDirectAcquisition"),  # 1 -> fits (5+1=6<=6), admitted
    ]
    admitted, deferred = _admit_within_weight_budget(due, max_weight=6)
    assert [s.name for s in admitted] == ["CountyRegistryMatrix", "SeapDirectAcquisition"]
    assert [s.name for s in deferred] == ["GalatiMunicipal"]


def test_order_is_preserved_within_each_returned_list():
    due = [_FakeScraper(n) for n in ("A", "B", "C", "D")]
    admitted, deferred = _admit_within_weight_budget(due, max_weight=2)
    assert [s.name for s in admitted] == ["A", "B"]
    assert [s.name for s in deferred] == ["C", "D"]


def test_empty_due_list_admits_nothing_and_defers_nothing():
    admitted, deferred = _admit_within_weight_budget([], max_weight=MAX_TICK_WEIGHT)
    assert admitted == []
    assert deferred == []


def test_max_tick_weight_is_a_positive_env_overridable_default():
    assert MAX_TICK_WEIGHT > 0


# --------------------------------------------------- fairness / due order

class _FakeSource:
    def __init__(self, name, poll_interval_minutes):
        self.name = name
        self.poll_interval_minutes = poll_interval_minutes


def _at(minutes_ago):
    return NOW - timedelta(minutes=minutes_ago)


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def test_a_source_inside_its_interval_is_not_due():
    fast = _FakeSource("Fast", 15)
    assert _due_with_priority([fast], {"Fast": _at(10)}, NOW) == []


def test_a_source_exactly_at_its_interval_is_due():
    """The boundary is inclusive — ratio 1.0 counts as due, matching
    db.is_source_due's `elapsed >= poll_interval_minutes`."""
    fast = _FakeSource("Fast", 15)
    assert [s.name for s in _due_with_priority([fast], {"Fast": _at(15)}, NOW)] == ["Fast"]


def test_a_never_run_source_goes_first():
    """Ranked inf, so a newly-enabled scraper gets its first row promptly
    rather than queueing behind the whole established backlog."""
    fresh = _FakeSource("NeverRun", 1440)
    overdue = _FakeSource("Overdue", 15)
    order = _due_with_priority([overdue, fresh], {"Overdue": _at(60)}, NOW)
    assert [s.name for s in order] == ["NeverRun", "Overdue"]


def test_the_more_overdue_source_wins_regardless_of_interval():
    """The starvation fix. Under the old interval-only sort the 15-minute
    feed sorted first on every tick forever; here the daily source that has
    been deferred for two full days outranks it."""
    fast = _FakeSource("Fast", 15)          # 20min late  -> ratio 1.33
    heavy = _FakeSource("HeavyDaily", 1440)  # 2 days late -> ratio 2.0
    order = _due_with_priority([fast, heavy], {"Fast": _at(20), "HeavyDaily": _at(2880)}, NOW)
    assert [s.name for s in order] == ["HeavyDaily", "Fast"]


def test_a_freshly_run_daily_source_does_not_outrank_a_late_fast_feed():
    """The mirror-image failure the ratio exists to avoid: sorting by raw
    age would put a daily source that ran 20 hours ago ahead of a 15-minute
    feed that is genuinely late, even though the daily one is not due."""
    fast = _FakeSource("Fast", 15)            # 30min late -> ratio 2.0
    heavy = _FakeSource("HeavyDaily", 1440)   # 20h        -> ratio 0.83, not due
    order = _due_with_priority([fast, heavy], {"Fast": _at(30), "HeavyDaily": _at(1200)}, NOW)
    assert [s.name for s in order] == ["Fast"]


def test_starvation_is_self_correcting_over_successive_ticks():
    """The property that makes this work without a deferral counter: each
    tick a source is passed over, its ratio climbs, so it must eventually
    outrank the sources that keep beating it."""
    fast = _FakeSource("Fast", 15)
    heavy = _FakeSource("HeavyDaily", 1440)
    heavy_last_run = 1440  # exactly due
    seen_heavy_first = False
    for _ in range(60):
        order = _due_with_priority(
            [fast, heavy], {"Fast": _at(16), "HeavyDaily": _at(heavy_last_run)}, NOW
        )
        if order and order[0].name == "HeavyDaily":
            seen_heavy_first = True
            break
        heavy_last_run += 60  # deferred another hour
    assert seen_heavy_first, "a perpetually-deferred source never reached the front"


def test_cold_start_ties_are_broken_by_interval_not_declaration_order():
    """Every source scores inf on a cold database, so without an explicit
    tie-break the order would be whatever __init__ happens to append — which
    puts the conditionally-registered 15-minute SEAP feeds last."""
    declared = [
        _FakeSource("SlowDaily", 1440),
        _FakeSource("Medium", 360),
        _FakeSource("FastSeap", 15),
    ]
    order = _due_with_priority(declared, {}, NOW)
    assert [s.name for s in order] == ["FastSeap", "Medium", "SlowDaily"]


def test_no_database_treats_every_source_as_due():
    """db.get_source_last_run_map returns None when unconfigured; the tick
    must degrade open exactly as db.is_source_due always did."""
    sources = [_FakeSource("A", 15), _FakeSource("B", 1440)]
    assert len(_due_with_priority(sources, None, NOW)) == 2


# ------------------------------------------------------- feature defaults

def test_the_five_live_source_flags_default_on(monkeypatch):
    """They defaulted off, and render.yaml's "true" never reached the
    running process — so 7 of 26 sources were silently absent from
    production ingestion. Unset must now mean enabled."""
    for var in (
        "ENABLE_LIVE_ELICITATIE", "ENABLE_LIVE_DIRECT_ACQUISITION",
        "ENABLE_LIVE_CONTRACT_NOTICES", "ENABLE_LIVE_COUNTY_REGISTRY",
        "ENABLE_LIVE_TED",
    ):
        monkeypatch.delenv(var, raising=False)
        assert _feature_enabled(var) is True


def test_a_flag_can_still_be_turned_off(monkeypatch):
    """The kill switch each flag was added for has to survive the default
    flip, or a misbehaving upstream can no longer be shut off without a
    code change."""
    for value in ("false", "False", "0", "no", "off", ""):
        monkeypatch.setenv("ENABLE_LIVE_TED", value)
        assert _feature_enabled("ENABLE_LIVE_TED") is False
    for value in ("true", "TRUE", "1", "yes", " true "):
        monkeypatch.setenv("ENABLE_LIVE_TED", value)
        assert _feature_enabled("ENABLE_LIVE_TED") is True


def test_all_twenty_six_sources_register_by_default(monkeypatch):
    """The end-to-end statement of the bug: with no env vars set at all,
    every source the matrix declares must actually be constructed."""
    for var in (
        "ENABLE_LIVE_ELICITATIE", "ENABLE_LIVE_DIRECT_ACQUISITION",
        "ENABLE_LIVE_CONTRACT_NOTICES", "ENABLE_LIVE_COUNTY_REGISTRY",
        "ENABLE_LIVE_TED",
    ):
        monkeypatch.delenv(var, raising=False)
    from scrapers.orchestrator import OpportunityOrchestrator

    names = {s.name for s in OpportunityOrchestrator().scrapers}
    for expected in (
        "ElicitatieLive", "SeapDirectAcquisition", "SeapDaAwardNotice",
        "SeapContractNotice", "SeapSimplifiedContractNotice",
        "CountyRegistryMatrix", "TedRomania",
    ):
        assert expected in names, f"{expected} is not registered with default env"
    assert len(names) == 26
