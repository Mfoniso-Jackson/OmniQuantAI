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

BASE_URL = "https://api-contract.weex.com"

if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing WEEX_API_KEY or WEEX_API_SECRET in .env")

# =========================
# SIGNATURE HELPERS
# =========================
def get_timestamp():
    return str(int(time.time() * 1000))

def sign(message: str) -> str:
    return hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

def headers(method: str, path: str, body: str = "") -> dict:
    ts = get_timestamp()
    payload = ts + method.upper() + path + body
    signature = sign(payload)

    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json"
    }

# =========================
# API TESTS
# =========================
def test_public_time():
    print("\n🔹 Testing public market time API...")
    url = BASE_URL + "/capi/v2/market/time"

    r = requests.get(url, timeout=5)
    print("Status:", r.status_code)
    print("Response:", r.text)

def test_private_position():
    print("\n🔹 Testing private position API (auth check)...")
    path = "/v1/position"
    url = BASE_URL + path

    for attempt in range(3):
        try:
            r = requests.get(
                url,
                headers=headers("GET", path),
                timeout=5
            )

            print(f"\nAttempt {attempt + 1}")
            print("Status:", r.status_code)
            print("Response:", r.text)

            # Any response proves auth + connectivity
            return

        except Exception as e:
            print("⚠️ Network error:", e)
            time.sleep(2)

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
