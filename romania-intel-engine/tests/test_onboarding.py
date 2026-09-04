"""Self-serve signup, profile editing, and account deletion.

There is no admin approving anything: a person signs in with Google or a
magic link, fills one form, and is live. That means the safeguards here are
the only ones there are — the payload caps (matching_terms runs these lists
against every ingested signal for every profile, once per tick), the
capacity cap, the route-scoped rate limit, and the operator notification
that is the only way the person running this business learns a new account
exists to invoice.
"""
import pytest
from fastapi.testclient import TestClient

import api
import db
import security


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


_MISSING = object()


class FakeConnection:
    """Enough of asyncpg's Connection for the profile writes: a no-op
    transaction, a configurable existing row, a configurable onboarded
    count for the cap check, and a record of everything executed."""

    def __init__(self, existing_onboarded_at=None, onboarded_count=0, row_missing=False):
        self.existing_onboarded_at = existing_onboarded_at
        self.onboarded_count = onboarded_count
        self.row_missing = row_missing
        self.executed = []
        self.fetchval_calls = []

    def transaction(self):
        return _FakeTransaction()

    async def fetchrow(self, query, *args):
        if "SELECT onboarded_at FROM user_profiles" in query:
            if self.row_missing:
                return None
            return {"onboarded_at": self.existing_onboarded_at}
        if query.strip().startswith("INSERT INTO user_profiles") or "UPDATE user_profiles SET" in query:
            self.executed.append((query, args))
            return {
                "id": "u1", "email": "ana@test.ro", "display_name": "Ana Popescu",
                "domain": "sanatate", "target_counties": ["Cluj"], "keywords": ["rmn"],
                "exclude_keywords": [], "min_value_ron": 0, "company_name": None,
                "cui": None, "alert_email": "ana@test.ro", "telegram_chat_id": None,
                "min_alert_score": 7.5, "onboarded_at": "2026-01-01T00:00:00",
            }
        return None

    async def fetchval(self, query, *args):
        self.fetchval_calls.append((query.strip(), args))
        if "COUNT(*) FROM user_profiles" in query:
            return self.onboarded_count
        return None

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "UPDATE 1"


def _with_connection(conn):
    class _Ctx:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *exc):
            return False

    return lambda: _Ctx()


