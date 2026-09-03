"""/api/v1/auth/sync must survive one person holding several auth identities.

This reproduces a real total outage. `upsert_user_profile_email` ran a bare
`INSERT ... ON CONFLICT (id)`, which handles only an id collision. One human
can hold several Supabase auth identities for one email — Google vs magic
link can mint different auth.users rows, and re-signup after a deletion
mints another — so a returning person arrived with an unseen id while their
email was already on a row. The insert sailed past the id handler and hit
the `user_profiles_email_key` unique index. Every login 500'd, the browser
could not decode it, and users got an infinite sign-in loop.

The fix treats the Supabase-verified email as the identity and re-points the
existing row onto the current auth id, so the person keeps their criteria
and their saved deals instead of being sent back through onboarding.

This survived the removal of multi-tenancy unchanged in substance: only the
column it preserves changed (tenant_id -> onboarded_at and the criteria on
the row itself). The re-pointing itself is exactly as load-bearing as before.
"""
import asyncpg
import pytest

import db


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _profile(user_id, email, onboarded_at=None):
    """A row shaped like user_profiles, minimally."""
    return {
        "id": user_id,
        "email": email,
        "display_name": None,
        "domain": None,
        "target_counties": [],
        "keywords": [],
        "exclude_keywords": [],
        "min_value_ron": 0,
        "company_name": None,
        "cui": None,
        "alert_email": None,
        "telegram_chat_id": None,
        "min_alert_score": 7.5,
        "onboarded_at": onboarded_at,
    }


class _FakeSyncConnection:
    """Models the live table, including the unique(email) index that caused
    the outage — an insert of a second row for a known email RAISES here,
    exactly as production did."""

    def __init__(self, rows=None, enforce_unique_email=True):
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
            matches.sort(key=lambda r: r["onboarded_at"] is None)
            return matches[0] if matches else None
        if query.strip().startswith("INSERT INTO user_profiles"):
            user_id, email = args
            if self.enforce_unique_email and any(r["email"].lower() == email.lower() for r in self.rows):
                raise asyncpg.exceptions.UniqueViolationError(
                    'duplicate key value violates unique constraint "user_profiles_email_key"'
                )
            row = _profile(user_id, email)
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
    conn = _FakeSyncConnection([_profile("uid-1", "ion@test.ro", "2026-01-01T00:00:00")])
    monkeypatch.setattr(db, "with_connection", _with_connection(conn))

    result = await db.upsert_user_profile_email("uid-1", "ion@test.ro")

    assert result["onboarded_at"] == "2026-01-01T00:00:00"
    assert len(conn.rows) == 1


@pytest.mark.asyncio
async def test_second_auth_identity_for_same_email_does_not_crash(monkeypatch):
    """THE OUTAGE. Same person, new Supabase auth id, email already on a row."""
    conn = _FakeSyncConnection([
        _profile("old-uid", "davidrosu72@gmail.com", "2026-01-01T00:00:00")
    ])
    monkeypatch.setattr(db, "with_connection", _with_connection(conn))

    result = await db.upsert_user_profile_email("new-uid", "davidrosu72@gmail.com")

    # Must not raise, and must return the existing profile so the user lands
    # back in their account rather than being asked to onboard again.
    assert result["id"] == "new-uid"
    assert result["onboarded_at"] == "2026-01-01T00:00:00"
    # Re-pointed, not duplicated — one row per verified email.
    assert len(conn.rows) == 1
    assert conn.rows[0]["id"] == "new-uid"


@pytest.mark.asyncio
async def test_email_match_is_case_insensitive(monkeypatch):
    conn = _FakeSyncConnection([_profile("old-uid", "Ion@Test.ro", "2026-02-02T00:00:00")])
    monkeypatch.setattr(db, "with_connection", _with_connection(conn))

    result = await db.upsert_user_profile_email("new-uid", "ion@test.ro")

    assert result["onboarded_at"] == "2026-02-02T00:00:00"
    assert len(conn.rows) == 1


@pytest.mark.asyncio
async def test_onboarded_row_wins_over_empty_one(monkeypatch):
    """A stale, never-onboarded profile must not shadow the real one."""
    conn = _FakeSyncConnection([
        _profile("empty-uid", "ion@test.ro", None),
        _profile("real-uid", "ion@test.ro", "2026-03-03T00:00:00"),
    ])
    monkeypatch.setattr(db, "with_connection", _with_connection(conn))

    result = await db.upsert_user_profile_email("new-uid", "ion@test.ro")

    assert result["onboarded_at"] == "2026-03-03T00:00:00"


@pytest.mark.asyncio
async def test_brand_new_person_gets_an_un_onboarded_row(monkeypatch):
    conn = _FakeSyncConnection([])
    monkeypatch.setattr(db, "with_connection", _with_connection(conn))

    result = await db.upsert_user_profile_email("fresh-uid", "nou@test.ro")

    # onboarded_at None is what drives the frontend's onboarding form.
    assert result["onboarded_at"] is None
    assert len(conn.rows) == 1


@pytest.mark.asyncio
async def test_no_database_degrades_to_none(monkeypatch):
    monkeypatch.setattr(db, "with_connection", _with_connection(None))
    assert await db.upsert_user_profile_email("uid", "a@b.ro") is None
