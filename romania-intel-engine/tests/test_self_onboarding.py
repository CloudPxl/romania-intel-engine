"""Tests for the self-serve onboarding path added to replace the old
"signed in but not associated with any company" dead end.

Selling to individuals rather than companies means there is no admin for a
new subscriber to email when scripts/provision_tenant.py hasn't been run
for them yet — so a signed-in user with no tenant must be able to create
one themselves. db.create_self_provisioned_tenant/update_own_tenant_product
are exercised here against a fake asyncpg connection (no real Postgres
needed, matching this repo's existing degrade-to-no-op convention); the
HTTP-layer validation in api.py is exercised through TestClient.

Run with `pytest` from romania-intel-engine/.
"""

import pytest
from fastapi.testclient import TestClient

import api
import db
import matching_engine
import security


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConnection:
    """Enough of asyncpg's Connection interface for create_self_provisioned_tenant
    and update_own_tenant_product to run against: transaction() as a no-op
    context manager, fetchrow returning a canned row, fetchval returning
    the current self-provisioned tenant count (for the cap check), execute
    recording every call it received for assertions."""

    def __init__(self, existing_tenant_id=None, self_provisioned_count=0, existing_tenant_id_for_email=None):
        self.existing_tenant_id = existing_tenant_id
        self.existing_tenant_id_for_email = existing_tenant_id_for_email
        self.self_provisioned_count = self_provisioned_count
        self.executed = []
        self.fetchval_calls = []

    def transaction(self):
        return _FakeTransaction()

    async def fetchrow(self, query, *args):
        # _attach_profile_to_tenant's re-point probe — also matches on
        # lower(email), so it has to be checked BEFORE the broader branch
        # below or it would be handed a row with no "id" key.
        if "lower(email)" in query and "id <> $2" in query:
            return None  # no other auth identity holds this email
        if "SELECT 1 FROM user_profiles WHERE id" in query:
            return {"?column?": 1}  # this identity already has its own row
        if "lower(email)" in query:
            return {"tenant_id": self.existing_tenant_id_for_email} if self.existing_tenant_id_for_email else None
        if "SELECT tenant_id FROM user_profiles" in query:
            return {"tenant_id": self.existing_tenant_id} if self.existing_tenant_id else None
        return None

    async def fetchval(self, query, *args):
        self.fetchval_calls.append((query.strip(), args))
        if "COUNT(*) FROM tenants" in query:
            return self.self_provisioned_count
        return None

    async def execute(self, query, *args):
        self.executed.append((query.strip().split()[0], args))


def _with_connection(conn):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        yield conn

    return _cm


