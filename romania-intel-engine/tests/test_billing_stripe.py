"""Stripe checkout and the subscription webhook.

Two properties carry most of the risk here and are pinned hardest: an
unconfigured Stripe must refuse rather than fabricate a checkout URL, and
an unsigned webhook must be refused rather than trusted — it is an
unauthenticated write to subscription state.
"""
import pytest

import billing
from billing import StripeBillingEngine
from routers import billing as billing_router


class TestPricing:
    def test_annual_is_priced_at_the_configured_month_count(self):
        monthly = StripeBillingEngine.price_for("plan_founder_vip", "monthly")
        annual = StripeBillingEngine.price_for("plan_founder_vip", "annual")
        assert annual == monthly * billing.ANNUAL_MONTHS_CHARGED
        assert annual < monthly * 12, "annual must be a discount, not a surcharge"


class TestUnconfiguredStripe:
    def test_returns_the_proforma_fallback_not_a_fake_url(self, monkeypatch):
        monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "")
        result = StripeBillingEngine.create_checkout_session("plan_acces_complet", "monthly")
        assert result["status"] == "unavailable"
        assert "checkout_url" not in result
        assert "proform" in result["message"].lower()

    def test_an_unknown_plan_is_rejected_before_any_api_call(self, monkeypatch):
        monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_x")
        assert StripeBillingEngine.create_checkout_session("plan_inexistent")["status"] == "error"

    def test_an_unknown_interval_is_rejected(self, monkeypatch):
        monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_x")
        assert StripeBillingEngine.create_checkout_session(
            "plan_acces_complet", "weekly")["status"] == "error"


class _FakeSession:
    url = "https://checkout.stripe.test/c/pay/cs_test_123"
    id = "cs_test_123"


def _capture_stripe(monkeypatch):
    """Intercept stripe.checkout.Session.create and record its kwargs."""
    import stripe

    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return _FakeSession()

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(_create))
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_x")
    return captured


class TestCheckoutSession:
    def test_builds_an_inline_price_when_no_price_id_is_configured(self, monkeypatch):
        """The whole point of the inline-price path: checkout works with
        nothing but a test API key, no dashboard Price objects."""
        captured = _capture_stripe(monkeypatch)
        monkeypatch.setattr(billing, "STRIPE_PRICE_IDS", {})
        out = StripeBillingEngine.create_checkout_session(
            "plan_acces_complet", "monthly", user_id="u-1", customer_email="a@b.ro")
        assert out["status"] == "success"
        assert out["checkout_url"] == _FakeSession.url
        item = captured["line_items"][0]
        assert "price" not in item
        assert item["price_data"]["recurring"]["interval"] == "month"

    def test_amounts_are_sent_in_bani_not_lei(self, monkeypatch):
        """Stripe amounts are in the currency's minor unit. Sending 499
        would charge 4,99 RON — a 100x undercharge that looks plausible."""
        captured = _capture_stripe(monkeypatch)
        monkeypatch.setattr(billing, "STRIPE_PRICE_IDS", {})
        StripeBillingEngine.create_checkout_session("plan_acces_complet", "monthly", user_id="u-1")
        expected = StripeBillingEngine.price_for("plan_acces_complet", "monthly") * 100
        assert captured["line_items"][0]["price_data"]["unit_amount"] == expected
        assert captured["line_items"][0]["price_data"]["currency"] == "ron"

    def test_annual_uses_a_yearly_recurring_interval(self, monkeypatch):
        captured = _capture_stripe(monkeypatch)
        monkeypatch.setattr(billing, "STRIPE_PRICE_IDS", {})
        StripeBillingEngine.create_checkout_session("plan_founder_vip", "annual", user_id="u-1")
        assert captured["line_items"][0]["price_data"]["recurring"]["interval"] == "year"

    def test_a_configured_price_id_wins_over_the_inline_price(self, monkeypatch):
        captured = _capture_stripe(monkeypatch)
        monkeypatch.setattr(billing, "STRIPE_PRICE_IDS",
                            {("plan_acces_complet", "monthly"): "price_live_abc"})
        StripeBillingEngine.create_checkout_session("plan_acces_complet", "monthly", user_id="u-1")
        assert captured["line_items"][0] == {"price": "price_live_abc", "quantity": 1}

    def test_the_user_is_traceable_from_both_the_session_and_the_subscription(self, monkeypatch):
        """A subscription.* event arrives without the session, so the user
        id has to be on the subscription's own metadata too."""
        captured = _capture_stripe(monkeypatch)
        monkeypatch.setattr(billing, "STRIPE_PRICE_IDS", {})
        StripeBillingEngine.create_checkout_session("plan_acces_complet", "monthly", user_id="u-42")
        assert captured["client_reference_id"] == "u-42"
        assert captured["metadata"]["user_id"] == "u-42"
        assert captured["subscription_data"]["metadata"]["user_id"] == "u-42"

    def test_an_existing_customer_is_reused_and_email_is_not_also_sent(self, monkeypatch):
        """Stripe rejects customer and customer_email together, and a new
        customer per purchase fragments invoice history."""
        captured = _capture_stripe(monkeypatch)
        monkeypatch.setattr(billing, "STRIPE_PRICE_IDS", {})
        StripeBillingEngine.create_checkout_session(
            "plan_acces_complet", "monthly", user_id="u-1",
            customer_email="a@b.ro", stripe_customer_id="cus_existing")
        assert captured["customer"] == "cus_existing"
        assert "customer_email" not in captured

    def test_an_api_error_degrades_instead_of_raising(self, monkeypatch):
        import stripe

        monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setattr(billing, "STRIPE_PRICE_IDS", {})

        def _boom(**kwargs):
            raise RuntimeError("stripe is down")

        monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(_boom))
        out = StripeBillingEngine.create_checkout_session("plan_acces_complet", "monthly")
        assert out["status"] == "error" and "checkout_url" not in out


