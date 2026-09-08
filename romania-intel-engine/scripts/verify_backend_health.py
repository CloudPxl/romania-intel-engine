"""Non-destructive, dependency-light synthetic health check for the deployed
RO-INTEL API and its database — safe to run on-demand, in CI, or wired into
an external uptime monitor (cron, GitHub Actions, UptimeRobot's "command"
mode via a thin wrapper, etc.).

Rewritten from a version with three real defects, each of which would have
made this script actively misleading rather than merely incomplete:

  1. It targeted RENDER_API = "https://ro-intel-engine.onrender.com" — a
     hostname that does still answer (Render always keeps a service's own
     onrender.com subdomain live alongside a custom domain), but bypasses
     the actual production edge users and the frontend hit. CLAUDE.md
     documents that api.ro-intel.xyz's edge runs Cloudflare internally and
     can challenge headless-looking requests — the exact reason the GitHub
     Actions heartbeat (.github/workflows/heartbeat.yml) sends a browser
     User-Agent. Testing the onrender.com host silently skips that whole
     layer, which is precisely where a real incident (a stricter challenge
     policy, a misconfigured custom domain) would show up first.

  2. The two "expects 401" checks — GET /api/v1/me/feed and GET
     /api/v1/me — asserted `status_code == 200`. Both routes are behind
     `Depends(require_auth)` (security.py) specifically so an
     unauthenticated caller is REJECTED; a 200 there would mean the auth
     gate is bypassed. The check's own name said "expects 401" while its
     condition demanded 200 — inverted, so a genuine auth-bypass incident
     would have shown as the green PASS row, and the correctly-secured
     everyday case would have shown red.

  3. `if __name__ == "__main__": run_suite()` never inspected its own
     results and always exited 0, printed table included. A script meant
     to gate CI or feed an uptime monitor that cannot fail is not a health
     check — it is a dashboard nobody is required to look at.

It also depended on `rich` and `psycopg2`, neither declared in
requirements.txt — installed in whichever dev environment happened to have
them, not guaranteed anywhere this script might actually need to run (CI,
a fresh clone, an uptime monitor's minimal container). Rewritten against
only httpx / asyncpg / python-dotenv, all three already required by the
app itself.

Exit codes (the actual contract for automation, not the printed table):
    0 — healthy: every check passed.
    1 — degraded: the API is up and safe, but something needs attention
        (data hasn't advanced recently, a source is broken, the DB wasn't
        reachable for the optional direct check).
    2 — critical: the API is down/unreachable, the schema guard failed to
        apply required DDL, or an auth-gated route did NOT reject an
        unauthenticated request.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
load_dotenv(ROOT_DIR / ".env")

import httpx  # noqa: E402

# The real production edge, not the onrender.com fallback — see the
# module docstring. Overridable so this same script can point at a
# staging deploy or localhost during development.
API_BASE = os.getenv("RENDER_APP_URL", "https://api.ro-intel.xyz").rstrip("/")

# Matches .github/workflows/heartbeat.yml's own comment: Render's edge can
# challenge a request that looks headless (no browser fingerprint, curl's
# or httpx's default UA). Blending in avoids testing a code path real
# users never hit.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

DATABASE_URL = os.getenv("DATABASE_URL", "")

STATUS_OK, STATUS_WARN, STATUS_FAIL = "OK", "WARN", "FAIL"


class Result:
    def __init__(self, name: str, status: str, detail: str, latency_ms: float = None):
        self.name = name
        self.status = status
        self.detail = detail
        self.latency_ms = latency_ms


def _fmt_ms(v):
    return f"{v:.0f}ms" if v is not None else "-"


async def check_http(
    client: httpx.AsyncClient, name: str, method: str, path: str,
    *, expect_status: int = 200, treat_unexpected_as: str = STATUS_FAIL,
) -> Result:
    """expect_status/treat_unexpected_as let a caller assert "this MUST be
    401" (an auth gate) with the same helper used for "this SHOULD be
    200" (a normal route) — the exact distinction the previous version of
    this script got backwards for the two auth-gated checks."""
    url = f"{API_BASE}{path}"
    t0 = time.monotonic()
    try:
        resp = await client.request(method, url, headers={"User-Agent": BROWSER_UA})
        latency = (time.monotonic() - t0) * 1000
        if resp.status_code == expect_status:
            return Result(name, STATUS_OK, f"HTTP {resp.status_code}", latency)
        return Result(
            name, treat_unexpected_as,
            f"HTTP {resp.status_code} (expected {expect_status})", latency,
        )
    except httpx.HTTPError as e:
        return Result(name, STATUS_FAIL, f"{type(e).__name__}: {e}", None)


async def check_system_status(client: httpx.AsyncClient) -> list:
    results = []
    try:
        resp = await client.get(f"{API_BASE}/api/v1/system/status", headers={"User-Agent": BROWSER_UA})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [Result("System status", STATUS_FAIL, f"{type(e).__name__}: {e}")]

    db = data.get("database") or {}
    results.append(Result(
        "Database connectivity", STATUS_OK if db.get("reachable") else STATUS_FAIL,
        db.get("detail") or ("reachable" if db.get("reachable") else "unreachable"),
    ))

    guard = data.get("schema_guard") or {}
    failures = guard.get("failures") or []
    if not guard.get("ran"):
        results.append(Result("Schema guard", STATUS_WARN, guard.get("detail", "did not run")))
    elif failures:
        results.append(Result(
            "Schema guard", STATUS_FAIL,
            f"{len(failures)} DDL statement(s) failed — required columns/tables may be missing",
        ))
    else:
        results.append(Result("Schema guard", STATUS_OK, f"{guard.get('applied', 0)} statements verified"))

    results.append(Result(
        "Tick freshness (is_stale)",
        STATUS_FAIL if data.get("is_stale") else STATUS_OK,
        f"last tick {data.get('minutes_since_last_tick')} min ago" if data.get("minutes_since_last_tick") is not None else "no tick recorded",
    ))

    # data_is_stale answers "is real data actually advancing" — see
    # db.get_max_last_seen_at's docstring. Deliberately a WARN, not a
    # FAIL: a fresh, empty deploy or a long quiet stretch on a genuinely
    # slow-moving source set is not itself an outage, but it is worth a
    # human's attention if it persists.
    if "data_is_stale" in data:
        results.append(Result(
            "Data freshness (last_seen_at)",
            STATUS_WARN if data.get("data_is_stale") else STATUS_OK,
            f"newest opportunity: {data.get('data_last_seen_at') or 'none'}",
        ))
    return results


async def check_sources(client: httpx.AsyncClient) -> Result:
    try:
        resp = await client.get(f"{API_BASE}/api/v1/system/sources", headers={"User-Agent": BROWSER_UA})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return Result("Per-source health", STATUS_WARN, f"could not read: {e}")

    sources = data.get("sources") or []
    broken = [s["source_name"] for s in sources if s.get("health") == "broken"]
    undelivered = data.get("undelivered_admin_alerts") or []
    if broken:
        return Result(
            "Per-source health", STATUS_WARN,
            f"{len(broken)}/{len(sources)} broken (circuit open): {', '.join(broken[:5])}"
            + (f" +{len(broken)-5} more" if len(broken) > 5 else ""),
        )
    detail = f"{len(sources)} sources healthy"
    if undelivered:
        detail += f"; {len(undelivered)} undelivered admin alert(s) — check notifier.py's Telegram/SMTP config"
    return Result("Per-source health", STATUS_OK if not undelivered else STATUS_WARN, detail)


async def check_market_trends(client: httpx.AsyncClient) -> Result:
    t0 = time.monotonic()
    try:
        resp = await client.get(
            f"{API_BASE}/api/v1/analysis/market-trends", headers={"User-Agent": BROWSER_UA}
        )
        latency = (time.monotonic() - t0) * 1000
        resp.raise_for_status()
        data = resp.json()
        if "total_leads" not in data:
            return Result("Market trends (public)", STATUS_FAIL, "response missing total_leads", latency)
        return Result(
            "Market trends (public)", STATUS_OK,
            f"{data['total_leads']} leads, {data.get('by_county', []).__len__()} counties", latency,
        )
    except Exception as e:
        return Result("Market trends (public)", STATUS_FAIL, f"{type(e).__name__}: {e}")


async def check_database_direct() -> Result:
    """Best-effort only. An external uptime monitor won't have production
    DB credentials at all, and this script's other checks already prove
    read/write health indirectly and safely: is_stale/data_is_stale only
    advance via real INSERT/UPDATE traffic into system_ticks/opportunities,
    and schema_guard proves DDL-level writes succeed. This direct check is
    a nice-to-have for whoever runs it locally with a working
    DATABASE_URL — its absence or failure is never fatal to the overall
    verdict, since the API-level checks already cover the same ground
    without a mutating query against production."""
    if not DATABASE_URL:
        return Result("Direct DB read (optional)", STATUS_WARN, "DATABASE_URL not set — skipped")
    try:
        import asyncpg
    except ImportError:
        return Result("Direct DB read (optional)", STATUS_WARN, "asyncpg not installed — skipped")

    kwargs = {"timeout": 10}
    if ":6543" in DATABASE_URL or "pooler.supabase.com" in DATABASE_URL:
        kwargs["statement_cache_size"] = 0
    t0 = time.monotonic()
    try:
        conn = await asyncpg.connect(DATABASE_URL, **kwargs)
        try:
            users = await conn.fetchval("SELECT count(*) FROM user_profiles")
            leads = await conn.fetchval("SELECT count(*) FROM opportunities")
        finally:
            await conn.close()
        return Result(
            "Direct DB read (optional)", STATUS_OK,
            f"{users} users, {leads} opportunities", (time.monotonic() - t0) * 1000,
        )
    except Exception as e:
        return Result("Direct DB read (optional)", STATUS_WARN, f"{type(e).__name__}: {e}")


async def run_suite() -> int:
    results: list = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        results.append(await check_http(client, "Root", "GET", "/"))
        results.append(await check_http(client, "Health probe", "GET", "/health"))
        results.append(await check_market_trends(client))
        results.extend(await check_system_status(client))
        results.append(await check_sources(client))

        # Auth gate checks: MUST reject an unauthenticated caller. A 200
        # here is not a soft warning — it means any visitor can read
        # another user's feed or profile, which is the specific inversion
        # bug this script used to have.
        results.append(await check_http(
            client, "Auth gate: /api/v1/me/feed", "GET", "/api/v1/me/feed",
            expect_status=401, treat_unexpected_as=STATUS_FAIL,
        ))
        results.append(await check_http(
            client, "Auth gate: /api/v1/me", "GET", "/api/v1/me",
            expect_status=401, treat_unexpected_as=STATUS_FAIL,
        ))

    results.append(await check_database_direct())

    width = max(len(r.name) for r in results) + 2
    print(f"RO-INTEL health check — target: {API_BASE}\n")
    print(f"{'CHECK'.ljust(width)}{'STATUS':<8}{'LATENCY':<10}DETAIL")
    print("-" * (width + 60))
    for r in results:
        print(f"{r.name.ljust(width)}{r.status:<8}{_fmt_ms(r.latency_ms):<10}{r.detail}")

    fails = [r for r in results if r.status == STATUS_FAIL]
    warns = [r for r in results if r.status == STATUS_WARN]

    print()
    if fails:
        print(f"CRITICAL — {len(fails)} check(s) failed: {', '.join(r.name for r in fails)}")
        return 2
    if warns:
        print(f"DEGRADED — {len(warns)} check(s) need attention: {', '.join(r.name for r in warns)}")
        return 1
    print("HEALTHY — all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_suite()))
