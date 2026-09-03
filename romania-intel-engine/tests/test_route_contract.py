"""The frontend/backend route contract.

`lib/api.ts` is the frontend's sole HTTP boundary, so every route the app
can possibly call is named in exactly one file. That makes the contract
checkable: parse the paths out of it and assert FastAPI actually declares
each one, with the same method.

This exists because the multi-tenancy refactor renamed
`DELETE /api/v1/account` to `DELETE /api/v1/me` in `lib/api.ts` and not in
`api.py`. Nothing caught it — the path `/api/v1/me` existed (as GET), the
frontend compiled, the backend booted, every test passed, and account
deletion returned 405 in production. A path-level check misses it too; the
method is the whole bug, so this compares (method, path) pairs.

Skips rather than fails when the submodule is not checked out.
"""
import json
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

import api

API_TS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "romania-intel-frontend"
    / "lib"
    / "api.ts"
)


def _call_arguments(src: str, open_paren: int) -> str:
    """Return the text between `open_paren` and its matching `)`.

    A fixed-width window after the call site is not good enough: it runs
    past the end of short functions and picks up the *next* function's
    `method:`, which reports GET routes as POST. Depth-counting stops at
    the real boundary.
    """
    depth = 0
    for i in range(open_paren, len(src)):
        c = src[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return src[open_paren + 1 : i]
    return ""


def _frontend_calls() -> set[tuple[str, str]]:
    """Every (METHOD, path) pair `lib/api.ts` can issue."""
    src = API_TS.read_text()
    calls: set[tuple[str, str]] = set()

    for m in re.finditer(r"\bapiFetch\b(?:<[^>]*>)?\s*\(", src):
        args = _call_arguments(src, m.end() - 1)

        path_match = re.match(r'\s*[`"\']([^`"\']*)', args)
        if not path_match:
            continue
        path = path_match.group(1)
        if not path.startswith("/api/"):
            continue

        method_match = re.search(r'method:\s*["\']([A-Z]+)["\']', args)
        calls.add((method_match.group(1) if method_match else "GET", path))

    return calls


def _backend_routes() -> dict[str, set[str]]:
    spec = json.loads(TestClient(api.app).get("/openapi.json").text, strict=False)
    return {
        _normalise(path): {m.upper() for m in ops}
        for path, ops in spec["paths"].items()
    }


def _strip_interpolations(path: str) -> str:
    """Collapse every `${expr}` to `{x}`, counting braces.

    `[^}]*` is not enough: `${qs({ ...filters })}` carries a nested object
    literal, so a non-greedy match stops at the inner `}` and leaves `)}`
    stuck to the path.
    """
    out = []
    i = 0
    while i < len(path):
        if path.startswith("${", i):
            depth = 0
            for j in range(i + 1, len(path)):
                if path[j] == "{":
                    depth += 1
                elif path[j] == "}":
                    depth -= 1
                    if depth == 0:
                        out.append("{x}")
                        i = j + 1
                        break
            else:  # unbalanced — leave the rest alone
                out.append(path[i:])
                break
        else:
            out.append(path[i])
            i += 1
    return "".join(out)


def _normalise(path: str) -> str:
    """Collapse interpolations and `{param}` alike to one placeholder."""
    path = _strip_interpolations(path)
    path = re.sub(r"\{[^}]*\}", "{x}", path)
    return path.split("?")[0].rstrip("/") or "/"


def _candidates(path: str) -> list[str]:
    """Paths this call could be addressing.

    A placeholder preceded by `/` is a path parameter and must stay
    (`/deals/${dealId}` -> `/deals/{x}`). One glued straight onto the end
    of a segment is an appended query string (`market-trends${qs(...)}`)
    and the route it hits is the path without it.
    """
    normalised = _normalise(path)
    out = [normalised]
    if normalised.endswith("{x}") and not normalised.endswith("/{x}"):
        out.append(normalised[: -len("{x}")].rstrip("/") or "/")
    return out


pytestmark = pytest.mark.skipif(
    not API_TS.exists(), reason="frontend submodule not checked out"
)


def test_every_frontend_call_has_a_matching_backend_route():
    backend = _backend_routes()
    calls = _frontend_calls()

    assert calls, "parsed no apiFetch calls — the parser broke, not the contract"

    missing = []
    for method, path in sorted(calls):
        served = [backend[c] for c in _candidates(path) if c in backend]
        if not served:
            missing.append(f"{method} {path} — no such route")
        elif not any(method in methods for methods in served):
            allowed = sorted({m for methods in served for m in methods})
            missing.append(f"{method} {path} — backend has {allowed}")

    assert not missing, "frontend calls routes the backend does not serve:\n  " + "\n  ".join(
        missing
    )


def test_account_deletion_is_addressed_as_me():
    """The specific regression: deletion must live under /me like every
    other user-scoped route, not at a separate /account path."""
    assert "DELETE" in _backend_routes()["/api/v1/me"]


def test_no_route_is_addressed_by_tenant():
    leaked = [p for p in _backend_routes() if "tenant" in p.lower()]
    assert not leaked, f"tenant-addressed routes survived the refactor: {leaked}"
