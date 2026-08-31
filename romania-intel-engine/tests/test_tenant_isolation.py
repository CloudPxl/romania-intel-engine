"""Tests for the real tenant-membership check (security.py) and the
Postgres-backed tenant config loader (matching_engine.py/db.py) added to
close the "any authenticated user can address any tenant_id" gap —
security.py's own verify_tenant_authorization docstring named this
limitation explicitly before this fix.

Run with `pytest` from romania-intel-engine/ (no DATABASE_URL needed —
persistence degrades to a no-op the same way it does in production).
"""

import pytest
from fastapi import HTTPException

import db
import matching_engine
from security import require_tenant_membership

FAKE_USER = {"user_id": "11111111-1111-1111-1111-111111111111", "email": "test@example.com", "role": "authenticated"}

# Snapshotted once at import time (before any test mutates the module-level
# dict) so tests that overwrite it can restore it for every other test in
# the suite that assumes the real fallback tenants exist.
_ORIGINAL_TENANT_ORGANIZATIONS = dict(matching_engine.TENANT_ORGANIZATIONS)


class TestRequireTenantMembership:
    @pytest.mark.asyncio
    async def test_allows_when_database_unconfigured(self, monkeypatch):
        # No DATABASE_URL in the test env -> dev-fallback path: trust the
        # path param, same as every route's behaviour before this fix.
        monkeypatch.setattr(db, "DATABASE_URL", "")
        result = await require_tenant_membership("t1_infra_transilvania", FAKE_USER)
        assert result == FAKE_USER

    @pytest.mark.asyncio
    async def test_allows_when_profile_matches_tenant(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://fake/db")

        async def fake_get_profile(user_id):
            return {"id": user_id, "email": FAKE_USER["email"], "tenant_id": "t1_infra_transilvania", "role": "owner"}

        monkeypatch.setattr(db, "get_user_profile", fake_get_profile)
        result = await require_tenant_membership("t1_infra_transilvania", FAKE_USER)
        assert result == FAKE_USER

    @pytest.mark.asyncio
    async def test_denies_when_profile_belongs_to_another_tenant(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://fake/db")

        async def fake_get_profile(user_id):
            return {"id": user_id, "email": FAKE_USER["email"], "tenant_id": "t2_medtech_bucuresti", "role": "owner"}

        monkeypatch.setattr(db, "get_user_profile", fake_get_profile)
        with pytest.raises(HTTPException) as exc_info:
            await require_tenant_membership("t1_infra_transilvania", FAKE_USER)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_denies_when_user_has_no_profile_row(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://fake/db")

        async def fake_get_profile(user_id):
            return None

        monkeypatch.setattr(db, "get_user_profile", fake_get_profile)
        with pytest.raises(HTTPException) as exc_info:
            await require_tenant_membership("t1_infra_transilvania", FAKE_USER)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_denies_when_profile_not_yet_provisioned_to_any_tenant(self, monkeypatch):
        # A user who has signed in (so has a user_profiles row) but hasn't
        # been run through scripts/provision_tenant.py yet — tenant_id is
        # NULL, not defaulted to any real tenant.
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://fake/db")

        async def fake_get_profile(user_id):
            return {"id": user_id, "email": FAKE_USER["email"], "tenant_id": None, "role": None}

        monkeypatch.setattr(db, "get_user_profile", fake_get_profile)
        with pytest.raises(HTTPException) as exc_info:
            await require_tenant_membership("t1_infra_transilvania", FAKE_USER)
        assert exc_info.value.status_code == 403


class TestRefreshTenantOrganizations:
    @pytest.mark.asyncio
    async def test_keeps_hardcoded_fallback_when_postgres_unavailable(self, monkeypatch):
        async def fake_get_tenant_organizations():
            return None

        monkeypatch.setattr(db, "get_tenant_organizations", fake_get_tenant_organizations)
        before = dict(matching_engine.TENANT_ORGANIZATIONS)
        refreshed = await matching_engine.refresh_tenant_organizations()
        assert refreshed is False
        assert matching_engine.TENANT_ORGANIZATIONS == before

    @pytest.mark.asyncio
    async def test_mutates_dict_in_place_not_by_reassignment(self, monkeypatch):
        # The identity check is the point: api.py imports TENANT_ORGANIZATIONS
        # by reference at module load time. If this function ever rebinds
        # the module-level name to a new dict object instead of mutating
        # the existing one, api.py's copy of the reference silently stops
        # seeing updates — this test exists specifically to catch that
        # regression, not just to check the resulting content.
        original_object_id = id(matching_engine.TENANT_ORGANIZATIONS)
        fake_data = {
            "t99_test_tenant": {
                "name": "Test Tenant SRL", "primary_domain": "infrastructura",
                "alert_emails": [], "telegram_chat_id": None, "min_alert_score": 7.5,
                "products": [],
            }
        }

        async def fake_get_tenant_organizations():
            return fake_data

        monkeypatch.setattr(db, "get_tenant_organizations", fake_get_tenant_organizations)
        try:
            refreshed = await matching_engine.refresh_tenant_organizations()
            assert refreshed is True
            assert id(matching_engine.TENANT_ORGANIZATIONS) == original_object_id
            assert matching_engine.TENANT_ORGANIZATIONS == fake_data
        finally:
            # Restore the real fallback tenants for every other test in the
            # suite (matching_engine.py, workflow tests, etc. assume they exist).
            matching_engine.TENANT_ORGANIZATIONS.clear()
            matching_engine.TENANT_ORGANIZATIONS.update(_ORIGINAL_TENANT_ORGANIZATIONS)
