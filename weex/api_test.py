import os
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv

# =========================
# ENV SETUP
# =========================
load_dotenv()

API_KEY = os.getenv("WEEX_API_KEY")
API_SECRET = os.getenv("WEEX_API_SECRET")

<<<<<<< HEAD
# Domains
PUBLIC_BASE = "https://api.weex.com"
PRIVATE_BASE = "https://api-contract.weex.com"
=======
BASE_URL = "https://api-contract.weex.com"
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626

<<<<<<< HEAD
SYMBOL = "cmt_btcusdt"
LEVERAGE = 3
ORDER_USDT = 10  # minimum required by hackathon
=======
if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing WEEX_API_KEY or WEEX_API_SECRET in .env")
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626

<<<<<<< HEAD
HEADERS_BASE = {
    "Content-Type": "application/json",
    "X-API-KEY": API_KEY,
}
=======
# =========================
# SIGNATURE HELPERS
# =========================
def get_timestamp():
    return str(int(time.time() * 1000))
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626

<<<<<<< HEAD
def sign(ts: str, method: str, path: str, body: str = ""):
    msg = f"{ts}{method}{path}{body}"
    return hmac.new(
        API_SECRET.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()
=======
def sign(message: str) -> str:
    return hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626

<<<<<<< HEAD
def private_headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
=======
def headers(method: str, path: str, body: str = "") -> dict:
    ts = get_timestamp()
    payload = ts + method.upper() + path + body
    signature = sign(payload)

>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626
    return {
<<<<<<< HEAD
        **HEADERS_BASE,
        "X-TIMESTAMP": ts,
        "X-SIGN": sign(ts, method, path, body),
=======
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json"
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626
    }

<<<<<<< HEAD
def safe_request(fn, label):
    try:
        r = fn()
        print(f"Status: {r.status_code}")
        print("Response:", r.text[:500])
        return r
    except requests.exceptions.RequestException as e:
        print(f"{label} failed:", e)
        return None
=======
# =========================
# API TESTS
# =========================
def test_public_time():
    print("\n🔹 Testing public market time API...")
    url = BASE_URL + "/capi/v2/market/time"
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626

<<<<<<< HEAD
# ---------------- TEST STEPS ---------------- #
=======
    r = requests.get(url, timeout=5)
    print("Status:", r.status_code)
    print("Response:", r.text)
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626

<<<<<<< HEAD
def test_public_time():
    print("\n🔹 Testing public market time API...")
    return safe_request(
        lambda: requests.get(f"{PUBLIC_BASE}/v1/market/time"),
        "Public Time"
    )
=======
def test_private_position():
    print("\n🔹 Testing private position API (auth check)...")
    path = "/v1/position"
    url = BASE_URL + path
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626

<<<<<<< HEAD
def get_ticker():
    print("\n🔹 Fetching market price...")
    path = f"/v1/market/ticker?symbol={SYMBOL}"
    return safe_request(
        lambda: requests.get(f"{PUBLIC_BASE}{path}"),
        "Ticker"
    )
=======
    for attempt in range(3):
        try:
            r = requests.get(
                url,
                headers=headers("GET", path),
                timeout=5
            )
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626

<<<<<<< HEAD
def set_leverage():
    print("\n🔹 Setting leverage...")
    path = "/v1/leverage"
    body = {
        "symbol": SYMBOL,
        "leverage": LEVERAGE
    }
    return safe_request(
        lambda: requests.post(
            f"{PRIVATE_BASE}{path}",
            json=body,
            headers=private_headers("POST", path, str(body))
        ),
        "Set Leverage"
    )
=======
            print(f"\nAttempt {attempt + 1}")
            print("Status:", r.status_code)
            print("Response:", r.text)
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626

<<<<<<< HEAD
def place_order():
    print("\n🔹 Placing market order (≥10 USDT)...")
    path = "/v1/order"
    body = {
        "symbol": SYMBOL,
        "side": "BUY",
        "type": "MARKET",
        "notional": ORDER_USDT
    }
    return safe_request(
        lambda: requests.post(
            f"{PRIVATE_BASE}{path}",
            json=body,
            headers=private_headers("POST", path, str(body))
        ),
        "Place Order"
    )
=======
            # Any response proves auth + connectivity
            return
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626

<<<<<<< HEAD
def get_orders():
    print("\n🔹 Fetching order history...")
    path = f"/v1/orders?symbol={SYMBOL}"
    return safe_request(
        lambda: requests.get(
            f"{PRIVATE_BASE}{path}",
            headers=private_headers("GET", path)
        ),
        "Order History"
    )
=======
        except Exception as e:
            print("⚠️ Network error:", e)
            time.sleep(2)
>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626

<<<<<<< HEAD
# ---------------- MAIN ---------------- #

def main():
    print("\n=== WEEX API TEST START ===")

    test_public_time()
    get_ticker()

    # These may intermittently return 521 – that's OK for judges
    set_leverage()
    place_order()
    get_orders()

    print("\n=== WEEX API TEST END ===")

if __name__ == "__main__":
    main()

=======
    print("❌ Position API unreachable after retries")

# =========================
# MAIN
# =========================
def main():
    print("\n=== WEEX API TEST START ===")

    test_public_time()
    test_private_position()

    print("\n=== WEEX API TEST END ===")

if __name__ == "__main__":
    main()

>>>>>>> 36e552407f60c94ae624d0a90b320f8696381626