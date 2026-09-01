"""Every error response must stay readable to a browser.

A cross-origin response without Access-Control-Allow-Origin is discarded
by the browser before JavaScript ever sees it: fetch() rejects with a bare
network error rather than surfacing the status or body. The frontend
(lib/api.ts decodes FastAPI's `detail`; AuthContext falls back to
"serverul nu răspunde" when the thrown error isn't an ApiError) therefore
reports a *healthy, correctly-answering* API as an outage.

That is not hypothetical — it caused a total login outage. Two response
paths were being produced OUTSIDE CORSMiddleware and so shipped without
the header:

  * the rate limiter's 429, because rate_limit_middleware had been
    registered after CORSMiddleware, which puts it outside;
  * an unhandled 500, because a handler registered for `Exception` is
    pulled out by Starlette and attached to ServerErrorMiddleware, which
    is unconditionally the outermost layer of all.

Both were invisible from curl, which does not enforce CORS at all — the
responses looked perfectly fine outside a browser. These tests are the
guard, since the failure mode is silent everywhere else.

The ordering these assert is load-bearing, not cosmetic: in api.py,
CORSMiddleware must remain the LAST middleware registered so that it ends
up outermost and every inner response passes back out through it.
"""
import pytest
from fastapi.testclient import TestClient

import api
from security import RATE_LIMIT_REQUESTS, RATE_LIMIT_STORE

ORIGIN = "https://ro-intel.xyz"


@pytest.fixture
def client():
    RATE_LIMIT_STORE.clear()
    yield TestClient(api.app, raise_server_exceptions=False)
    RATE_LIMIT_STORE.clear()


def _assert_readable(response, expected_status):
    assert response.status_code == expected_status
    assert response.headers.get("access-control-allow-origin") == ORIGIN, (
        f"{expected_status} response has no Access-Control-Allow-Origin — a browser "
        "will discard it and report a network error instead of this status. "
        "Check that CORSMiddleware is still the LAST middleware registered in api.py."
    )
    assert isinstance(response.json().get("detail"), str), "error body must carry a decodable `detail`"


def test_cors_middleware_is_outermost():
    """Index 0 is the outermost layer; everything else must sit inside it."""
    outermost = api.app.user_middleware[0]
    assert "CORSMiddleware" in str(outermost), (
        f"CORSMiddleware is not outermost (found {outermost}). Any response produced by a "
        "middleware outside it — a 429, a caught 500 — reaches the browser with no CORS "
        "headers and presents as an outage. Register CORSMiddleware LAST in api.py."
    )


def test_auth_rejection_is_readable(client):
    """The baseline: a route-dependency HTTPException was always fine."""
    _assert_readable(
        client.post("/api/v1/auth/sync", headers={"Origin": ORIGIN}, json={"email": "a@b.co"}),
        401,
    )


def test_rate_limit_rejection_is_readable(client):
    """The 429 that caused the outage — produced by middleware, not a route."""
    response = None
    for _ in range(RATE_LIMIT_REQUESTS + 5):
        response = client.post("/api/v1/auth/sync", headers={"Origin": ORIGIN}, json={"email": "a@b.co"})
        if response.status_code == 429:
            break
    _assert_readable(response, 429)


def test_unhandled_exception_is_readable(client):
    """A genuine crash must arrive as a readable 500, not a network error."""

    @api.app.get("/__test_boom")
    async def _boom():
        raise RuntimeError("simulated crash")

    try:
        _assert_readable(client.get("/__test_boom", headers={"Origin": ORIGIN}), 500)
    finally:
        api.app.router.routes = [
            r for r in api.app.router.routes if getattr(r, "path", None) != "/__test_boom"
        ]


def test_disallowed_origin_gets_no_cors_header(client):
    """The header is granted to the allowlist only — not to everyone."""
    response = client.post(
        "/api/v1/auth/sync", headers={"Origin": "https://attacker.example"}, json={"email": "a@b.co"}
    )
    assert response.headers.get("access-control-allow-origin") is None
