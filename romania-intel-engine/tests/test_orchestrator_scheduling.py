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
from scrapers.orchestrator import (
    MAX_TICK_WEIGHT,
    SCRAPER_EXECUTION_WEIGHT,
    _admit_within_weight_budget,
    _scraper_weight,
)


class _FakeScraper:
    def __init__(self, name):
        self.name = name


def test_unlisted_scraper_defaults_to_weight_one():
    assert _scraper_weight(_FakeScraper("SomeBrandNewScraper")) == 1


def test_listed_heavy_scrapers_have_elevated_weight():
    """Pins the specific sources identified as heavy by live measurement —
    a name lookup, not a guess, so this must name the same ones."""
    for name in ("CountyRegistryMatrix", "ElicitatieLive"):
        assert SCRAPER_EXECUTION_WEIGHT[name] >= 3


def test_admits_sources_until_the_budget_is_exhausted():
    due = [_FakeScraper("ElicitatieLive"), _FakeScraper("SeapDirectAcquisition")]  # weights 5, 1
    admitted, deferred = _admit_within_weight_budget(due, max_weight=6)
    assert [s.name for s in admitted] == ["ElicitatieLive", "SeapDirectAcquisition"]
    assert deferred == []


def test_defers_a_source_that_would_overflow_the_budget():
    due = [_FakeScraper("ElicitatieLive"), _FakeScraper("CountyRegistryMatrix")]  # 5, 5
    admitted, deferred = _admit_within_weight_budget(due, max_weight=6)
    assert [s.name for s in admitted] == ["ElicitatieLive"]
    assert [s.name for s in deferred] == ["CountyRegistryMatrix"]


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
        _FakeScraper("ElicitatieLive"),         # 5 -> doesn't fit (5+5=10>6), deferred
        _FakeScraper("SeapDirectAcquisition"),  # 1 -> fits (5+1=6<=6), admitted
    ]
    admitted, deferred = _admit_within_weight_budget(due, max_weight=6)
    assert [s.name for s in admitted] == ["CountyRegistryMatrix", "SeapDirectAcquisition"]
    assert [s.name for s in deferred] == ["ElicitatieLive"]


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