class _RecordingDb:
    def __init__(self, user_for_customer=None):
        self.updates = []
        self._user_for_customer = user_for_customer

    async def update_subscription_state(self, **kwargs):
        self.updates.append(kwargs)
        return True

    async def get_user_id_by_stripe_customer(self, customer_id):
        return self._user_for_customer


class TestWebhookEvents:
    @pytest.mark.asyncio
    async def test_checkout_completed_activates_the_subscription(self, monkeypatch):
        fake = _RecordingDb()
        monkeypatch.setattr(billing_router, "db", fake)
        handled = await billing_router._handle_stripe_event(
            "checkout.session.completed",
            {"metadata": {"user_id": "u-1", "plan_id": "plan_founder_vip"},
             "subscription": "sub_1", "customer": "cus_1"},
        )
        assert handled is True
        assert fake.updates[0]["status"] == "active"
        assert fake.updates[0]["user_id"] == "u-1"
        assert fake.updates[0]["plan_id"] == "plan_founder_vip"

    @pytest.mark.asyncio
    async def test_subscription_deleted_marks_it_cancelled(self, monkeypatch):
        fake = _RecordingDb()
        monkeypatch.setattr(billing_router, "db", fake)
        handled = await billing_router._handle_stripe_event(
            "customer.subscription.deleted",
            {"metadata": {"user_id": "u-1"}, "id": "sub_1", "current_period_end": 1800000000},
        )
        assert handled is True
        assert fake.updates[0]["status"] == "canceled"

    @pytest.mark.asyncio
    async def test_stripes_own_status_vocabulary_is_stored_verbatim(self, monkeypatch):
        """'past_due' is not 'canceled' — collapsing them would silently
        cut off a user whose card merely needs retrying."""
        fake = _RecordingDb()
        monkeypatch.setattr(billing_router, "db", fake)
        await billing_router._handle_stripe_event(
            "customer.subscription.updated",
            {"metadata": {"user_id": "u-1"}, "id": "sub_1", "status": "past_due"},
        )
        assert fake.updates[0]["status"] == "past_due"

    @pytest.mark.asyncio
    async def test_an_event_without_metadata_resolves_via_the_customer_id(self, monkeypatch):
        """A subscription cancelled by hand in the Stripe dashboard carries
        no metadata; without this fallback the account stays marked paid."""
        fake = _RecordingDb(user_for_customer="u-99")
        monkeypatch.setattr(billing_router, "db", fake)
        handled = await billing_router._handle_stripe_event(
            "customer.subscription.deleted", {"id": "sub_1", "customer": "cus_9"})
        assert handled is True
        assert fake.updates[0]["user_id"] == "u-99"

    @pytest.mark.asyncio
    async def test_an_unresolvable_event_changes_nothing(self, monkeypatch):
        fake = _RecordingDb(user_for_customer=None)
        monkeypatch.setattr(billing_router, "db", fake)
        handled = await billing_router._handle_stripe_event(
            "customer.subscription.deleted", {"id": "sub_1"})
        assert handled is False and fake.updates == []

    @pytest.mark.asyncio
    async def test_an_unrelated_event_type_is_ignored_without_error(self, monkeypatch):
        fake = _RecordingDb()
        monkeypatch.setattr(billing_router, "db", fake)
        assert await billing_router._handle_stripe_event("invoice.created", {}) is False
        assert fake.updates == []


