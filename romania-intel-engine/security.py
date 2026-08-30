import os
import time
import logging
from typing import Dict, Optional, Tuple

import jwt
from fastapi import Request, HTTPException

logger = logging.getLogger("SecurityGuard")

RATE_LIMIT_STORE: Dict[str, Tuple[int, float]] = {}
RATE_LIMIT_REQUESTS = 180
RATE_LIMIT_WINDOW = 60

# The rate limiter never evicted an IP once it stopped sending requests, so
# RATE_LIMIT_STORE grew by one entry per distinct client IP ever seen and
# never shrank — a slow but real OOM risk on a long-lived process. Cleanup
# runs opportunistically (inside enforce_rate_limit, not a separate
# scheduled task) but only every CLEANUP_INTERVAL_SECONDS, so it stays an
# O(n) scan every few minutes rather than every request.
CLEANUP_INTERVAL_SECONDS = 300
_last_cleanup_at = 0.0

# Supabase JWTs are signed with the project's JWT Secret (Project Settings
# -> API -> JWT Settings in the Supabase dashboard) — a distinct, private
# value, NOT the anon/publishable key. The anon key is itself a JWT (signed
# BY that secret), so it cannot also serve as the HMAC key to verify other
# tokens; a JWT's own string value never doubles as the secret used to sign
# it or its siblings. Configure the real secret as SUPABASE_JWT_SECRET.
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_JWT_AUDIENCE = "authenticated"


class SecurityGuard:
    @staticmethod
    def _cleanup_stale_ips(now: float) -> None:
        global _last_cleanup_at
        if now - _last_cleanup_at < CLEANUP_INTERVAL_SECONDS:
            return
        _last_cleanup_at = now
        stale = [ip for ip, (_, start_time) in RATE_LIMIT_STORE.items() if now - start_time >= RATE_LIMIT_WINDOW]
        for ip in stale:
            del RATE_LIMIT_STORE[ip]
        if stale:
            logger.info(f"[SecurityGuard] Purged {len(stale)} stale rate-limit entries ({len(RATE_LIMIT_STORE)} remaining).")

    @staticmethod
    def enforce_rate_limit(request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()

        SecurityGuard._cleanup_stale_ips(now)

        if client_ip in RATE_LIMIT_STORE:
            count, start_time = RATE_LIMIT_STORE[client_ip]
            if now - start_time < RATE_LIMIT_WINDOW:
                if count >= RATE_LIMIT_REQUESTS:
                    logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                    raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")
                RATE_LIMIT_STORE[client_ip] = (count + 1, start_time)
            else:
                RATE_LIMIT_STORE[client_ip] = (1, now)
        else:
            RATE_LIMIT_STORE[client_ip] = (1, now)

    @staticmethod
    def verify_tenant_authorization(request: Request) -> Dict:
        """Decodes and validates a Supabase-issued JWT from the
        Authorization header. Replaces a hardcoded stub that returned a
        fixed fake user/role for every request regardless of what (if
        anything) was actually sent — i.e. no request was ever rejected.

        Scope note — this authenticates, it does not authorize per tenant.
        It proves the caller holds a valid, unexpired Supabase session for
        *some* account; it cannot prove that account is entitled to the
        {tenant_id} in the path, because no user->tenant mapping is stored
        anywhere yet (TENANT_ORGANIZATIONS in matching_engine.py is a
        hardcoded in-process dict, and desks are per-browser localStorage).
        A logged-in user can therefore still address another tenant's id.
        Closing that gap needs a real tenant-membership table; naming the
        function `verify_tenant_authorization` does not by itself make it
        one, so the limitation is stated here rather than implied away.
        """
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Lipsește antetul Authorization: Bearer <token>.")
        token = auth_header[len("Bearer "):].strip()
        if not token:
            raise HTTPException(status_code=401, detail="Token de autentificare gol.")

        if not SUPABASE_JWT_SECRET:
            logger.error("[SecurityGuard] SUPABASE_JWT_SECRET not configured — cannot verify tokens.")
            raise HTTPException(status_code=503, detail="Autentificarea nu este configurată pe server.")

        try:
            claims = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience=SUPABASE_JWT_AUDIENCE,
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expirat. Reautentificați-vă.")
        except jwt.PyJWTError as e:
            logger.warning(f"[SecurityGuard] JWT verification failed: {e}")
            raise HTTPException(status_code=401, detail="Token de autentificare invalid.")

        user_id = claims.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token invalid — lipsește identificatorul utilizatorului.")

        user_metadata = claims.get("user_metadata") or {}
        return {
            "user_id": user_id,
            "email": claims.get("email"),
            "role": user_metadata.get("role") or claims.get("role", "authenticated"),
        }


# --- FastAPI dependencies -------------------------------------------------
#
# `Depends(require_auth)` is the form routes actually consume. Kept as
# module-level functions rather than staticmethods because FastAPI inspects
# the callable's signature to build the dependency, and a bare `Request`
# parameter is what makes it resolve without polluting the route signature.


def require_auth(request: Request) -> Dict:
    """Hard gate: a valid Supabase bearer token or the request does not
    proceed. 401 on a missing/forged/expired token, 503 if the server has
    no SUPABASE_JWT_SECRET configured (fail closed — an unconfigured
    server must not silently accept everything, which is exactly the
    behaviour the previous stub had)."""
    return SecurityGuard.verify_tenant_authorization(request)


def optional_auth(request: Request) -> Optional[Dict]:
    """Soft gate for routes that are public but behave differently for a
    signed-in caller. Returns the claims when a valid token is present and
    None otherwise — it never raises, so an anonymous visitor still gets a
    response. Used to derive entitlement server-side instead of trusting a
    client-supplied flag."""
    if not request.headers.get("Authorization", "").startswith("Bearer "):
        return None
    try:
        return SecurityGuard.verify_tenant_authorization(request)
    except HTTPException:
        return None
