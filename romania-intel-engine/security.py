import os
import time
import logging
from typing import Dict, Optional, Tuple

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError, PyJWKSetError
from fastapi import Depends, Request, HTTPException

import db

logger = logging.getLogger("SecurityGuard")

RATE_LIMIT_STORE: Dict[str, Tuple[int, float]] = {}
RATE_LIMIT_REQUESTS = 180
RATE_LIMIT_WINDOW = 60

# Self-serve onboarding (/api/v1/onboarding/complete) does a real
# transactional DB write (tenant + product + membership rows) and, on
# success, an in-process refresh of every tenant's matching config — far
# heavier than an ordinary read, and each success leaves a permanent row
# behind rather than just serving a response. The global 180-req/60s
# budget above exists to stop generic API hammering, not tenant-farming
# specifically: 180 requests/minute is no obstacle at all to a script
# cycling through disposable free Supabase accounts from one IP. This is
# a separate, much tighter budget scoped to just that one route — a
# legitimate user onboards once, so even a handful of allowed attempts
# per hour (retries after a validation error, one person setting up a
# couple of accounts) comfortably covers real usage.
ONBOARDING_RATE_LIMIT_STORE: Dict[str, Tuple[int, float]] = {}
ONBOARDING_RATE_LIMIT_REQUESTS = 5
ONBOARDING_RATE_LIMIT_WINDOW = 3600

# The rate limiter never evicted an IP once it stopped sending requests, so
# RATE_LIMIT_STORE grew by one entry per distinct client IP ever seen and
# never shrank — a slow but real OOM risk on a long-lived process. Cleanup
# runs opportunistically (inside enforce_rate_limit, not a separate
# scheduled task) but only every CLEANUP_INTERVAL_SECONDS, so it stays an
# O(n) scan every few minutes rather than every request. Covers both
# stores above — the onboarding one grows far slower, but not enforcing
# the same hygiene on it would just move the same slow OOM risk over.
CLEANUP_INTERVAL_SECONDS = 300
_last_cleanup_at = 0.0

# Supabase rolled this project onto asymmetric JWT signing keys (verified
# live against this project's own JWKS endpoint below — its two active
# keys are both ES256/EC, not RS256; the algorithm actually in use is read
# from each key itself rather than assumed, since Supabase lets a project
# pick either an EC or RSA key pair and guessing wrong reproduces exactly
# the "alg value is not allowed" failure this replaces). New sessions are
# therefore verified against Supabase's public signing keys — nothing
# secret is needed for them, so this is not a credential to protect.
#
# SUPABASE_JWT_SECRET (the legacy shared HS256 secret, from Project
# Settings -> API -> JWT Settings in the Supabase dashboard) is kept only
# as a fallback for a token minted in the short window before the project
# switched — Supabase access tokens are short-lived (default ~1h), so any
# still-valid HS256 token naturally ages out on its own; this just avoids
# forcing an immediate re-login for whoever was signed in at the moment of
# the switch. It is read from the token's own `alg` header, never assumed.
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://upzyczsfizenlogkfvsa.supabase.co").rstrip("/")
SUPABASE_JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_JWT_AUDIENCE = "authenticated"

# Built once per process, not per request: PyJWKClient caches the fetched
# keyset for `lifespan` seconds (below) and the individual keys by `kid`,
# so re-verifying a token a moment later costs no network round trip to
# Supabase. Constructing a fresh client per call would defeat that cache
# and put Supabase's JWKS endpoint on the hot path of every authenticated
# request — this mirrors db.py's lazy, module-level connection pool.
_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            SUPABASE_JWKS_URL,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=300,
        )
    return _jwks_client


