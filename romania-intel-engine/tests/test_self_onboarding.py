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
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api
import db
import security


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConnection:
    """Enough of asyncpg's Connection interface for create_self_provisioned_tenant
    and update_own_tenant_product to run against: transaction() as a no-op
    context manager, fetchrow returning a canned row, execute recording
    every call it received for assertions."""

    def __init__(self, existing_tenant_id=None):
        self.existing_tenant_id = existing_tenant_id
        self.executed = []

    def transaction(self):
        return _FakeTransaction()

    async def fetchrow(self, query, *args):
        if "SELECT tenant_id FROM user_profiles" in query:
            return {"tenant_id": self.existing_tenant_id} if self.existing_tenant_id else None
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
    async def test_blank_display_name_falls_back_to_email_local_part(self, monkeypatch):
        conn = FakeConnection(existing_tenant_id=None)
        monkeypatch.setattr(db, "with_connection", _with_connection(conn))
        await db.create_self_provisioned_tenant(
            "u2", "vlad@test.ro", "  ", "energie", [], 0.0, ["solar"], []
        )
        tenants_args = conn.executed[0][1]
        assert tenants_args[1] == "vlad"


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

    def test_rejects_invalid_domain(self):
        client = TestClient(api.app)
        r = client.post("/api/v1/onboarding/complete", json={"domain": "nu-exista", "keywords": ["x"]})
        assert r.status_code == 400
        assert "Domeniu invalid" in r.json()["detail"]

    def test_rejects_empty_keywords(self):
        client = TestClient(api.app)
        r = client.post("/api/v1/onboarding/complete", json={"domain": "sanatate", "keywords": []})
        assert r.status_code == 400

    def test_no_database_configured_is_a_clean_503_not_a_500(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "")
        client = TestClient(api.app)
        r = client.post(
            "/api/v1/onboarding/complete",
            json={"domain": "infrastructura", "keywords": ["drum"], "target_counties": ["Cluj"]},
        )
        assert r.status_code == 503
