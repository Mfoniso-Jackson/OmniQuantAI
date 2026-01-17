"""
WEEX API Client (OmniQuantAI)
----------------------------
Minimal, reliable WEEX REST client with:
- .env loading
- Base64 HMAC-SHA256 signing
- GET/POST support
- Query string support
- Debug printing for WEEX support
"""

import os
import time
import hmac
import hashlib
import base64
import json
from typing import Dict, Any, Optional, Tuple
import requests
from dotenv import load_dotenv


# ============================================================
# ENV + CONFIG
# ============================================================

load_dotenv()

WEEX_API_KEY = os.getenv("WEEX_API_KEY")
WEEX_API_SECRET = os.getenv("WEEX_API_SECRET")
WEEX_API_PASSPHRASE = os.getenv("WEEX_API_PASSPHRASE")

if not WEEX_API_KEY or not WEEX_API_SECRET or not WEEX_API_PASSPHRASE:
    raise RuntimeError("❌ Missing WEEX_API_KEY / WEEX_API_SECRET / WEEX_API_PASSPHRASE in .env")

BASE_URL = os.getenv("WEEX_BASE_URL", "https://api-contract.weex.com")
DEFAULT_LOCALE = os.getenv("WEEX_LOCALE", "en-US")


# ============================================================
# SIGNING
# ============================================================

def _generate_signature(
    secret_key: str,
    timestamp: str,
    method: str,
    request_path: str,
    query_string: str = "",
    body: str = ""
) -> str:
    """
    WEEX signature format (confirmed working):
    message = timestamp + METHOD + request_path + query_string + body
    signature = Base64(HMAC_SHA256(secret, message))
    """
    message = f"{timestamp}{method.upper()}{request_path}{query_string}{body}"
    digest = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _build_headers(
    api_key: str,
    secret_key: str,
    passphrase: str,
    method: str,
    request_path: str,
    query_string: str = "",
    body: str = ""
) -> Dict[str, str]:
    ts = str(int(time.time() * 1000))
    sign = _generate_signature(secret_key, ts, method, request_path, query_string, body)

    return {
        "ACCESS-KEY": api_key,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
        "locale": DEFAULT_LOCALE,
    }


# ============================================================
# CLIENT
# ============================================================

class WeexClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        private: bool = False,
        timeout: int = 15
    ) -> Tuple[int, str]:
        """
        Core request method.
        Returns: (status_code, response_text)
        """

        method = method.upper()
        path = path if path.startswith("/") else f"/{path}"

        query_string = ""
        if params:
            # must match WEEX signing style: ?a=1&b=2
            query_string = "?" + "&".join([f"{k}={params[k]}" for k in sorted(params.keys())])

        url = f"{self.base_url}{path}{query_string}"

        json_body = ""
        if body is not None:
            json_body = json.dumps(body, separators=(",", ":"))

        headers = None
        if private:
            headers = _build_headers(
                api_key=WEEX_API_KEY,
                secret_key=WEEX_API_SECRET,
                passphrase=WEEX_API_PASSPHRASE,
                method=method,
                request_path=path,
                query_string=query_string,
                body=json_body if method == "POST" else ""
            )

        # Debug prints (good for WEEX support)
        print("\n➡️ REQUEST")
        print("URL:", url)
        print("METHOD:", method)
        print("PRIVATE:", private)

        if method == "GET":
            r = self.session.get(url, headers=headers, timeout=timeout)
        elif method == "POST":
            r = self.session.post(url, headers=headers, data=json_body, timeout=timeout)
        else:
            raise ValueError("Unsupported HTTP method. Use GET or POST.")

        print("⬅️ STATUS:", r.status_code)
        print("⬅️ RESPONSE:", r.text)

        return r.status_code, r.text

    # -------------------------
    # Convenience wrappers
    # -------------------------

    def public_get(self, path: str, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", path, params=params, private=False)

    def private_get(self, path: str, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", path, params=params, private=True)

    def private_post(self, path: str, body: Dict[str, Any]):
        return self._request("POST", path, body=body, private=True)


# ============================================================
# QUICK TEST
# ============================================================

if __name__ == "__main__":
    client = WeexClient()

    print("\n=== WEEX CLIENT QUICK TEST ===")

    # Balance (private)
    client.private_get("/capi/v2/account/assets")

    # Ticker (public-ish via capi market endpoint)
    client.private_get("/capi/v2/market/ticker", params={"symbol": "cmt_btcusdt"})