class SecurityGuard:
    @staticmethod
    def _cleanup_stale_ips(now: float) -> None:
        global _last_cleanup_at
        if now - _last_cleanup_at < CLEANUP_INTERVAL_SECONDS:
            return
        _last_cleanup_at = now
        for store, window, label in (
            (RATE_LIMIT_STORE, RATE_LIMIT_WINDOW, "global"),
            (ONBOARDING_RATE_LIMIT_STORE, ONBOARDING_RATE_LIMIT_WINDOW, "onboarding"),
        ):
            stale = [ip for ip, (_, start_time) in store.items() if now - start_time >= window]
            for ip in stale:
                del store[ip]
            if stale:
                logger.info(f"[SecurityGuard] Purged {len(stale)} stale {label} rate-limit entries ({len(store)} remaining).")

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
    def enforce_onboarding_rate_limit(request: Request):
        """Tighter, route-scoped budget layered on top of the global
        limiter above — see ONBOARDING_RATE_LIMIT_REQUESTS' comment for
        why self-serve tenant creation needs its own, much stricter cap."""
        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()

        SecurityGuard._cleanup_stale_ips(now)

        if client_ip in ONBOARDING_RATE_LIMIT_STORE:
            count, start_time = ONBOARDING_RATE_LIMIT_STORE[client_ip]
            if now - start_time < ONBOARDING_RATE_LIMIT_WINDOW:
                if count >= ONBOARDING_RATE_LIMIT_REQUESTS:
                    logger.warning(f"[SecurityGuard] Onboarding rate limit exceeded for IP: {client_ip}")
                    raise HTTPException(
                        status_code=429,
                        detail="Prea multe încercări de înregistrare de pe această adresă. Reîncercați peste o oră.",
                    )
                ONBOARDING_RATE_LIMIT_STORE[client_ip] = (count + 1, start_time)
            else:
                ONBOARDING_RATE_LIMIT_STORE[client_ip] = (1, now)
        else:
            ONBOARDING_RATE_LIMIT_STORE[client_ip] = (1, now)

    @staticmethod
    def verify_tenant_authorization(request: Request) -> Dict:
        """Decodes and validates a Supabase-issued JWT from the
        Authorization header. Replaces a hardcoded stub that returned a
        fixed fake user/role for every request regardless of what (if
        anything) was actually sent — i.e. no request was ever rejected.

        Scope note — this authenticates, it does not authorize per tenant.
        It proves the caller holds a valid, unexpired Supabase session for
        *some* account; it does not by itself prove that account is
        entitled to any particular {tenant_id} in a route's path — that
        check is `require_tenant_membership` below, layered on top of this
        function via `Depends(require_auth)`, not folded into this one.
        Naming this function `verify_tenant_authorization` never made it
        one; every tenant-scoped route in api.py now depends on
        `require_tenant_membership` instead of `require_auth` directly for
        exactly this reason — see tenants_schema.sql / db.get_user_profile.
        """
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Lipsește antetul Authorization: Bearer <token>.")
        token = auth_header[len("Bearer "):].strip()
        if not token:
            raise HTTPException(status_code=401, detail="Token de autentificare gol.")

        try:
            # The header alone decides the path — it is unsigned data at
            # this point, so nothing here has been trusted yet. It only
            # picks which key material to verify the signature against;
            # jwt.decode() below still does the actual cryptographic check
            # and is what would raise on a forged or tampered token.
            unverified_alg = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError as e:
            raise HTTPException(status_code=401, detail="Token de autentificare malformat.") from e

        try:
            if unverified_alg == "HS256":
                # Legacy path — see the SUPABASE_JWT_SECRET comment above.
                if not SUPABASE_JWT_SECRET:
                    raise HTTPException(
                        status_code=401,
                        detail="Token semnat cu un algoritm expirat. Reautentificați-vă.",
                    )
                claims = jwt.decode(
                    token,
                    SUPABASE_JWT_SECRET,
                    algorithms=["HS256"],
                    audience=SUPABASE_JWT_AUDIENCE,
                )
            else:
                # Current path: verify against Supabase's own public
                # signing keys. algorithms=[signing_key.algorithm_name]
                # uses whatever algorithm that specific key actually
                # declares (this project's are ES256) instead of a
                # hardcoded guess — pinning the wrong family here is
                # exactly what reproduces "alg value is not allowed"
                # against a correctly-signed token.
                #
                # A prior direct push to main (a30451a, 88b8119) worked
                # around that same error with
                # options={"verify_signature": False, "verify_aud": False}
                # — accepting any token regardless of who signed it or
                # what it claims. That was live in production and
                # confirmed exploitable (a forged token with a fake `sub`
                # and no valid signature returned real tenant data over
                # the public API) before this replaced it. Never reduce
                # this path back to that: the fix for "wrong algorithm
                # rejected" is verifying against the *correct* key and
                # algorithm, not skipping verification.
                signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=[signing_key.algorithm_name],
                    audience=SUPABASE_JWT_AUDIENCE,
                )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expirat. Reautentificați-vă.")
        except PyJWKClientConnectionError as e:
            # Supabase's JWKS endpoint itself is unreachable — a server/
            # upstream problem, not evidence the caller's token is bad.
            logger.error(f"[SecurityGuard] Could not reach Supabase JWKS endpoint: {e}")
            raise HTTPException(status_code=503, detail="Serviciul de autentificare este temporar indisponibil.")
        except (PyJWKClientError, PyJWKSetError) as e:
            # Keyset fetched fine but no key matches this token's `kid` —
            # a forged token, one from a different Supabase project, or a
            # signing key that has since been rotated out.
            logger.warning(f"[SecurityGuard] No matching signing key for token: {e}")
            raise HTTPException(status_code=401, detail="Token de autentificare invalid.")
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
    proceed. 401 on a missing/forged/expired token or one signed by a key
    this project doesn't recognise; 503 only if Supabase's own JWKS
    endpoint is unreachable. Fails closed either way — an unconfigured or
    unreachable auth backend must not silently accept everything, which is
    exactly the behaviour the previous stub had."""
    return SecurityGuard.verify_tenant_authorization(request)


def enforce_onboarding_rate_limit(request: Request) -> None:
    """`Depends()`-compatible wrapper around
    SecurityGuard.enforce_onboarding_rate_limit, for routes that need the
    tighter self-serve-signup budget on top of the global per-IP limit
    the middleware already applies to every request."""
    SecurityGuard.enforce_onboarding_rate_limit(request)


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


async def require_tenant_membership(tenant_id: str, user: Dict = Depends(require_auth)) -> Dict:
    """The actual per-tenant authorization check `require_auth` alone never
    did (see its docstring above, and verify_tenant_authorization's).
    `tenant_id` is resolved by FastAPI from the route's own path parameter
    of the same name — every tenant-scoped route in api.py depends on this
    instead of `require_auth` directly, so this composes with it rather
    than replacing it.

    Fails CLOSED on ambiguity, deliberately unlike almost every other read
    in this codebase: an unreachable database is not "let the request
    through", because this is a tenant-isolation boundary, not a feed that
    degrades gracefully to empty. The one exception is when no database is
    configured *at all* (`db.DATABASE_URL` unset) — that's the local/dev
    case (this repo's tests and `python server.py` runs work with no
    DATABASE_URL by design), where trusting the path param reproduces
    exactly today's pre-fix behaviour rather than breaking local
    development for a check that has nothing to check against.
    """
    if not db.DATABASE_URL:
        return user

    profile = await db.get_user_profile(user["user_id"])
    if profile is None or profile.get("tenant_id") != tenant_id:
        logger.warning(
            f"[SecurityGuard] Denied {user.get('email') or user['user_id']} access to tenant '{tenant_id}' "
            f"(profile {'not found' if profile is None else 'assigned to ' + str(profile.get('tenant_id'))})."
        )
        raise HTTPException(status_code=403, detail="Nu aveți acces la acest tenant.")
    return user
