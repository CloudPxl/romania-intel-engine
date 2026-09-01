"""/api/v1/auth/sync must survive one person holding several auth identities.

This reproduces a real total outage. `upsert_user_profile_email` ran a bare
`INSERT ... ON CONFLICT (id)`, which handles only an id collision. One human
can hold several Supabase auth identities for one email — Google vs magic
link can mint different auth.users rows, and re-signup after a deletion
mints another — so a returning person arrived with an unseen id while their
email was already on a row. The insert sailed past the id handler and hit
the live `user_profiles_email_key` unique index (a constraint no schema file
in this repo declares). Every login 500'd, the browser could not decode it,
and users got an infinite sign-in loop.

The fix treats the Supabase-verified email as the identity and re-points the
existing row onto the current auth id, preserving their tenant.
"""
import asyncpg
import pytest

import db


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSyncConnection:
    """Models the live table, including the unique(email) index that caused
    the outage — an insert of a second row for a known email RAISES here,
    exactly as production did."""

    def __init__(self, rows=None, enforce_unique_email=True):
        # rows: list of dicts with id/email/tenant_id/role
        self.rows = rows or []
        self.enforce_unique_email = enforce_unique_email
        self.executed = []

    def transaction(self):
        return _FakeTransaction()

    async def execute(self, query, *args):
        self.executed.append(query)
        if "pg_advisory_xact_lock" in query:
            return "SELECT 1"
        if query.strip().startswith("UPDATE user_profiles SET id"):
            new_id, email, old_id = args
            for row in self.rows:
                if row["id"] == old_id:
                    row["id"], row["email"] = new_id, email
            return "UPDATE 1"
        if query.strip().startswith("UPDATE user_profiles SET email"):
            email, user_id = args
            for row in self.rows:
                if row["id"] == user_id:
                    row["email"] = email
            return "UPDATE 1"
        return "OK"

    async def fetchrow(self, query, *args):
        if "WHERE id = $1" in query:
            return next((r for r in self.rows if r["id"] == args[0]), None)
        if "lower(email) = lower($1)" in query:
            matches = [r for r in self.rows if r["email"].lower() == args[0].lower()]
            matches.sort(key=lambda r: r["tenant_id"] is None)
            return matches[0] if matches else None
        if query.strip().startswith("INSERT INTO user_profiles"):
            user_id, email = args
            if self.enforce_unique_email and any(r["email"].lower() == email.lower() for r in self.rows):
                raise asyncpg.exceptions.UniqueViolationError(
                    'duplicate key value violates unique constraint "user_profiles_email_key"'
                )
            row = {"id": user_id, "email": email, "tenant_id": None, "role": None}
            self.rows.append(row)
            return row
        return None


def _with_connection(conn):
    class _Ctx:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *exc):
            return False

    return lambda: _Ctx()


@pytest.mark.asyncio
async def test_returning_user_same_identity(monkeypatch):
    conn = _FakeSyncConnection([
        {"id": "uid-1", "email": "ion@test.ro", "tenant_id": "u_abc", "role": "owner"}
    ])
    monkeypatch.setattr(db, "with_connection", _with_connection(conn))

    result = await db.upsert_user_profile_email("uid-1", "ion@test.ro")

    assert result["tenant_id"] == "u_abc"
    assert len(conn.rows) == 1


@pytest.mark.asyncio
async def test_second_auth_identity_for_same_email_does_not_crash(monkeypatch):
    """THE OUTAGE. Same person, new Supabase auth id, email already on a row."""
    conn = _FakeSyncConnection([
        {"id": "old-uid", "email": "davidrosu72@gmail.com", "tenant_id": "u_abc", "role": "owner"}
    ])
    monkeypatch.setattr(db, "with_connection", _with_connection(conn))

    result = await db.upsert_user_profile_email("new-uid", "davidrosu72@gmail.com")

    # Must not raise, and must return the tenant so the user goes straight
    # back into their account rather than being asked to onboard again.
    assert result["id"] == "new-uid"
    assert result["tenant_id"] == "u_abc"
    # Re-pointed, not duplicated — one row per verified email.
    assert len(conn.rows) == 1
    assert conn.rows[0]["id"] == "new-uid"


@pytest.mark.asyncio
async def test_email_match_is_case_insensitive(monkeypatch):
    conn = _FakeSyncConnection([
        {"id": "old-uid", "email": "Ion@Test.ro", "tenant_id": "u_xyz", "role": "owner"}
    ])
    monkeypatch.setattr(db, "with_connection", _with_connection(conn))

    result = await db.upsert_user_profile_email("new-uid", "ion@test.ro")

    assert result["tenant_id"] == "u_xyz"
    assert len(conn.rows) == 1


@pytest.mark.asyncio
async def test_provisioned_row_wins_over_empty_one(monkeypatch):
    """A stale profile with no tenant must not shadow the real one."""
    conn = _FakeSyncConnection([
        {"id": "empty-uid", "email": "ion@test.ro", "tenant_id": None, "role": None},
        {"id": "real-uid", "email": "ion@test.ro", "tenant_id": "u_real", "role": "owner"},
    ])
    monkeypatch.setattr(db, "with_connection", _with_connection(conn))

    result = await db.upsert_user_profile_email("new-uid", "ion@test.ro")

    assert result["tenant_id"] == "u_real"


@pytest.mark.asyncio
async def test_brand_new_person_gets_a_row_with_no_tenant(monkeypatch):
    conn = _FakeSyncConnection([])
    monkeypatch.setattr(db, "with_connection", _with_connection(conn))

    result = await db.upsert_user_profile_email("fresh-uid", "nou@test.ro")

    # tenant_id None is what drives the frontend's onboarding form.
    assert result["tenant_id"] is None
    assert len(conn.rows) == 1


@pytest.mark.asyncio
async def test_no_database_degrades_to_none(monkeypatch):
    monkeypatch.setattr(db, "with_connection", _with_connection(None))
    assert await db.upsert_user_profile_email("uid", "a@b.ro") is None