class TestCreateSelfProvisionedTenant:
    @pytest.mark.asyncio
    async def test_no_database_returns_none(self, monkeypatch):
        monkeypatch.setattr(db, "with_connection", _with_connection(None))
        result = await db.create_self_provisioned_tenant(
            "u1", "a@b.ro", "Ana", "infrastructura", ["Cluj"], 100000.0, ["drum"], []
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_already_provisioned_user_returns_none_without_writing(self, monkeypatch):
        conn = FakeConnection(existing_tenant_id="t1_infra_transilvania")
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.create_self_provisioned_tenant(
            "u1", "a@b.ro", "Ana", "infrastructura", ["Cluj"], 100000.0, ["drum"], []
        )
        assert result is None
        assert conn.executed == []  # never attempted an insert for an already-owned account

    @pytest.mark.asyncio
    async def test_new_user_creates_tenant_product_and_membership(self, monkeypatch):
        conn = FakeConnection(existing_tenant_id=None)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.create_self_provisioned_tenant(
            "u1", "ana@test.ro", "Ana Popescu", "sanatate", ["Iasi", "Cluj"], 50000.0, ["rmn"], ["catering"]
        )
        assert result is not None
        assert result["tenant_id"].startswith("u_")
        assert result["product_id"] == f"{result['tenant_id']}_prod_main"

        kinds = [k for k, _ in conn.executed]
        assert kinds == ["INSERT", "INSERT", "INSERT"]  # tenants, tenant_products, user_profiles

        tenants_args = conn.executed[0][1]
        assert tenants_args[0] == result["tenant_id"]
        assert tenants_args[1] == "Ana Popescu"
        assert tenants_args[2] == "sanatate"
        assert tenants_args[3] == ["ana@test.ro"]

        membership_args = conn.executed[2][1]
        assert membership_args == ("u1", "ana@test.ro", result["tenant_id"])

    @pytest.mark.asyncio
    async def test_acquires_per_user_advisory_lock_before_checking_existing_tenant(self, monkeypatch):
        # Two concurrent onboarding calls for the SAME user_id (a
        # double-click submit, or a client retry) could otherwise both
        # pass the "no tenant yet" check under READ COMMITTED and both
        # create a tenant, orphaning one — pg_advisory_xact_lock serializes
        # them. This only checks the lock is actually requested, keyed by
        # this user, before the existing-tenant read; real cross-session
        # blocking behaviour needs a real Postgres instance to observe.
        conn = FakeConnection(existing_tenant_id=None)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        await db.create_self_provisioned_tenant(
            "u5", "lock@test.ro", "Lock", "infrastructura", [], 0.0, ["drum"], []
        )
        assert len(conn.fetchval_calls) >= 1
        lock_query, lock_args = conn.fetchval_calls[0]
        assert "pg_advisory_xact_lock" in lock_query
        assert lock_args == ("u5",)

    @pytest.mark.asyncio
    async def test_blank_display_name_falls_back_to_email_local_part(self, monkeypatch):
        conn = FakeConnection(existing_tenant_id=None)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        await db.create_self_provisioned_tenant(
            "u2", "vlad@test.ro", "  ", "energie", [], 0.0, ["solar"], []
        )
        tenants_args = conn.executed[0][1]
        assert tenants_args[1] == "vlad"

    @pytest.mark.asyncio
    async def test_raises_capacity_error_when_cap_reached_and_writes_nothing(self, monkeypatch):
        # Unbounded self-serve signup is O(number of tenants) load on
        # orchestrator.py:run_tick's per-signal matching loop — this cap
        # exists to stop scripted tenant-farming from degrading ingestion
        # for every tenant, not just the abuser. See MAX_SELF_PROVISIONED_TENANTS'
        # docstring in db.py.
        monkeypatch.setattr(db, "MAX_SELF_PROVISIONED_TENANTS", 3)
        conn = FakeConnection(existing_tenant_id=None, self_provisioned_count=3)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        with pytest.raises(db.TenantCapacityError):
            await db.create_self_provisioned_tenant(
                "u3", "over@test.ro", "Over", "infrastructura", [], 0.0, ["drum"], []
            )
        assert conn.executed == []  # rejected before any INSERT was attempted

    @pytest.mark.asyncio
    async def test_allows_creation_just_under_the_cap(self, monkeypatch):
        monkeypatch.setattr(db, "MAX_SELF_PROVISIONED_TENANTS", 3)
        conn = FakeConnection(existing_tenant_id=None, self_provisioned_count=2)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.create_self_provisioned_tenant(
            "u4", "under@test.ro", "Under", "infrastructura", [], 0.0, ["drum"], []
        )
        assert result is not None
        kinds = [k for k, _ in conn.executed]
        assert kinds == ["INSERT", "INSERT", "INSERT"]

    @pytest.mark.asyncio
    async def test_second_identity_same_email_links_to_existing_tenant_instead_of_creating_one(self, monkeypatch):
        # The scenario this guards: the same real person signs in via
        # Google once and a magic link another time. Whether that mints
        # one Supabase auth identity (`sub`) or two depends entirely on
        # that project's own identity-linking setting — not something this
        # code can see. If it forks, a NEW user_id shows up here with the
        # SAME email as an account that already owns a tenant. Without
        # this check, that would silently create a second, duplicate-
        # billable tenant for one customer.
        conn = FakeConnection(existing_tenant_id=None, existing_tenant_id_for_email="u_original111111")
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.create_self_provisioned_tenant(
            "u_second_identity", "same@test.ro", "Same Person", "infrastructura", [], 0.0, ["drum"], []
        )
        assert result == {
            "tenant_id": "u_original111111",
            "product_id": "u_original111111_prod_main",
            "linked_existing": True,
        }
        # Exactly one write — linking this identity's membership row to
        # the existing tenant — never a second tenants/tenant_products
        # INSERT for a "new" tenant.
        kinds = [k for k, _ in conn.executed]
        assert kinds == ["INSERT"]
        membership_args = conn.executed[0][1]
        assert membership_args == ("u_second_identity", "same@test.ro", "u_original111111")

    @pytest.mark.asyncio
    async def test_email_lookup_is_case_insensitive(self, monkeypatch):
        conn = FakeConnection(existing_tenant_id=None, existing_tenant_id_for_email="u_original222222")
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.create_self_provisioned_tenant(
            "u_second", "Same@Test.RO", "Same Person", "infrastructura", [], 0.0, ["drum"], []
        )
        assert result["linked_existing"] is True
        assert result["tenant_id"] == "u_original222222"

    @pytest.mark.asyncio
    async def test_no_email_collision_creates_a_normal_new_tenant(self, monkeypatch):
        conn = FakeConnection(existing_tenant_id=None, existing_tenant_id_for_email=None)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.create_self_provisioned_tenant(
            "u6", "genuinely-new@test.ro", "New Person", "infrastructura", [], 0.0, ["drum"], []
        )
        assert result["linked_existing"] is False
        kinds = [k for k, _ in conn.executed]
        assert kinds == ["INSERT", "INSERT", "INSERT"]


class TestUpdateOwnTenantProduct:
    @pytest.mark.asyncio
    async def test_no_database_returns_false(self, monkeypatch):
        monkeypatch.setattr(db, "with_connection", _with_connection(None))
        ok = await db.update_own_tenant_product("u_abc123", "infrastructura", ["Cluj"], 0.0, ["drum"], [])
        assert ok is False

    @pytest.mark.asyncio
    async def test_upserts_product_and_updates_primary_domain(self, monkeypatch):
        conn = FakeConnection()
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        ok = await db.update_own_tenant_product("u_abc123", "energie", ["Timis"], 20000.0, ["solar"], [])
        assert ok is True
        kinds = [k for k, _ in conn.executed]
        assert kinds == ["INSERT", "UPDATE"]
        assert conn.executed[0][1][0] == "u_abc123_prod_main"
        assert conn.executed[1][1] == ("energie", "u_abc123")


class TestOnboardingRoute:
    """HTTP-layer validation — the actual db write is exercised above."""

    @pytest.fixture(autouse=True)
    def _auth_override(self):
        api.app.dependency_overrides[security.require_auth] = lambda: {
            "user_id": "route-uid-1", "email": "ion@test.ro", "role": "Membru"
        }
        yield
        api.app.dependency_overrides.pop(security.require_auth, None)

    def test_rejects_missing_consent(self):
        # consent_accepted defaults to False — an otherwise-perfectly-valid
        # payload must still be rejected without it, and rejected for
        # THIS reason specifically (not incidentally by some other check).
        client = TestClient(api.app)
        r = client.post("/api/v1/onboarding/complete", json={"domain": "infrastructura", "keywords": ["drum"]})
        assert r.status_code == 400
        assert "Termenii" in r.json()["detail"]

    def test_rejects_invalid_domain(self):
        client = TestClient(api.app)
        r = client.post(
            "/api/v1/onboarding/complete",
            json={"domain": "nu-exista", "keywords": ["x"], "consent_accepted": True},
        )
        assert r.status_code == 400
        assert "Domeniu invalid" in r.json()["detail"]

    def test_rejects_empty_keywords(self):
        client = TestClient(api.app)
        r = client.post(
            "/api/v1/onboarding/complete",
            json={"domain": "sanatate", "keywords": [], "consent_accepted": True},
        )
        assert r.status_code == 400
        assert "cuvânt-cheie" in r.json()["detail"]

    def test_no_database_configured_is_a_clean_503_not_a_500(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "")
        client = TestClient(api.app)
        r = client.post(
            "/api/v1/onboarding/complete",
            json={
                "domain": "infrastructura", "keywords": ["drum"], "target_counties": ["Cluj"],
                "consent_accepted": True,
            },
        )
        assert r.status_code == 503


class TestOnboardingHardening:
    """Tests for the abuse/scale safeguards layered on top of the original
    self-serve flow: payload size caps (matching_terms() runs these lists
    against every ingested signal for every tenant — orchestrator.py:
    run_tick), the self-provisioned tenant cap, the route-scoped rate
    limit, and the operator notification that gives the person running
    this business visibility into new signups now that there is no admin
    approval step to surface them."""

    @pytest.fixture(autouse=True)
    def _auth_override(self):
        api.app.dependency_overrides[security.require_auth] = lambda: {
            "user_id": "route-uid-2", "email": "maria@test.ro", "role": "Membru"
        }
        yield
        api.app.dependency_overrides.pop(security.require_auth, None)

    @pytest.fixture(autouse=True)
    def _reset_onboarding_rate_limit(self):
        # ONBOARDING_RATE_LIMIT_STORE is module-level state shared across
        # every test that hits this route in the same process — without
        # resetting it, tests in this class would trip each other's
        # 429s depending on execution order.
        security.ONBOARDING_RATE_LIMIT_STORE.clear()
        yield
        security.ONBOARDING_RATE_LIMIT_STORE.clear()

    def test_rejects_oversized_keyword_list(self):
        client = TestClient(api.app)
        r = client.post(
            "/api/v1/onboarding/complete",
            json={
                "domain": "infrastructura",
                "keywords": [f"kw{i}" for i in range(api.MAX_ONBOARDING_LIST_ITEMS + 1)],
                "consent_accepted": True,
            },
        )
        assert r.status_code == 400
        assert "Prea multe valori" in r.json()["detail"]

    def test_rejects_oversized_single_keyword_string(self):
        client = TestClient(api.app)
        r = client.post(
            "/api/v1/onboarding/complete",
            json={
                "domain": "infrastructura",
                "keywords": ["x" * (api.MAX_ONBOARDING_STRING_LENGTH + 1)],
                "consent_accepted": True,
            },
        )
        assert r.status_code == 400
        assert "prea lung" in r.json()["detail"]

    def test_rejects_negative_min_value(self):
        client = TestClient(api.app)
        r = client.post(
            "/api/v1/onboarding/complete",
            json={"domain": "infrastructura", "keywords": ["drum"], "min_value_ron": -1, "consent_accepted": True},
        )
        assert r.status_code == 400
        assert "buget" in r.json()["detail"]

    def test_capacity_error_returns_503_and_alerts_operator(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://fake/db")

        async def fake_create(*args, **kwargs):
            raise db.TenantCapacityError("Self-provisioned tenant cap reached (300/300).")

        monkeypatch.setattr(db, "create_self_provisioned_tenant", fake_create)

        alerts = []

        async def fake_alert(text):
            alerts.append(text)
            return True

        monkeypatch.setattr(api.LeadAlertDispatcher, "dispatch_admin_alert", fake_alert)

        client = TestClient(api.app)
        r = client.post(
            "/api/v1/onboarding/complete",
            json={"domain": "infrastructura", "keywords": ["drum"], "consent_accepted": True},
        )
        assert r.status_code == 503
        assert len(alerts) == 1
        assert "Plafonul" in alerts[0]

    def test_successful_onboarding_notifies_operator(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://fake/db")

        async def fake_create(*args, **kwargs):
            return {"tenant_id": "u_abcdef123456", "product_id": "u_abcdef123456_prod_main"}

        monkeypatch.setattr(db, "create_self_provisioned_tenant", fake_create)

        async def fake_refresh():
            return True

        monkeypatch.setattr(matching_engine, "refresh_tenant_organizations", fake_refresh)

        alerts = []

        async def fake_alert(text):
            alerts.append(text)
            return True

        monkeypatch.setattr(api.LeadAlertDispatcher, "dispatch_admin_alert", fake_alert)

        client = TestClient(api.app)
        r = client.post(
            "/api/v1/onboarding/complete",
            json={
                "domain": "infrastructura", "keywords": ["drum"], "display_name": "Maria Ionescu",
                "consent_accepted": True,
            },
        )
        assert r.status_code == 200
        assert r.json()["tenant_id"] == "u_abcdef123456"
        assert len(alerts) == 1
        assert "maria@test.ro" in alerts[0]
        assert "Maria Ionescu" in alerts[0]
        assert "u_abcdef123456" in alerts[0]

    def test_refresh_failure_does_not_turn_success_into_a_500(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://fake/db")

        async def fake_create(*args, **kwargs):
            return {"tenant_id": "u_zzz999", "product_id": "u_zzz999_prod_main"}

        monkeypatch.setattr(db, "create_self_provisioned_tenant", fake_create)

        async def fake_refresh_raises():
            raise RuntimeError("transient pool error")

        monkeypatch.setattr(matching_engine, "refresh_tenant_organizations", fake_refresh_raises)

        async def fake_alert(text):
            return True

        monkeypatch.setattr(api.LeadAlertDispatcher, "dispatch_admin_alert", fake_alert)

        client = TestClient(api.app)
        r = client.post(
            "/api/v1/onboarding/complete",
            json={"domain": "infrastructura", "keywords": ["drum"], "consent_accepted": True},
        )
        # The tenant/product/membership rows already committed inside
        # create_self_provisioned_tenant's own transaction — a refresh
        # failure after that point must not be reported back as a failed
        # signup for a user whose account is already real in Postgres.
        assert r.status_code == 200
        assert r.json()["tenant_id"] == "u_zzz999"

    def test_update_profile_route_shares_the_same_payload_caps(self, monkeypatch):
        # PUT /tenants/{id}/profile calls the same _validate_onboarding_payload
        # as the onboarding route — this just confirms the wiring, not the
        # cap logic itself (already covered above).
        api.app.dependency_overrides[security.require_tenant_membership] = lambda: {
            "user_id": "route-uid-2", "email": "maria@test.ro", "role": "owner"
        }
        try:
            client = TestClient(api.app)
            r = client.put(
                "/api/v1/tenants/u_existing123/profile",
                json={
                    "domain": "infrastructura",
                    "keywords": [f"kw{i}" for i in range(api.MAX_ONBOARDING_LIST_ITEMS + 1)],
                },
            )
            assert r.status_code == 400
            assert "Prea multe valori" in r.json()["detail"]
        finally:
            api.app.dependency_overrides.pop(security.require_tenant_membership, None)

    def test_rate_limit_blocks_after_threshold_requests(self):
        # No database configured -> every allowed call cleanly 503s past
        # the rate limiter, so this isolates the limiter itself.
        client = TestClient(api.app)
        payload = {"domain": "infrastructura", "keywords": ["drum"], "consent_accepted": True}
        for _ in range(security.ONBOARDING_RATE_LIMIT_REQUESTS):
            r = client.post("/api/v1/onboarding/complete", json=payload)
            assert r.status_code == 503
        r = client.post("/api/v1/onboarding/complete", json=payload)
        assert r.status_code == 429


class TestUpdateTenantAlertSettings:
    @pytest.mark.asyncio
    async def test_no_database_returns_false(self, monkeypatch):
        monkeypatch.setattr(db, "with_connection", _with_connection(None))
        ok = await db.update_tenant_alert_settings("u_abc123", ["a@b.ro"], 8.0)
        assert ok is False

    @pytest.mark.asyncio
    async def test_updates_alert_emails_and_score(self, monkeypatch):
        conn = FakeConnection()
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        ok = await db.update_tenant_alert_settings("u_abc123", ["ion@test.ro"], 8.5)
        assert ok is True
        assert conn.executed == [("UPDATE", (["ion@test.ro"], 8.5, "u_abc123"))]


class TestAlertSettingsRoute:
    @pytest.fixture(autouse=True)
    def _auth_override(self):
        api.app.dependency_overrides[security.require_auth] = lambda: {
            "user_id": "route-uid-2", "email": "ion@test.ro", "role": "Membru"
        }
        yield
        api.app.dependency_overrides.pop(security.require_auth, None)

    def test_rejects_out_of_range_score(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "")  # dev fallback -> require_tenant_membership trusts path param
        client = TestClient(api.app)
        r = client.put(
            "/api/v1/tenants/t1_infra_transilvania/alert-settings",
            json={"alert_email": "ion@test.ro", "min_alert_score": 15},
        )
        assert r.status_code == 400

    def test_rejects_invalid_email(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "")
        client = TestClient(api.app)
        r = client.put(
            "/api/v1/tenants/t1_infra_transilvania/alert-settings",
            json={"alert_email": "not-an-email", "min_alert_score": 8.0},
        )
        assert r.status_code == 422

    @staticmethod
    def _capture_update(monkeypatch):
        calls = {}

        async def fake_update(tenant_id, alert_emails, min_alert_score, telegram_chat_id=None):
            calls["args"] = (tenant_id, alert_emails, min_alert_score, telegram_chat_id)
            return True

        monkeypatch.setattr(db, "update_tenant_alert_settings", fake_update)
        return calls

    def test_valid_update_calls_db_layer(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "")
        calls = self._capture_update(monkeypatch)
        client = TestClient(api.app)
        r = client.put(
            "/api/v1/tenants/t1_infra_transilvania/alert-settings",
            json={"alert_email": "vlad@test.ro", "min_alert_score": 8.0},
        )
        assert r.status_code == 200
        # telegram_chat_id omitted -> None -> "leave whatever is stored".
        assert calls["args"] == ("t1_infra_transilvania", ["vlad@test.ro"], 8.0, None)

    def test_accepts_numeric_telegram_chat_id(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "")
        calls = self._capture_update(monkeypatch)
        client = TestClient(api.app)
        r = client.put(
            "/api/v1/tenants/t1_infra_transilvania/alert-settings",
            json={"alert_email": "vlad@test.ro", "min_alert_score": 8.0, "telegram_chat_id": " 123456789 "},
        )
        assert r.status_code == 200
        assert calls["args"][3] == "123456789"

    def test_accepts_negative_group_chat_id(self, monkeypatch):
        """Telegram group/channel ids are negative — must not be rejected."""
        monkeypatch.setattr(db, "DATABASE_URL", "")
        calls = self._capture_update(monkeypatch)
        client = TestClient(api.app)
        r = client.put(
            "/api/v1/tenants/t1_infra_transilvania/alert-settings",
            json={"alert_email": "vlad@test.ro", "min_alert_score": 8.0, "telegram_chat_id": "-1001234567890"},
        )
        assert r.status_code == 200
        assert calls["args"][3] == "-1001234567890"

    def test_empty_telegram_chat_id_clears_it(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "")
        calls = self._capture_update(monkeypatch)
        client = TestClient(api.app)
        r = client.put(
            "/api/v1/tenants/t1_infra_transilvania/alert-settings",
            json={"alert_email": "vlad@test.ro", "min_alert_score": 8.0, "telegram_chat_id": ""},
        )
        assert r.status_code == 200
        assert calls["args"][3] == ""

    def test_rejects_telegram_username(self, monkeypatch):
        """@username is the likeliest wrong value and the Bot API rejects
        it — fail loudly here rather than silently never alerting."""
        monkeypatch.setattr(db, "DATABASE_URL", "")
        client = TestClient(api.app)
        r = client.put(
            "/api/v1/tenants/t1_infra_transilvania/alert-settings",
            json={"alert_email": "vlad@test.ro", "min_alert_score": 8.0, "telegram_chat_id": "@ionpopescu"},
        )
        assert r.status_code == 400
        assert "numeric" in r.json()["detail"]


class _FakeDeleteConnection:
    """Enough of asyncpg's Connection interface for delete_own_account:
    a canned user_profiles row, a configurable count of OTHER profiles
    still pointing at the same tenant, and to_regclass returning whether
    the optional pipeline/alert-log tables "exist" in this scenario."""

    def __init__(self, tenant_id="u_abc123", other_profiles_on_tenant=0, optional_tables_exist=True):
        self.tenant_id = tenant_id
        self.other_profiles_on_tenant = other_profiles_on_tenant
        self.optional_tables_exist = optional_tables_exist
        self.executed = []

    def transaction(self):
        return _FakeTransaction()

    async def fetchrow(self, query, *args):
        if "SELECT tenant_id FROM user_profiles WHERE id" in query:
            if self.tenant_id is _MISSING:
                return None
            return {"tenant_id": self.tenant_id}
        return None

    async def fetchval(self, query, *args):
        if "to_regclass" in query:
            return self.optional_tables_exist
        if "COUNT(*) FROM user_profiles WHERE tenant_id" in query:
            return self.other_profiles_on_tenant
        return None

    async def execute(self, query, *args):
        self.executed.append((query.strip(), args))


_MISSING = object()


class TestDeleteOwnAccount:
    @pytest.mark.asyncio
    async def test_no_database_returns_not_deleted(self, monkeypatch):
        monkeypatch.setattr(db, "with_connection", _with_connection(None))
        result = await db.delete_own_account("u1")
        assert result == {"deleted": False, "tenant_deleted": False, "tenant_id": None}

    @pytest.mark.asyncio
    async def test_no_profile_returns_not_deleted_without_writing(self, monkeypatch):
        conn = _FakeDeleteConnection(tenant_id=_MISSING)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.delete_own_account("ghost")
        assert result == {"deleted": False, "tenant_deleted": False, "tenant_id": None}
        assert conn.executed == []

    @pytest.mark.asyncio
    async def test_sole_owner_deletes_profile_and_tenant(self, monkeypatch):
        conn = _FakeDeleteConnection(tenant_id="u_abc123", other_profiles_on_tenant=0)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.delete_own_account("u1")
        assert result == {"deleted": True, "tenant_deleted": True, "tenant_id": "u_abc123"}
        queries = [q for q, _ in conn.executed]
        assert any("DELETE FROM user_profiles" in q for q in queries)
        assert any("DELETE FROM tenant_alert_dispatch_log" in q for q in queries)
        assert any("DELETE FROM product_bidding_deals" in q for q in queries)
        assert any("DELETE FROM tenants" in q for q in queries)

    @pytest.mark.asyncio
    async def test_shared_tenant_keeps_tenant_when_another_identity_still_uses_it(self, monkeypatch):
        # The interaction with create_self_provisioned_tenant's email-merge
        # path: two user_profiles rows can legitimately point at one
        # tenant. Deleting one account must not destroy the other
        # identity's data.
        conn = _FakeDeleteConnection(tenant_id="u_shared", other_profiles_on_tenant=1)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.delete_own_account("u_second_identity")
        assert result == {"deleted": True, "tenant_deleted": False, "tenant_id": "u_shared"}
        queries = [q for q, _ in conn.executed]
        assert len(queries) == 1
        assert "DELETE FROM user_profiles" in queries[0]  # only the profile row, tenant left alone

    @pytest.mark.asyncio
    async def test_missing_optional_tables_do_not_block_deletion(self, monkeypatch):
        # pipeline_schema.sql/the alert-log table may not be applied in
        # every environment — must not fail the whole deletion over an
        # optional table that was never created.
        conn = _FakeDeleteConnection(tenant_id="u_abc123", other_profiles_on_tenant=0, optional_tables_exist=False)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        result = await db.delete_own_account("u1")
        assert result == {"deleted": True, "tenant_deleted": True, "tenant_id": "u_abc123"}
        queries = [q for q, _ in conn.executed]
        assert not any("tenant_alert_dispatch_log" in q for q in queries)
        assert not any("product_bidding_deals" in q for q in queries)
        assert any("DELETE FROM tenants" in q for q in queries)


class TestDeleteAccountRoute:
    @pytest.fixture(autouse=True)
    def _auth_override(self):
        api.app.dependency_overrides[security.require_auth] = lambda: {
            "user_id": "route-uid-3", "email": "delete-me@test.ro", "role": "Membru"
        }
        yield
        api.app.dependency_overrides.pop(security.require_auth, None)

    def test_no_account_returns_404(self, monkeypatch):
        async def fake_delete(user_id):
            return {"deleted": False, "tenant_deleted": False, "tenant_id": None}

        monkeypatch.setattr(db, "delete_own_account", fake_delete)
        client = TestClient(api.app)
        r = client.delete("/api/v1/account")
        assert r.status_code == 404

    def test_success_without_service_role_key_reports_it_honestly(self, monkeypatch):
        # No SUPABASE_SERVICE_ROLE_KEY configured is a real, supported
        # state — the app-side deletion must still succeed and say so
        # plainly rather than failing the whole request over it.
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

        async def fake_delete(user_id):
            return {"deleted": True, "tenant_deleted": True, "tenant_id": "u_abc123"}

        monkeypatch.setattr(db, "delete_own_account", fake_delete)

        async def fake_refresh():
            return True

        monkeypatch.setattr(matching_engine, "refresh_tenant_organizations", fake_refresh)

        alerts = []

        async def fake_alert(text):
            alerts.append(text)
            return True

        monkeypatch.setattr(api.LeadAlertDispatcher, "dispatch_admin_alert", fake_alert)

        client = TestClient(api.app)
        r = client.delete("/api/v1/account")
        assert r.status_code == 200
        body = r.json()
        assert body == {"status": "deleted", "auth_identity_deleted": False}
        assert len(alerts) == 1
        assert "SUPABASE_SERVICE_ROLE_KEY" in alerts[0]

    def test_success_with_service_role_key_deletes_auth_identity_too(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-service-key")

        async def fake_delete(user_id):
            return {"deleted": True, "tenant_deleted": True, "tenant_id": "u_abc123"}

        monkeypatch.setattr(db, "delete_own_account", fake_delete)

        async def fake_refresh():
            return True

        monkeypatch.setattr(matching_engine, "refresh_tenant_organizations", fake_refresh)

        async def fake_auth_delete(user_id):
            return True

        monkeypatch.setattr(api, "delete_supabase_auth_identity", fake_auth_delete)

        async def fake_alert(text):
            return True

        monkeypatch.setattr(api.LeadAlertDispatcher, "dispatch_admin_alert", fake_alert)

        client = TestClient(api.app)
        r = client.delete("/api/v1/account")
        assert r.status_code == 200
        assert r.json() == {"status": "deleted", "auth_identity_deleted": True}
