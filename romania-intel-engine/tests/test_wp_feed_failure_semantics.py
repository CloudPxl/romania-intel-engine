"""A WordPress feed that cannot be read must not report a successful,
empty run.

fetch_posts swallowed every failure into [], and the orchestrator records
an empty result as SUCCESS with 0 records. A live audit of
/api/v1/system/sources found ProgramEnergie and ProgramSanatate with 31
consecutive zero-result runs against a host that refuses connections
outright, both reported `last_error: null`, `consecutive_failures: 0`,
`circuit_state: closed` — indistinguishable from a feed that simply had no
new funding calls. The circuit breaker therefore never opened, and the
zero-streak alert that eventually fired blamed the page structure for what
was actually a dead host.
"""
import json

import pytest

from scrapers.matrix.energy_scrapers import ProgramEnergieScraper
from scrapers.matrix.wp_json_common import SourceUnreachableError


def _post(pid, title):
    return {
        "id": pid,
        "title": {"rendered": title},
        "content": {"rendered": title},
        "date": "2026-09-01T10:00:00",
        "link": "https://mfe.gov.ro/x",
    }


@pytest.mark.asyncio
async def test_transport_failure_raises_instead_of_reporting_an_empty_success(monkeypatch):
    async def dead(self, url, timeout=30.0):
        return None  # what fetch_url returns for dead DNS / refused / 503

    monkeypatch.setattr(ProgramEnergieScraper, "fetch_url", dead)
    with pytest.raises(SourceUnreachableError):
        await ProgramEnergieScraper().fetch_market_consultations()


@pytest.mark.asyncio
async def test_a_non_json_response_raises(monkeypatch):
    """The 'source page structure changed' case the stale alert describes —
    it has to actually surface as an error for that message to be true."""
    async def html_error_page(self, url, timeout=30.0):
        return "<html><body>502 Bad Gateway</body></html>"

    monkeypatch.setattr(ProgramEnergieScraper, "fetch_url", html_error_page)
    with pytest.raises(SourceUnreachableError):
        await ProgramEnergieScraper().fetch_market_consultations()


@pytest.mark.asyncio
async def test_a_genuinely_empty_feed_is_still_a_successful_empty_run(monkeypatch):
    """The distinction this whole change exists to draw: a feed that was
    read fine and had no posts must NOT raise — an authority publishing
    nothing this week is normal, not a failure."""
    async def empty_feed(self, url, timeout=30.0):
        return "[]"

    monkeypatch.setattr(ProgramEnergieScraper, "fetch_url", empty_feed)
    assert await ProgramEnergieScraper().fetch_market_consultations() == []


@pytest.mark.asyncio
async def test_posts_that_all_fail_the_keyword_gate_are_a_successful_empty_run(monkeypatch):
    """Same rule one level down: MFE serves several domains from one feed,
    so this scraper legitimately matches none of a real, healthy payload."""
    async def health_only_feed(self, url, timeout=30.0):
        return json.dumps([_post(1, "Apel dedicat spitalelor si ambulatoriilor")])

    monkeypatch.setattr(ProgramEnergieScraper, "fetch_url", health_only_feed)
    assert await ProgramEnergieScraper().fetch_market_consultations() == []


@pytest.mark.asyncio
async def test_a_matching_post_still_produces_a_signal(monkeypatch):
    """Regression guard: the raising path must not have broken the happy
    path it sits in front of."""
    async def energy_feed(self, url, timeout=30.0):
        return json.dumps([_post(7, "Apel pentru eficienta energetica si panouri solare")])

    monkeypatch.setattr(ProgramEnergieScraper, "fetch_url", energy_feed)
    signals = await ProgramEnergieScraper().fetch_market_consultations()
    assert len(signals) == 1
    assert signals[0].category == "energie"
