import os
import time
import hmac
import hashlib
import base64
import json
import base64
import requests
from dotenv import load_dotenv

# ============================================================
# LOAD ENV
# ============================================================

load_dotenv()

API_KEY = os.getenv("WEEX_API_KEY")
API_SECRET = os.getenv("WEEX_API_SECRET")
API_PASSPHRASE = os.getenv("WEEX_API_PASSPHRASE")

if not API_KEY or not API_SECRET or not API_PASSPHRASE:
<<<<<<< HEAD
    raise RuntimeError("❌ Missing WEEX API credentials")
=======
    raise RuntimeError("❌ Missing WEEX API credentials in .env")
>>>>>>> 264c7c6b46352c0303a972d37c59ecb04c24e5d3

<<<<<<< HEAD
# ============================================================
# CONFIG
# ============================================================

=======
>>>>>>> 264c7c6b46352c0303a972d37c59ecb04c24e5d3
BASE_URL = "https://api-contract.weex.com"
PATH = "/capi/v2/order/uploadAiLog"
METHOD = "POST"


# ------------------------
# SIGNING (BASE64 HMAC-SHA256 ✅)
# message = timestamp + METHOD + path + body
# ------------------------
def sign(timestamp: str, method: str, path: str, body: str = "") -> str:
    message = f"{timestamp}{method.upper()}{path}{body}"
    digest = hmac.new(
        API_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def build_headers(method: str, path: str, body: str = "") -> dict:
    ts = str(int(time.time() * 1000))
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign(ts, method, path, body),
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "locale": "en-US",
        "Content-Type": "application/json"
    }


# ------------------------
# UPLOAD FUNCTION (dynamic orderId ✅)
# ------------------------
def upload_ai_log(ai_log: dict):
    path = "/capi/v2/order/uploadAiLog"
    url = BASE_URL + path

    body_json = json.dumps(ai_log, separators=(",", ":"))
    headers = build_headers("POST", path, body_json)

    print("\n🚀 Uploading AI Log")
    print("➡️ URL:", url)
    print("➡️ ORDER ID:", ai_log.get("orderId"))
    print("➡️ PAYLOAD:", body_json)
# ============================================================
# AI LOG PAYLOAD
# ============================================================

AI_LOG = {
    "orderId": "702628302073888771",
    "stage": "Decision Making",
    "model": "OmniQuantAI-v0.1",
    "input": {
        "prompt": "Analyze BTCUSDT perpetual futures and decide trade direction",
        "data": {
            "symbol": "cmt_btcusdt",
            "last_price": 91358.1,
            "mark_price": 91364.6,
            "index_price": 91407.677,
            "volume_24h": 2862623799.40485
        }
    },
    "output": {
        "signal": "OPEN_LONG",
        "confidence": 0.78,
        "execution": {
            "order_type": "IOC",
            "side": "BUY",
            "size": "0.001",
            "symbol": "cmt_btcusdt"
        }
    },
    "explanation": (
        "The AI agent evaluated real-time futures price, volume, and mark/index "
        "price deviations and executed a controlled long decision."
    )
}

# ============================================================
# SIGNATURE (BASE64 — REQUIRED)
# ============================================================

def generate_signature(timestamp: str, body: str) -> str:
    payload = f"{timestamp}{METHOD}{PATH}{body}"
    print("🔑 Signing payload:", payload)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).digest()

    return base64.b64encode(signature).decode()

def build_headers(body: str):
    ts = str(int(time.time() * 1000))
    sign = generate_signature(ts, body)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "locale": "zh-CN",
        "Content-Type": "application/json"
    }

    print("📝 Headers:", headers)
    return headers

# ============================================================
# UPLOAD
# ============================================================

def upload_ai_log():
    body = json.dumps(AI_LOG, separators=(",", ":"), ensure_ascii=False)
    headers = build_headers(body)

    url = BASE_URL + PATH

    print("\n🚀 Uploading AI Log")
    print("➡️ URL:", url)
    print("➡️ Payload:", body)

    response = requests.post(url, headers=headers, data=body, timeout=15)

    print("⬅️ STATUS:", response.status_code)
    print("⬅️ RESPONSE:", response.text)

    response.raise_for_status()
    return response.json()


# ------------------------
# SAMPLE AI LOG (replace per trade)
# ------------------------
# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    AI_LOG = {
        "orderId": 702628302073888771,
        "stage": "Decision Making",
        "model": "OmniQuantAI-v0.1",
        "input": {
            "prompt": "Analyze BTCUSDT perpetual futures market conditions and determine trade direction.",
            "data": {
                "symbol": "cmt_btcusdt",
                "last_price": 91358.1,
                "mark_price": 91364.6,
                "index_price": 91407.677,
                "volume_24h": 2862623799.40485
            }
        },
        "output": {
            "signal": "OPEN_LONG",
            "confidence": 0.78,
            "execution": {
                "order_type": "IOC",
                "side": "BUY",
                "size": "0.001",
                "symbol": "cmt_btcusdt"
            }
        },
        "explanation": (
            "The AI agent evaluated real-time futures features (price, spread, "
            "volume, mark/index deviation) and approved a controlled long entry "
            "under risk constraints."
        )
    }

    try:
        result = upload_ai_log(AI_LOG)
        print("\n✅ AI LOG UPLOAD SUCCESS")
        print(result)
    except Exception as e:
        print("\n❌ AI LOG UPLOAD FAILED")
        print(str(e))
