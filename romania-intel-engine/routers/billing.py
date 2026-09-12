"""Stripe Checkout and the subscription webhook.

Extracted into its own router (rather than added to api.py's inline
billing routes) because it backs a real frontend surface — the pricing
modal and the /abonament landing page.

The webhook is the only route in this application that is deliberately
unauthenticated and yet trusted: Stripe calls it directly, so there is no
user session. What replaces the session is the signature check below —
`stripe.Webhook.construct_event` verifies an HMAC over the exact raw bytes
using STRIPE_WEBHOOK_SECRET. Without that secret configured the route
refuses every request rather than trusting the body, because a webhook
that accepts unsigned JSON is an endpoint that lets anyone on the internet
mark any account as paid.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import billing
import db
from billing import StripeBillingEngine
from security import require_auth

logger = logging.getLogger("BillingRouter")

router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])


class CheckoutRequest(BaseModel):
    plan_id: str
    interval: str = "monthly"


@router.get("/config")
def billing_config():
    """What the UI needs to decide between the card flow and the proforma
    flow, without hardcoding either side's availability."""
    return {
        "stripe_enabled": billing.stripe_configured(),
        "annual_months_charged": billing.ANNUAL_MONTHS_CHARGED,
        "currency": "RON",
    }


@router.post("/checkout")
async def create_checkout(payload: CheckoutRequest, user: dict = Depends(require_auth)):
    """Start a hosted-checkout session for the signed-in user.

    Reuses the profile's stripe_customer_id when one exists so renewals and
    upgrades stay on a single Stripe customer instead of creating a new one
    per purchase (which would fragment their invoice history and break the
    billing portal).
    """
    profile = await db.get_profile(user["user_id"]) or {}
    result = StripeBillingEngine.create_checkout_session(
        plan_id=payload.plan_id,
        interval=payload.interval,
        user_id=user["user_id"],
        customer_email=profile.get("email") or user.get("email"),
        stripe_customer_id=profile.get("stripe_customer_id"),
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result.get("message", "Plata a eșuat."))
    # "unavailable" is returned as 200: it is a real, expected state (no
    # Stripe key yet) that the UI renders as the proforma fallback notice,
    # not an error the user did anything to cause.
    return result


@router.get("/subscription")
async def my_subscription(user: dict = Depends(require_auth)):
    profile = await db.get_profile(user["user_id"]) or {}
    status = profile.get("subscription_status") or "inactive"
    period_end = profile.get("subscription_current_period_end")
    return {
        "status": status,
        # One derived boolean so every caller agrees on what "paid" means
        # rather than each re-deriving it from the raw Stripe vocabulary.
        "is_active": status in ("active", "trialing"),
        "plan_id": profile.get("subscription_plan_id"),
        "current_period_end": period_end.isoformat() if hasattr(period_end, "isoformat") else period_end,
    }


def _epoch_to_dt(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


async def _resolve_user_id(obj: Dict[str, Any]) -> Optional[str]:
    """Find the local user behind a Stripe object.

    Metadata first (set on both the session and the subscription at
    creation), then the customer id. The fallback matters: a subscription
    cancelled from the Stripe dashboard, or one created before metadata was
    being written, carries no user_id at all — without the lookup those
    events would be silently dropped and the account would stay marked paid
    forever.
    """
    meta = obj.get("metadata") or {}
    user_id = meta.get("user_id") or obj.get("client_reference_id")
    if user_id:
        return user_id
    customer_id = obj.get("customer")
    if isinstance(customer_id, str) and customer_id:
        return await db.get_user_id_by_stripe_customer(customer_id)
    return None


@router.post("/webhook")
async def stripe_webhook(request: Request):
    if not billing.STRIPE_WEBHOOK_SECRET:
        # Fail closed. An unsigned webhook is an unauthenticated write to
        # subscription state, so "not configured" must mean "refuse", never
        # "trust the body".
        logger.error("[Billing] Webhook called but STRIPE_WEBHOOK_SECRET is not set — refusing.")
        raise HTTPException(status_code=503, detail="Webhook-ul nu este configurat.")

    try:
        import stripe
    except ImportError:
        raise HTTPException(status_code=503, detail="Modulul de plată nu este disponibil.")

    # The RAW body, not the parsed JSON: the signature is an HMAC over the
    # exact bytes Stripe sent, so re-serialising a parsed dict (different
    # key order, different separators) invalidates it.
    raw_body = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload=raw_body, sig_header=signature, secret=billing.STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        logger.warning(f"[Billing] Rejected webhook with bad signature: {e}")
        raise HTTPException(status_code=400, detail="Semnătură invalidă.")

    event_type = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    handled = await _handle_stripe_event(event_type, obj)

    # 200 even for an event type we do not act on: a non-2xx makes Stripe
    # retry with backoff for days, and "understood, nothing to do" is not a
    # failure.
    return {"received": True, "handled": handled, "type": event_type}


async def _handle_stripe_event(event_type: str, obj: Dict[str, Any]) -> bool:
    """Separated from the route so the event handling can be tested without
    forging a valid Stripe signature."""
    if event_type == "checkout.session.completed":
        user_id = await _resolve_user_id(obj)
        if not user_id:
            logger.error("[Billing] checkout.session.completed with no resolvable user.")
            return False
        meta = obj.get("metadata") or {}
        await db.update_subscription_state(
            user_id=user_id,
            status="active",
            subscription_id=obj.get("subscription") if isinstance(obj.get("subscription"), str) else None,
            plan_id=meta.get("plan_id"),
            customer_id=obj.get("customer") if isinstance(obj.get("customer"), str) else None,
        )
        logger.info(f"[Billing] Subscription activated for user {user_id}.")
        return True

    if event_type in ("customer.subscription.updated", "customer.subscription.created"):
        user_id = await _resolve_user_id(obj)
        if not user_id:
            return False
        meta = obj.get("metadata") or {}
        await db.update_subscription_state(
            user_id=user_id,
            # Stripe's own vocabulary, stored verbatim: 'past_due' and
            # 'unpaid' are meaningfully different from 'canceled' and
            # collapsing them here would lose that.
            status=obj.get("status") or "active",
            subscription_id=obj.get("id"),
            plan_id=meta.get("plan_id"),
            current_period_end=_epoch_to_dt(obj.get("current_period_end")),
            customer_id=obj.get("customer") if isinstance(obj.get("customer"), str) else None,
        )
        return True

    if event_type == "customer.subscription.deleted":
        user_id = await _resolve_user_id(obj)
        if not user_id:
            logger.error("[Billing] customer.subscription.deleted with no resolvable user.")
            return False
        await db.update_subscription_state(
            user_id=user_id,
            status="canceled",
            subscription_id=obj.get("id"),
            current_period_end=_epoch_to_dt(obj.get("current_period_end")),
        )
        logger.info(f"[Billing] Subscription cancelled for user {user_id}.")
        return True

    return False
