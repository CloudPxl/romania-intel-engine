"""Web Push device registration.

Split into its own router rather than added inline to api.py because it
backs a real frontend surface (the notification toggle in Account Settings
and onboarding) — the same rule routers/eligibility.py and
routers/drafting.py were extracted under.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import db
import push_notifications
from security import require_auth

logger = logging.getLogger("NotificationsRouter")

router = APIRouter(prefix="/api/v1/notifications/push", tags=["Push Notifications"])


class PushKeys(BaseModel):
    p256dh: str = Field(..., min_length=1, max_length=256)
    auth: str = Field(..., min_length=1, max_length=256)


class PushSubscribeRequest(BaseModel):
    """Mirrors the browser's PushSubscription.toJSON() shape, so the
    frontend can post the object it already has without reshaping it."""
    endpoint: str = Field(..., min_length=1, max_length=2048)
    keys: PushKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(..., min_length=1, max_length=2048)


class PushPreferences(BaseModel):
    push_enabled: Optional[bool] = None
    push_radar_enabled: Optional[bool] = None


@router.get("/public-key")
def push_public_key():
    """The VAPID application server key the browser needs to subscribe.

    Served rather than baked into the frontend bundle so rotating the key
    pair is a backend env change, not a frontend redeploy. `configured:
    false` lets the UI hide the toggle instead of offering a button that
    cannot work.
    """
    return {
        "configured": push_notifications.is_configured(),
        "public_key": push_notifications.VAPID_PUBLIC_KEY or None,
    }


@router.post("/subscribe")
async def subscribe(payload: PushSubscribeRequest, request: Request, user: dict = Depends(require_auth)):
    ok = await db.upsert_push_subscription(
        user_id=user["user_id"],
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        # Only so the operator can tell an installed iOS PWA from desktop
        # Chrome when a device stops accepting pushes; never used to gate.
        user_agent=(request.headers.get("user-agent") or "")[:400] or None,
    )
    if not ok:
        raise HTTPException(
            status_code=503,
            detail="Notificările nu pot fi activate momentan — baza de date este indisponibilă.",
        )
    return {"status": "subscribed"}


@router.post("/unsubscribe")
async def unsubscribe(payload: PushUnsubscribeRequest, user: dict = Depends(require_auth)):
    # Scoped to the caller: without the user_id in the WHERE clause, anyone
    # holding another person's endpoint could silence their alerts. Same
    # reasoning as db.get_deal/update_deal keying on (user_id, deal_id).
    removed = await db.delete_push_subscription(payload.endpoint, user_id=user["user_id"])
    return {"status": "unsubscribed" if removed else "not_found"}


@router.get("/devices")
async def list_devices(user: dict = Depends(require_auth)):
    devices = await db.get_push_subscriptions(user["user_id"])
    return {
        "count": len(devices),
        # The endpoint is a capability URL for pushing to that browser, so
        # only a short suffix is returned — enough for the UI to tell two
        # devices apart, not enough to be replayed.
        "devices": [
            {
                "id": d["endpoint"][-12:],
                "user_agent": d.get("user_agent"),
                "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
            }
            for d in devices
        ],
    }


@router.put("/preferences")
async def update_preferences(payload: PushPreferences, user: dict = Depends(require_auth)):
    updated = await db.update_push_preferences(
        user["user_id"],
        push_enabled=payload.push_enabled,
        push_radar_enabled=payload.push_radar_enabled,
    )
    if not updated:
        raise HTTPException(
            status_code=503,
            detail="Preferințele nu au putut fi salvate — baza de date este indisponibilă.",
        )
    return {"status": "updated"}


@router.post("/test")
async def send_test_notification(user: dict = Depends(require_auth)):
    """Send a notification to this user's own devices.

    Exists because push has an unusually long list of ways to be silently
    off — OS-level Do Not Disturb, a denied browser permission, an iOS PWA
    that was never added to the home screen, a stale service worker — none
    of which the server can see. One button that either produces a
    notification or names what failed replaces guessing at all of them.
    """
    if not push_notifications.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Notificările push nu sunt configurate pe server (lipsesc cheile VAPID).",
        )
    if push_notifications.keys_are_consistent() is False:
        # Checked before attempting a send: a mismatched pair fails at the
        # push service with a bare 401/403 that names nothing, and this is
        # the one place an operator is actively looking for an answer.
        raise HTTPException(
            status_code=503,
            detail=(
                "Cheile VAPID nu se potrivesc între ele: VAPID_PUBLIC_KEY nu corespunde "
                "cheii private configurate. Regenerați perechea și actualizați ambele variabile."
            ),
        )
    subs = await db.get_push_subscriptions(user["user_id"])
    if not subs:
        raise HTTPException(
            status_code=404,
            detail="Niciun dispozitiv înregistrat. Activați notificările din acest browser mai întâi.",
        )
    delivered = await push_notifications.dispatch_to_user(
        user["user_id"],
        subs,
        {
            "project_title": "Test de notificare RO-INTEL",
            "entity_name": "Notificările sunt active",
            "county": "",
            "source_id": "",
            "financial_value_ron": 0,
        },
        reason="criteria",
    )
    return {"status": "sent" if delivered else "failed", "delivered": delivered, "devices": len(subs)}