class TestCompleteOnboarding:
    @pytest.mark.asyncio
    async def test_no_database_returns_none(self, monkeypatch):
        monkeypatch.setattr(db, "with_connection", _with_connection(None))
        result = await db.complete_onboarding(
            "u1", "ana@test.ro", "Ana", "sanatate", ["Cluj"], 0.0, ["rmn"], []
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_already_onboarded_returns_none(self, monkeypatch):
        conn = FakeConnection(existing_onboarded_at="2026-01-01T00:00:00")
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.complete_onboarding(
            "u1", "ana@test.ro", "Ana", "sanatate", ["Cluj"], 0.0, ["rmn"], []
        )
        # The route turns this into a 409 and points them at PUT /me/profile.
        assert result is None

    @pytest.mark.asyncio
    async def test_new_user_is_configured(self, monkeypatch):
        conn = FakeConnection(existing_onboarded_at=None)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.complete_onboarding(
            "u1", "ana@test.ro", "Ana Popescu", "sanatate", ["Cluj"], 0.0, ["rmn"], []
        )
        assert result["onboarded_at"] is not None
        assert result["domain"] == "sanatate"

    @pytest.mark.asyncio
    async def test_takes_advisory_lock_before_checking(self, monkeypatch):
        """Two concurrent submits for one user (double-click, client retry)
        could otherwise both read 'not onboarded yet' under READ COMMITTED
        and both proceed."""
        conn = FakeConnection(existing_onboarded_at=None)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        await db.complete_onboarding("u1", "ana@test.ro", None, "sanatate", [], 0.0, ["rmn"], [])
        assert any("pg_advisory_xact_lock" in q for q, _ in conn.fetchval_calls)

    @pytest.mark.asyncio
    async def test_capacity_cap_raises(self, monkeypatch):
        """The cap exists because every onboarded profile is one more
        iteration of the tick's per-signal matching loop — unbounded growth
        degrades ingestion for everyone, not just the abuser."""
        monkeypatch.setattr(db, "MAX_USER_PROFILES", 3)
        conn = FakeConnection(existing_onboarded_at=None, onboarded_count=3)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        with pytest.raises(db.UserCapacityError):
            await db.complete_onboarding("u1", "a@b.ro", None, "sanatate", [], 0.0, ["rmn"], [])

    @pytest.mark.asyncio
    async def test_under_cap_succeeds(self, monkeypatch):
        monkeypatch.setattr(db, "MAX_USER_PROFILES", 3)
        conn = FakeConnection(existing_onboarded_at=None, onboarded_count=2)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.complete_onboarding("u1", "a@b.ro", None, "sanatate", [], 0.0, ["rmn"], [])
        assert result is not None

    @pytest.mark.asyncio
    async def test_defaults_alert_score_and_leaves_telegram_null_when_omitted(self, monkeypatch):
        """Callers written before these two params existed (and any caller
        that just doesn't set alerts) must keep getting today's defaults."""
        conn = FakeConnection(existing_onboarded_at=None)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        await db.complete_onboarding("u1", "ana@test.ro", "Ana", "sanatate", ["Cluj"], 0.0, ["rmn"], [])
        _, args = conn.executed[0]
        assert args[-2:] == (7.5, None)

    @pytest.mark.asyncio
    async def test_persists_supplied_alert_settings(self, monkeypatch):
        """The whole point of folding these into onboarding: a value the
        user actually chose must reach the same columns
        PUT /api/v1/me/alert-settings writes, not silently fall back to the
        default because onboarding forgot to pass it through."""
        conn = FakeConnection(existing_onboarded_at=None)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        await db.complete_onboarding(
            "u1", "ana@test.ro", "Ana", "sanatate", ["Cluj"], 0.0, ["rmn"], [],
            9.0, "123456789",
        )
        _, args = conn.executed[0]
        assert args[-2:] == (9.0, "123456789")


class TestUpdateProfile:
    @pytest.mark.asyncio
    async def test_no_database_returns_none(self, monkeypatch):
        monkeypatch.setattr(db, "with_connection", _with_connection(None))
        assert await db.update_profile("u1", {"domain": "energie"}) is None

    @pytest.mark.asyncio
    async def test_only_sends_supplied_fields(self, monkeypatch):
        """A PUT that always wrote every column would blank out the county
        list for any client editing only its keywords."""
        conn = FakeConnection()
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        await db.update_profile("u1", {"keywords": ["drum"]})
        query = conn.executed[0][0]
        assert "keywords = $2" in query
        # Assert on the SET clause, not the whole statement — every column
        # name also appears in RETURNING.
        set_clause = query.split("SET", 1)[1].split("WHERE", 1)[0]
        assert "target_counties" not in set_clause
        assert "domain" not in set_clause

    @pytest.mark.asyncio
    async def test_ignores_unknown_fields(self, monkeypatch):
        conn = FakeConnection()
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        await db.update_profile("u1", {"onboarded_at": "hacked", "id": "someone-else"})
        # Nothing allowed was supplied, so it falls through to a plain read
        # rather than writing anything.
        assert conn.executed == []


class TestUpdateAlertSettings:
    @pytest.mark.asyncio
    async def test_no_database_returns_false(self, monkeypatch):
        monkeypatch.setattr(db, "with_connection", _with_connection(None))
        assert await db.update_alert_settings("u1", "a@b.ro", 8.0) is False

    @pytest.mark.asyncio
    async def test_omitted_telegram_leaves_stored_value_alone(self, monkeypatch):
        conn = FakeConnection()
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        await db.update_alert_settings("u1", "a@b.ro", 8.0, None)
        assert "telegram_chat_id" not in conn.executed[0][0]

    @pytest.mark.asyncio
    async def test_empty_telegram_clears_to_null(self, monkeypatch):
        """Stored as NULL, not "", so notifier's `if not chat_id` skip works
        instead of the dispatcher trying to send to an empty string."""
        conn = FakeConnection()
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        await db.update_alert_settings("u1", "a@b.ro", 8.0, "   ")
        assert conn.executed[0][1][2] is None


class TestDeleteOwnAccount:
    @pytest.mark.asyncio
    async def test_no_database_returns_false(self, monkeypatch):
        monkeypatch.setattr(db, "with_connection", _with_connection(None))
        assert await db.delete_own_account("u1") is False

    @pytest.mark.asyncio
    async def test_deletes_the_profile_row(self, monkeypatch):
        """One DELETE is enough — saved_deals and alert_dispatch_log cascade
        from the profile, so the database does the cleanup rather than a
        hand-maintained list of statements that drifts."""
        class _Conn(FakeConnection):
            async def execute(self, query, *args):
                self.executed.append((query, args))
                return "DELETE 1"

        conn = _Conn()
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        assert await db.delete_own_account("u1") is True
        assert "DELETE FROM user_profiles" in conn.executed[0][0]

    @pytest.mark.asyncio
    async def test_no_matching_row_returns_false(self, monkeypatch):
        class _Conn(FakeConnection):
            async def execute(self, query, *args):
                return "DELETE 0"

        monkeypatch.setattr(db, "with_connection", _with_connection(_Conn()))
        assert await db.delete_own_account("u1") is False


class TestOnboardingRoute:
    @pytest.fixture(autouse=True)
    def _auth_override(self):
        api.app.dependency_overrides[security.require_auth] = lambda: {
            "user_id": "route-uid", "email": "maria@test.ro", "role": "Membru"
        }
        yield
        api.app.dependency_overrides.pop(security.require_auth, None)

    @pytest.fixture(autouse=True)
    def _reset_rate_limit(self):
        # Module-level state shared by every test hitting this route in the
        # same process — without resetting, tests trip each other's 429s
        # depending on execution order.
        security.ONBOARDING_RATE_LIMIT_STORE.clear()
        yield
        security.ONBOARDING_RATE_LIMIT_STORE.clear()

    def _post(self, **overrides):
        payload = {
            "domain": "infrastructura",
            "keywords": ["drum"],
            "target_counties": ["Cluj"],
            "consent_accepted": True,
        }
        payload.update(overrides)
        return TestClient(api.app).post("/api/v1/me/onboarding", json=payload)

    def test_requires_consent(self):
        r = self._post(consent_accepted=False)
        assert r.status_code == 400
        assert "Termenii" in r.json()["detail"]

    def test_rejects_unknown_domain(self):
        r = self._post(domain="criptomonede")
        assert r.status_code == 400
        assert "Domeniu invalid" in r.json()["detail"]

    def test_rejects_empty_keywords(self):
        r = self._post(keywords=[])
        assert r.status_code == 400
        assert "cuvânt-cheie" in r.json()["detail"]

    def test_rejects_oversized_keyword_list(self):
        r = self._post(keywords=[f"kw{i}" for i in range(api.MAX_ONBOARDING_LIST_ITEMS + 1)])
        assert r.status_code == 400
        assert "Prea multe valori" in r.json()["detail"]

    def test_rejects_overlong_keyword(self):
        r = self._post(keywords=["x" * (api.MAX_ONBOARDING_STRING_LENGTH + 1)])
        assert r.status_code == 400
        assert "prea lungă" in r.json()["detail"]

    def test_rejects_negative_min_value(self):
        r = self._post(min_value_ron=-1)
        assert r.status_code == 400
        assert "bugetului" in r.json()["detail"]

    def test_rejects_out_of_range_alert_score(self):
        r = self._post(min_alert_score=15)
        assert r.status_code == 400
        assert "Pragul de alertă" in r.json()["detail"]

    def test_rejects_telegram_username_at_onboarding(self):
        """Same rule as PUT /api/v1/me/alert-settings — validated by the
        same shared helper, so this must fail identically here."""
        r = self._post(telegram_chat_id="@ionpopescu")
        assert r.status_code == 400
        assert "numeric" in r.json()["detail"]

    def test_valid_alert_settings_reach_the_db_layer(self, monkeypatch):
        """The point of folding alert settings into onboarding: a value the
        user actually chose must reach db.complete_onboarding, not get
        silently dropped on the way from the request model."""
        captured = {}

        async def fake_complete_onboarding(user_id, email, display_name, domain,
                                            target_counties, min_value_ron,
                                            keywords, exclude_keywords,
                                            min_alert_score=7.5, telegram_chat_id=None):
            captured["min_alert_score"] = min_alert_score
            captured["telegram_chat_id"] = telegram_chat_id
            return {"onboarded_at": "2026-01-01T00:00:00", "domain": domain}

        monkeypatch.setattr(db, "DATABASE_URL", "postgres://fake")
        monkeypatch.setattr(db, "complete_onboarding", fake_complete_onboarding)
        r = self._post(min_alert_score=9.0, telegram_chat_id=" 123456789 ")
        assert r.status_code == 200
        assert captured["min_alert_score"] == 9.0
        assert captured["telegram_chat_id"] == "123456789"

    def test_rate_limited_after_repeated_attempts(self):
        """The global 180/60s budget is no obstacle to a script cycling
        disposable Supabase accounts; this route needs its own."""
        last = None
        for _ in range(security.ONBOARDING_RATE_LIMIT_REQUESTS + 2):
            last = self._post(consent_accepted=False)
        assert last.status_code == 429


class TestAlertSettingsRoute:
    @pytest.fixture(autouse=True)
    def _auth_override(self):
        api.app.dependency_overrides[security.require_auth] = lambda: {
            "user_id": "route-uid-2", "email": "ion@test.ro", "role": "Membru"
        }
        yield
        api.app.dependency_overrides.pop(security.require_auth, None)

    @staticmethod
    def _capture(monkeypatch):
        calls = {}

        async def fake_update(user_id, alert_email, min_alert_score, telegram_chat_id=None):
            calls["args"] = (user_id, alert_email, min_alert_score, telegram_chat_id)
            return True

        monkeypatch.setattr(db, "update_alert_settings", fake_update)
        return calls

    def _put(self, **overrides):
        payload = {"alert_email": "ion@test.ro", "min_alert_score": 8.0}
        payload.update(overrides)
        return TestClient(api.app).put("/api/v1/me/alert-settings", json=payload)

    def test_rejects_out_of_range_score(self):
        assert self._put(min_alert_score=15).status_code == 400

    def test_rejects_invalid_email(self):
        assert self._put(alert_email="not-an-email").status_code == 422

    def test_valid_update_reaches_the_db_layer(self, monkeypatch):
        calls = self._capture(monkeypatch)
        assert self._put().status_code == 200
        assert calls["args"] == ("route-uid-2", "ion@test.ro", 8.0, None)

    def test_accepts_numeric_telegram_chat_id(self, monkeypatch):
        calls = self._capture(monkeypatch)
        assert self._put(telegram_chat_id=" 123456789 ").status_code == 200
        assert calls["args"][3] == "123456789"

    def test_accepts_negative_group_chat_id(self, monkeypatch):
        """Telegram group/channel ids are negative — must not be rejected."""
        calls = self._capture(monkeypatch)
        assert self._put(telegram_chat_id="-1001234567890").status_code == 200
        assert calls["args"][3] == "-1001234567890"

    def test_empty_telegram_chat_id_clears_it(self, monkeypatch):
        calls = self._capture(monkeypatch)
        assert self._put(telegram_chat_id="").status_code == 200
        assert calls["args"][3] == ""

    def test_rejects_telegram_username(self, monkeypatch):
        """@username is the likeliest wrong value and the Bot API rejects
        it — fail loudly here rather than silently never alerting."""
        r = self._put(telegram_chat_id="@ionpopescu")
        assert r.status_code == 400
        assert "numeric" in r.json()["detail"]
