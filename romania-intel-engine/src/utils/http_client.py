import httpx
import asyncio
import random
from typing import Optional, Any, Dict

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
]

async def fetch_with_retry(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    json_data: Optional[Any] = None,
    json: Optional[Any] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 8.0,
    max_retries: int = 2
) -> Optional[Any]:
    req_json = json if json is not None else json_data
    req_headers = headers or {}
    if "User-Agent" not in req_headers:
        req_headers["User-Agent"] = random.choice(USER_AGENTS)

    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
                if method.upper() == "POST":
                    resp = await client.post(url, headers=req_headers, json=req_json, params=params)
                else:
                    resp = await client.get(url, headers=req_headers, params=params)

                if resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "")
                    if "application/json" in content_type:
                        try:
                            return resp.json()
                        except Exception:
                            return resp.text
                    return resp.text
                elif resp.status_code in [404, 403, 410, 500]:
                    return None
        except Exception:
            if attempt == max_retries:
                return None
            await asyncio.sleep(0.5)
    return None
