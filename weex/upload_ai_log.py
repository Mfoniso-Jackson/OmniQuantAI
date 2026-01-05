import os
import time
import hmac
import hashlib
import json
import requests
from dotenv import load_dotenv

# ------------------------
# ENV SETUP
# ------------------------
load_dotenv()

API_KEY = os.getenv("WEEX_API_KEY")
API_SECRET = os.getenv("WEEX_API_SECRET")
API_PASSPHRASE = os.getenv("WEEX_API_PASSPHRASE")

assert API_KEY and API_SECRET and API_PASSPHRASE, "Missing WEEX API credentials"

BASE_URL = "https://api-contract.weex.com"

# ------------------------
# SIGNING (CONFIRMED WORKING)
# ------------------------
def sign(timestamp: str, method: str, path: str, body: str = "") -> str:
    """
    WEEX signature format:
    sign = HMAC_SHA256(secret, timestamp + method + path + body)
    """
    message = f"{timestamp}{method}{path}{body}"
    return hmac.new(
        API_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

def build_headers(method: str, path: str, body: str = "") -> dict:
    ts = str(int(time.time() * 1000))
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign(ts, method, path, body),
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

# ------------------------
# AI LOG PAYLOAD (REAL ORDER)
# ------------------------
AI_LOG = {
    "orderId": 702628302073888771,
    "stage": "Decision Making",
    "model": "OmniQuantAI-v0.1 (LLM-assisted trading agent)",
    "input": {
        "prompt": "Analyze BTCUSDT perpetual futures market conditions and determine whether to open a long or short position.",
        "market_data": {
            "symbol": "cmt_btcusdt",
            "last_price": 91358.1,
            "best_bid": 91358.0,
            "best_ask": 91358.1,
            "price_change_24h_percent": 0.017782,
            "volume_24h": 2862623799.40485,
            "mark_price": 91364.6,
            "index_price": 91407.677
        }
    },
    "output": {
        "signal": "OPEN_LONG",
        "confidence": 0.78,
        "execution_plan": {
            "order_type": "IOC",
            "side": "BUY",
            "symbol": "cmt_btcusdt",
            "size": "0.001 BTC"
        },
        "reasoning": "Short-term momentum and liquidity conditions favored a long entry."
    },
    "explanation": (
        "The AI agent evaluated real-time futures price, volume, spread, and "
        "mark/index price deviations. Based on momentum confirmation and "
        "predefined risk constraints, it recommended opening a small long "
        "position, which was executed via the WEEX order API."
    )
}

# ------------------------
# UPLOAD FUNCTION
# ------------------------
def upload_ai_log():
    path = "/capi/v2/order/uploadAiLog"
    url = BASE_URL + path

    body_json = json.dumps(AI_LOG, separators=(",", ":"))

    headers = build_headers("POST", path, body_json)

    print("\n🚀 Uploading AI Log")
    print("➡️ URL:", url)
    print("➡️ ORDER ID:", AI_LOG["orderId"])

    r = requests.post(
        url,
        headers=headers,
        data=body_json,
        timeout=15
    )

    print("⬅️ STATUS:", r.status_code)
    print("⬅️ RESPONSE:", r.text)

    r.raise_for_status()
    return r.json()

# ------------------------
# MAIN
# ------------------------
if __name__ == "__main__":
    try:
        result = upload_ai_log()
        print("\n✅ AI LOG UPLOAD SUCCESS")
        print(result)
    except Exception as e:
        print("\n❌ AI LOG UPLOAD FAILED")
        print(str(e))