class TestWebhookSecurity:
    def test_an_unconfigured_secret_refuses_rather_than_trusting_the_body(self, monkeypatch):
        """Without signature verification this route is an unauthenticated
        write that lets anyone mark any account as paid."""
        from fastapi.testclient import TestClient

        import api

        monkeypatch.setattr(billing, "STRIPE_WEBHOOK_SECRET", "")
        with TestClient(api.app) as client:
            resp = client.post(
                "/api/v1/billing/webhook",
                json={"type": "checkout.session.completed",
                      "data": {"object": {"metadata": {"user_id": "attacker"}}}},
            )
        assert resp.status_code == 503

    def test_a_bad_signature_is_rejected(self, monkeypatch):
        from fastapi.testclient import TestClient

        import api

        monkeypatch.setattr(billing, "STRIPE_WEBHOOK_SECRET", "whsec_test")
        with TestClient(api.app) as client:
            resp = client.post(
                "/api/v1/billing/webhook",
                headers={"stripe-signature": "t=1,v1=deadbeef"},
                json={"type": "checkout.session.completed", "data": {"object": {}}},
            )
        assert resp.status_code == 400


def _sign(body: bytes, secret: str) -> dict:
    """A genuine Stripe signature header over these exact bytes."""
    import hashlib
    import hmac
    import time

    ts = int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"stripe-signature": f"t={ts},v1={mac}", "content-type": "application/json"}


