"""Web Push (VAPID) dispatch for newly-ingested opportunities.

Zero recurring cost by construction: Web Push is delivered by the browser
vendors' own push services (FCM for Chrome/Edge, Mozilla autopush, Apple's
for Safari/iOS), which are free and need no account. VAPID is the
self-signed identity that authorises this server to post to them — a key
pair generated once with `openssl` (see the README block at the bottom of
this file), never a third-party service.

Two rules decide who gets notified about a new signal, and they answer
different questions:

  criteria — the tender matched the user's own declared filters (domain,
      counties, keywords) and cleared their own min_alert_score. This is
      the alert they asked for.

  radar — the tender did NOT match their filters, but scored at least
      PUSH_RADAR_MIN_SCORE on its own merits. A 9.5/10 national
      infrastructure programme is worth surfacing to a bidder whose saved
      filters happen to say "Cluj, health" — the filters describe where
      they usually look, not the ceiling of what they would bid on.

The radar is deliberately separable (user_profiles.push_radar_enabled) and
deliberately respects hard exclusions: a user who excluded a keyword is
telling us they do not want it at any score, and overriding that would be
the product deciding it knows better.
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("PushNotifications")

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "cloudpxlsupport@gmail.com")

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://ro-intel.xyz")

# The score at or above which an opportunity is pushed to a user whose own
# filters it does NOT match. High on purpose: this is an interruption the
# user did not ask for, so it has to clear a bar their own criteria do not.
# ai_refinery scores on evidence and rarely reaches 9 — which is the point.
PUSH_RADAR_MIN_SCORE = float(os.getenv("PUSH_RADAR_MIN_SCORE", "9.0"))

# Per-send timeout. A push service that hangs must not hold the ingestion
# tick, which has its own deadline to meet.
PUSH_TIMEOUT_SECONDS = float(os.getenv("PUSH_TIMEOUT_SECONDS", "10"))


def is_configured() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def _vapid_private_key() -> str:
    """The private key in the one form py_vapid actually accepts.

    py_vapid takes either a *path* to a PEM file or the raw 32-byte private
    scalar as base64url — it does NOT accept the contents of a PEM as a
    string, which is the obvious thing to paste into a Render env var and
    exactly what the openssl recipe below produces. Doing so fails at send
    time with "Could not deserialize key data", nowhere near the
    configuration that caused it, and only for real pushes — every unit
    test still passes.

    So a PEM is detected and converted here. Both forms work, and the
    operator can paste whichever they have.
    """
    raw = (VAPID_PRIVATE_KEY or "").strip()
    if "BEGIN" not in raw:
        return raw  # already base64url
    try:
        import base64

        from cryptography.hazmat.primitives import serialization

        key = serialization.load_pem_private_key(raw.encode(), password=None)
        scalar = key.private_numbers().private_value.to_bytes(32, "big")
        return base64.urlsafe_b64encode(scalar).decode().rstrip("=")
    except Exception as e:
        logger.error(f"[Push] VAPID_PRIVATE_KEY is not a usable EC private key: {e}")
        return ""


def decide_push(
    lead: Dict[str, Any],
    profile: Dict[str, Any],
    match: Dict[str, Any],
    radar_min_score: float = PUSH_RADAR_MIN_SCORE,
) -> Optional[str]:
    """'criteria', 'radar', or None — the whole notification policy.

    Pure and side-effect free so the policy can be tested exhaustively
    without a database, a push service or a tick. Every caller must treat
    None as "do not send".
    """
    if profile.get("push_enabled") is False:
        return None

    # A hard exclusion outranks both rules. matching_engine.evaluate
    # returns is_match False with an "Exclus prin:" reason for these, which
    # is indistinguishable from an ordinary non-match at this layer — so the
    # exclusion list is re-read here rather than inferred from the score.
    if _is_excluded(lead, profile):
        return None

    if match.get("is_match"):
        min_score = profile.get("min_alert_score")
        if min_score is None:
            min_score = 7.5
        try:
            if float(match.get("score") or 0) >= float(min_score):
                return "criteria"
        except (TypeError, ValueError):
            return None
        # Matched the filters but under the user's own alert threshold —
        # their setting, respected. Deliberately does not fall through to
        # the radar: a low-scoring match is not a high-yield outlier.
        return None

    if profile.get("push_radar_enabled") is False:
        return None
    try:
        score = float(lead.get("opportunity_score") or 0)
    except (TypeError, ValueError):
        return None
    if score >= radar_min_score:
        return "radar"
    return None


def _is_excluded(lead: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    excludes = profile.get("exclude_keywords") or []
    if not excludes:
        return False
    from text_utils import matching_terms

    text = " ".join(str(lead.get(f) or "") for f in
                    ("project_title", "executive_summary", "sub_category", "entity_name"))
    return bool(matching_terms(text, excludes))


def build_payload(lead: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """What the service worker receives. Kept small on purpose — several
    push services cap the encrypted payload around 4KB, and the worker only
    needs enough to render a notification and route the click."""
    title = (lead.get("project_title") or "Oportunitate nouă").strip()
    county = (lead.get("county") or "").strip()
    entity = (lead.get("entity_name") or "").strip()
    source_id = (lead.get("source_id") or "").strip()

    from notifier import _format_ron

    budget = _format_ron(lead.get("financial_value_ron") or lead.get("estimated_value_ron"))
    deadline = (lead.get("action_deadline") or "").strip()

    body_bits = [b for b in (entity, county) if b]
    detail = " • ".join(body_bits)
    money = f"Valoare: {budget}"
    if deadline:
        money += f" • Termen: {deadline}"

    return {
        # Radar sends are labelled in the title itself: an interruption the
        # user did not ask for has to explain itself on the lock screen,
        # where there is no room for anything else to.
        "title": ("Radar de piață: scor ridicat" if reason == "radar" else "Oportunitate nouă"),
        "body": f"{title[:110]}\n{detail}\n{money}".strip(),
        "url": (f"/cautare-avansata?openLead={source_id}" if source_id else "/cautare-avansata"),
        "tag": f"ro-intel-{source_id}" if source_id else "ro-intel",
        "reason": reason,
    }


async def send_to_subscription(subscription: Dict[str, Any], payload: Dict[str, Any]) -> Tuple[bool, bool]:
    """Deliver to one device. Returns (delivered, should_prune).

    should_prune is True only for 404/410 — the push service stating the
    subscription no longer exists (user revoked permission, cleared site
    data, or the browser profile is gone). Every other failure is
    transient-until-proven-otherwise and leaves the row in place.

    Never raises: this runs inside the ingestion tick, where one dead phone
    must not abort the remaining signals.
    """
    if not is_configured():
        return False, False
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.error("[Push] pywebpush is not installed — push disabled.")
        return False, False

    def _send() -> Tuple[bool, bool]:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription["endpoint"],
                    "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
                },
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=_vapid_private_key(),
                # The `sub` claim must be a mailto: or https: URI per RFC
                # 8292; a bare address is rejected by some push services.
                vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
                timeout=PUSH_TIMEOUT_SECONDS,
            )
            return True, False
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                logger.info(f"[Push] Subscription gone ({status}); pruning endpoint.")
                return False, True
            logger.warning(f"[Push] Delivery failed (status={status}): {str(e)[:160]}")
            return False, False
        except Exception as e:
            logger.warning(f"[Push] Delivery error: {str(e)[:160]}")
            return False, False

    # pywebpush is synchronous (requests under the hood), so it goes to a
    # thread rather than blocking the tick's event loop.
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_send), timeout=PUSH_TIMEOUT_SECONDS + 5
        )
    except asyncio.TimeoutError:
        logger.warning("[Push] Delivery timed out.")
        return False, False


async def dispatch_to_user(
    user_id: str,
    subscriptions: List[Dict[str, Any]],
    lead: Dict[str, Any],
    reason: str,
) -> int:
    """Fan one notification out to all of a user's devices. Returns the
    number delivered. Prunes endpoints the push service reports as gone."""
    if not subscriptions or not is_configured():
        return 0
    import db

    payload = build_payload(lead, reason)
    delivered = 0
    for sub in subscriptions:
        ok, prune = await send_to_subscription(sub, payload)
        if ok:
            delivered += 1
            await db.record_push_success(sub["endpoint"])
        elif prune:
            await db.delete_push_subscription(sub["endpoint"])
        else:
            await db.record_push_failure(sub["endpoint"])
    return delivered


# ---------------------------------------------------------------------------
# Generating the VAPID key pair (once, by the operator):
#
#   openssl ecparam -name prime256v1 -genkey -noout -out vapid_private.pem
#   openssl ec -in vapid_private.pem -pubout -out vapid_public.pem
#
#   VAPID_PRIVATE_KEY:  EITHER the whole PEM (multi-line, as Render's env
#                       editor accepts) or the raw scalar as base64url —
#                       _vapid_private_key() above converts the PEM form,
#                       because py_vapid itself rejects it. The raw form is:
#     openssl ec -in vapid_private.pem -outform DER \
#       | tail -c 32 | base64 | tr '/+' '_-' | tr -d '=\n'
#   VAPID_PUBLIC_KEY:   the base64url, uncompressed public point, which the
#                       browser needs as applicationServerKey:
#     openssl ec -in vapid_private.pem -pubout -outform DER \
#       | tail -c 65 | base64 | tr '/+' '_-' | tr -d '=\n'
#
# The public key is served to the frontend by
# GET /api/v1/notifications/push/public-key, so it lives in exactly one
# place and a rotation does not need a frontend redeploy.
# ---------------------------------------------------------------------------
