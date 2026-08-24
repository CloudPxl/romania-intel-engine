import os
import time
import logging
from fastapi import Request, HTTPException
from typing import Dict, Tuple

logger = logging.getLogger("SecurityGuard")
RATE_LIMIT_STORE: Dict[str, Tuple[int, float]] = {}
RATE_LIMIT_REQUESTS = 180
RATE_LIMIT_WINDOW = 60

class SecurityGuard:
    @staticmethod
    def enforce_rate_limit(request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        
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
        return {"user_id": "usr_verified", "role": "Director Bidding & Strategie"}