class TestWebhookRouteWithAValidSignature:
    """The gap that let a total webhook outage ship.

    Every event test above calls _handle_stripe_event with a plain dict,
    and the two security tests above only exercise the *rejection* paths.
    Nothing ever drove a **valid** signature through the route — so nobody
    noticed that stripe-python v8+ removed the dict base class from
    StripeObject, making `event.get("type")` raise AttributeError on the
    first line after a successful verification. Signature checks passed,
    every real payment 500ed, and no test failed.

    These drive the HTTP route end to end with a real signature.
    """

    SECRET = "whsec_test_route"

    def _post(self, monkeypatch, event: dict):
        import json

        from fastapi.testclient import TestClient

        import api

        monkeypatch.setattr(billing, "STRIPE_WEBHOOK_SECRET", self.SECRET)
        body = json.dumps(event).encode()
        with TestClient(api.app) as client:
            return client.post(
                "/api/v1/billing/webhook", content=body, headers=_sign(body, self.SECRET)
            )

    def test_a_validly_signed_event_is_processed_not_500(self, monkeypatch):
        fake = _RecordingDb()
        monkeypatch.setattr(billing_router, "db", fake)
        resp = self._post(monkeypatch, {
            "id": "evt_1", "object": "event", "type": "checkout.session.completed",
            "data": {"object": {
                "id": "cs_1", "customer": "cus_1", "subscription": "sub_1",
                "metadata": {"user_id": "u-1", "plan_id": "plan_acces_complet"},
            }},
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["handled"] is True
        assert fake.updates[0]["status"] == "active"

    def test_an_event_type_we_ignore_is_acked_not_retried(self, monkeypatch):
        fake = _RecordingDb()
        monkeypatch.setattr(billing_router, "db", fake)
        resp = self._post(monkeypatch, {
            "id": "evt_2", "object": "event", "type": "invoice.created",
            "data": {"object": {"id": "in_1"}},
        })
        assert resp.status_code == 200
        assert resp.json()["handled"] is False

    def test_a_processing_failure_returns_500_so_stripe_retries(self, monkeypatch):
        """A transient database failure must not be acked with 200 — that
        drops the payment permanently. Stripe retries a non-2xx for days."""
        class _Exploding:
            async def update_subscription_state(self, **kw):
                raise RuntimeError("database is down")

            async def get_user_id_by_stripe_customer(self, cid):
                return None

        monkeypatch.setattr(billing_router, "db", _Exploding())
        resp = self._post(monkeypatch, {
            "id": "evt_3", "object": "event", "type": "checkout.session.completed",
            "data": {"object": {"metadata": {"user_id": "u-1"}}},
        })
        assert resp.status_code == 500

    def test_a_body_that_is_not_a_json_object_is_rejected(self, monkeypatch):
        resp = self._post(monkeypatch, ["not", "an", "object"])
        assert resp.status_code == 400


class TestPayloadShapeTolerance:
    @pytest.mark.asyncio
    async def test_an_expanded_subscription_object_still_yields_its_id(self, monkeypatch):
        """`subscription` is normally a bare id but becomes a full object
        as soon as anything expands it. Reading only the string form stored
        NULL and the profile never recovered the id."""
        fake = _RecordingDb()
        monkeypatch.setattr(billing_router, "db", fake)
        await billing_router._handle_stripe_event(
            "checkout.session.completed",
            {"metadata": {"user_id": "u-1"},
             "subscription": {"id": "sub_9", "object": "subscription"},
             "customer": {"id": "cus_9", "object": "customer"}},
        )
        assert fake.updates[0]["subscription_id"] == "sub_9"
        assert fake.updates[0]["customer_id"] == "cus_9"

    @pytest.mark.asyncio
    async def test_period_end_is_read_from_items_on_current_api_versions(self, monkeypatch):
        """Stripe moved current_period_end off Subscription and onto each
        subscription item in API 2025-03-31.basil. Reading only the old
        top-level field wrote NULL for every current account."""
        fake = _RecordingDb()
        monkeypatch.setattr(billing_router, "db", fake)
        await billing_router._handle_stripe_event(
            "customer.subscription.created",
            {"metadata": {"user_id": "u-1"}, "id": "sub_1", "status": "active",
             "items": {"object": "list", "data": [{"id": "si_1", "current_period_end": 1790000000}]}},
        )
        assert fake.updates[0]["current_period_end"] is not None

    @pytest.mark.asyncio
    async def test_the_legacy_top_level_period_end_still_wins_when_present(self, monkeypatch):
        fake = _RecordingDb()
        monkeypatch.setattr(billing_router, "db", fake)
        await billing_router._handle_stripe_event(
            "customer.subscription.updated",
            {"metadata": {"user_id": "u-1"}, "id": "sub_1", "current_period_end": 1800000000,
             "items": {"data": [{"current_period_end": 1790000000}]}},
        )
        assert int(fake.updates[0]["current_period_end"].timestamp()) == 1800000000

    @pytest.mark.asyncio
    async def test_a_missing_period_end_is_none_not_an_exception(self, monkeypatch):
        fake = _RecordingDb()
        monkeypatch.setattr(billing_router, "db", fake)
        await billing_router._handle_stripe_event(
            "customer.subscription.updated", {"metadata": {"user_id": "u-1"}, "id": "sub_1"})
        assert fake.updates[0]["current_period_end"] is None

    @pytest.mark.asyncio
    async def test_a_blank_user_id_falls_through_to_the_customer_lookup(self, monkeypatch):
        """create_checkout_session writes `user_id or ""`, so an anonymous
        session carries an empty string, not a missing key. Using it as an
        id would write to a profile that cannot exist."""
        fake = _RecordingDb(user_for_customer="u-77")
        monkeypatch.setattr(billing_router, "db", fake)
        await billing_router._handle_stripe_event(
            "checkout.session.completed",
            {"metadata": {"user_id": "  "}, "client_reference_id": "", "customer": "cus_7"},
        )
        assert fake.updates[0]["user_id"] == "u-77"
