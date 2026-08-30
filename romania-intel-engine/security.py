import os
import time
import logging
from typing import Dict, Optional, Tuple

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError, PyJWKSetError
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
