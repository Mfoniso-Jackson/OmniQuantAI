"""
WEEX API Client (OmniQuantAI)
----------------------------
Reliable WEEX REST client with:
- .env loading
- Base64 HMAC-SHA256 signing (confirmed working)
- GET/POST support
- Query string sorting
- Debug printing for WEEX support
- Convenience methods for OmniQuantAI pipeline

Used by:
- execution_engine.py
- position_manager.py
- run.py
"""

from __future__ import annotations

import os
import time
import hmac
import hashlib
import base64
import json
from typing import Dict, Any, Optional
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
    raise RuntimeError(
        "❌ Missing WEEX_API_KEY / WEEX_API_SECRET / WEEX_API_PASSPHRASE in .env"
    )

BASE_URL = os.getenv("WEEX_BASE_URL", "https://api-contract.weex.com").rstrip("/")
DEFAULT_LOCALE = os.getenv("WEEX_LOCALE", "en-US")


# ============================================================
# SIGNING
# ============================================================

def _build_query_string(params: Optional[Dict[str, Any]]) -> str:
    """
    WEEX signing requires stable query formatting:
    ?a=1&b=2 (sorted by key)
    """
    if not params:
        return ""
    pairs = []
    for k in sorted(params.keys()):
        pairs.append(f"{k}={params[k]}")
    return "?" + "&".join(pairs)


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
    method: str,
    request_path: str,
    query_string: str = "",
    body: str = ""
) -> Dict[str, str]:
    ts = str(int(time.time() * 1000))
    sign = _generate_signature(
        WEEX_API_SECRET,
        ts,
        method,
        request_path,
        query_string,
        body
    )

    return {
        "ACCESS-KEY": WEEX_API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": WEEX_API_PASSPHRASE,
        "Content-Type": "application/json",
        "locale": DEFAULT_LOCALE,
    }


# ============================================================
# CLIENT
# ============================================================

class WEEXClient:
    """
    Minimal high-reliability WEEX client returning JSON dicts.

    Notes:
    - For GET requests: body must not be included in signing.
    - For POST requests: JSON body (minified) must be included in signing.
    """

    def __init__(self, base_url: str = BASE_URL, debug: bool = True):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.debug = debug

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        private: bool = False,
        timeout: int = 15
    ) -> Dict[str, Any]:
        method = method.upper()
        path = path if path.startswith("/") else f"/{path}"

        query_string = _build_query_string(params)
        url = f"{self.base_url}{path}{query_string}"

        # Body must be compact JSON when signed
        json_body = ""
        if body is not None:
            json_body = json.dumps(body, separators=(",", ":"))

        headers = None
        if private:
            headers = _build_headers(
                method=method,
                request_path=path,
                query_string=query_string,
                body=json_body if method == "POST" else ""
            )

        # Debug prints for WEEX support
        if self.debug:
            print("\n➡️ REQUEST")
            print("URL:", url)
            print("METHOD:", method)
            print("PRIVATE:", private)
            if body is not None:
                print("BODY:", json_body)

        if method == "GET":
            r = self.session.get(url, headers=headers, timeout=timeout)
        elif method == "POST":
            r = self.session.post(url, headers=headers, data=json_body, timeout=timeout)
        else:
            raise ValueError("Unsupported HTTP method. Use GET or POST.")

        if self.debug:
            print("⬅️ STATUS:", r.status_code)
            print("⬅️ RESPONSE:", r.text)

        # WEEX sometimes returns "" on errors
        if not r.text:
            r.raise_for_status()
            return {}

        # Parse JSON safely
        try:
            data = r.json()
        except Exception:
            r.raise_for_status()
            return {"raw": r.text}

        # Raise for non-2xx
        if r.status_code >= 400:
            # keep error JSON for inspection
            raise RuntimeError(f"WEEX error {r.status_code}: {data}")

        return data

    # ============================================================
    # Public / Private wrappers
    # ============================================================

    def public_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", path, params=params, private=False)

    def private_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", path, params=params, private=True)

    def private_post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", path, body=body, private=True)

    # ============================================================
    # OmniQuantAI-required convenience methods
    # ============================================================

    def get_assets(self) -> Dict[str, Any]:
        """
        GET /capi/v2/account/assets
        """
        return self.private_get("/capi/v2/account/assets")

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        GET /capi/v2/market/ticker?symbol=...
        (This is the endpoint you confirmed returns 200)
        """
        return self.private_get("/capi/v2/market/ticker", params={"symbol": symbol})

    def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """
        POST /capi/v2/account/leverage
        """
        payload = {"symbol": symbol, "leverage": leverage}
        return self.private_post("/capi/v2/account/leverage", payload)

    def place_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        POST /capi/v2/order/placeOrder
        Returns:
        {"client_oid": "...", "order_id": "..."}
        """
        return self.private_post("/capi/v2/order/placeOrder", payload)

    def get_current_orders(self, symbol: str, page: int = 0, limit: int = 100) -> Dict[str, Any]:
        """
        GET /capi/v2/order/current?limit=...&page=...&symbol=...
        """
        return self.private_get(
            "/capi/v2/order/current",
            params={"limit": limit, "page": page, "symbol": symbol},
        )

    def get_history_orders(self, symbol: str, page_size: int = 10) -> Dict[str, Any]:
        """
        GET /capi/v2/order/history?pageSize=...&symbol=...
        """
        return self.private_get(
            "/capi/v2/order/history",
            params={"pageSize": page_size, "symbol": symbol},
        )

    def get_fills(self, symbol: str, limit: int = 10) -> Dict[str, Any]:
        """
        GET /capi/v2/order/fills?limit=...&symbol=...
        """
        return self.private_get(
            "/capi/v2/order/fills",
            params={"limit": limit, "symbol": symbol},
        )

    def get_single_position(self, symbol: str) -> Dict[str, Any]:
        """
        GET /capi/v2/account/position/singlePosition?symbol=...
        Used by PositionManager.
        """
        return self.private_get(
            "/capi/v2/account/position/singlePosition",
            params={"symbol": symbol},
        )


# ============================================================
# QUICK TEST
# ============================================================

if __name__ == "__main__":
    client = WEEXClient(debug=True)

    print("\n=== WEEX CLIENT QUICK TEST ===")

    # Balance
    assets = client.get_assets()
    print("✅ assets ok")

    # Ticker
    ticker = client.get_ticker("cmt_btcusdt")
    print("✅ ticker ok:", ticker.get("last"))
