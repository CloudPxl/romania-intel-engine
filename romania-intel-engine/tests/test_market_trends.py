"""Prima Pagina's personalized market-trends aggregation.

GET /api/v1/me/market-trends reuses the same county/category/funding-source
aggregation as the public GET /api/v1/analysis/market-trends, but scoped to
one user's own matches — "metrics that only serve the user's custom
criteria," not the whole market with matches merely ranked higher. These
tests pin that scoping and the no-matches fallback, since both are easy to
get backwards (aggregating over everything and just labeling it
"personalized" would pass a shallow smoke test while silently failing the
actual requirement).
"""
import pytest
from fastapi.testclient import TestClient

import api
import security


def _lead(source_id, *, matched, value=1_000_000, county="Cluj", category="infrastructura"):
    return {
        "source_id": source_id,
        "project_title": f"Proiect {source_id}",
        "entity_name": "Primaria Test",
        "county": county,
        "category": category,
        "financial_value_ron": value,
        "opportunity_score": 5.0,
        "match": {"is_match": matched, "excluded": False, "reasons": ["cuvânt-cheie"] if matched else []},
    }


class TestMyMarketTrendsRoute:
    @pytest.fixture(autouse=True)
    def _auth_override(self):
        api.app.dependency_overrides[security.require_auth] = lambda: {
            "user_id": "route-uid", "email": "ion@test.ro", "role": "Membru"
        }
        yield
        api.app.dependency_overrides.pop(security.require_auth, None)

    def test_requires_authentication(self):
        api.app.dependency_overrides.pop(security.require_auth, None)
        try:
            r = TestClient(api.app).get("/api/v1/me/market-trends")
            assert r.status_code == 401
        finally:
            api.app.dependency_overrides[security.require_auth] = lambda: {
                "user_id": "route-uid", "email": "ion@test.ro", "role": "Membru"
            }

    def test_aggregates_only_over_matches_when_any_exist(self, monkeypatch):
        leads = [
            _lead("MATCH1", matched=True, value=1_000_000, county="Cluj"),
            _lead("MATCH2", matched=True, value=500_000, county="Cluj"),
            # A much larger non-match must NOT inflate the personalized
            # totals — that would be "the whole market, mislabeled",
            # exactly the failure mode this test exists to catch.
            _lead("HUGE_NONMATCH", matched=False, value=50_000_000, county="Timis"),
        ]

        async def fake_get_my_feed(user_id, **kwargs):
            return {"leads": leads, "data_updated_at": "2026-01-01T00:00:00Z"}

        monkeypatch.setattr(api, "get_my_feed", fake_get_my_feed)

        r = TestClient(api.app).get("/api/v1/me/market-trends")
        assert r.status_code == 200
        body = r.json()

        assert body["is_personalized"] is True
        assert body["total_leads"] == 2
        assert body["total_market_value_ron"] == 1_500_000
        counties = {c["county"] for c in body["by_county"]}
        assert counties == {"Cluj"}
        top_ids = {o["source_id"] for o in body["top_opportunities"]}
        assert "HUGE_NONMATCH" not in top_ids
        assert top_ids == {"MATCH1", "MATCH2"}

    def test_falls_back_to_full_market_when_nothing_matches(self, monkeypatch):
        """A profile that currently matches nothing must not render an
        empty personalized page — same rule /cautare-avansata already
        applies, surfaced here as an explicit, checkable flag rather than
        left for the frontend to infer from an empty list."""
        leads = [
            _lead("A", matched=False, value=1_000_000),
            _lead("B", matched=False, value=2_000_000),
        ]

        async def fake_get_my_feed(user_id, **kwargs):
            return {"leads": leads, "data_updated_at": None}

        monkeypatch.setattr(api, "get_my_feed", fake_get_my_feed)

        r = TestClient(api.app).get("/api/v1/me/market-trends")
        assert r.status_code == 200
        body = r.json()

        assert body["is_personalized"] is False
        assert body["total_leads"] == 2
        assert body["total_market_value_ron"] == 3_000_000

    def test_top_opportunities_carry_source_id(self, monkeypatch):
        """The frontend click-through (?openLead=<source_id>) needs this
        field; the original /analysis aggregation never included it because
        nothing there consumed it before this feature existed."""
        leads = [_lead("X1", matched=True)]

        async def fake_get_my_feed(user_id, **kwargs):
            return {"leads": leads, "data_updated_at": None}

        monkeypatch.setattr(api, "get_my_feed", fake_get_my_feed)

        body = TestClient(api.app).get("/api/v1/me/market-trends").json()
        assert body["top_opportunities"][0]["source_id"] == "X1"

    def test_degraded_feed_is_reported_not_hidden(self, monkeypatch):
        async def fake_get_my_feed(user_id, **kwargs):
            return {"leads": [], "degraded": True, "detail": "Baza de date nu a răspuns."}

        monkeypatch.setattr(api, "get_my_feed", fake_get_my_feed)

        body = TestClient(api.app).get("/api/v1/me/market-trends").json()
        assert body["degraded"] is True
        assert body["is_personalized"] is False


class TestPublicMarketTrendsUnaffectedByRefactor:
    """The aggregation body moved into a shared helper; this pins that the
    existing public route's own contract (top_opportunities empty for
    anonymous callers, is_authenticated flag) survived the move intact."""

    def test_anonymous_caller_gets_aggregates_but_no_named_opportunities(self, monkeypatch):
        async def fake_load_feed(filters):
            return {"leads": [_lead("A", matched=True, value=1_000_000)], "updated_at": None}

        import api as api_module
        monkeypatch.setattr(api_module, "_load_feed", fake_load_feed)

        body = TestClient(api.app).get("/api/v1/analysis/market-trends").json()
        assert body["is_authenticated"] is False
        assert body["top_opportunities"] == []
        assert body["total_leads"] == 1
