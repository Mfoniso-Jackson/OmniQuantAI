import os
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("WEEX_API_KEY")
API_SECRET = os.getenv("WEEX_API_SECRET")

assert API_KEY and API_SECRET, "Missing API credentials"

PUBLIC_BASE = "https://contract.weex.com"
PRIVATE_BASE = "https://api-contract.weex.com"

SYMBOL = "cmt_btcusdt"
LEVERAGE = 1
QTY = "0.0002"  # ~10 USDT

# ------------------------
# SIGNING
# ------------------------
def sign(ts, method, path, body=""):
    msg = f"{ts}{method}{path}{body}"
    return hmac.new(
        API_SECRET.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()

def headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
    return {
        "Content-Type": "application/json",
        "ACCESS-KEY": API_KEY,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-SIGN": sign(ts, method, path, body)
    }

# ------------------------
# STEP 1 — PUBLIC TIME
# ------------------------
def server_time():
    print("\n🔹 Server Time")
    r = requests.get(f"{PUBLIC_BASE}/v1/public/time")
    print(r.status_code, r.text)

# ------------------------
# STEP 2 — TICKER (PRICE)
# ------------------------
def get_price():
    print("\n🔹 Get Ticker")
    r = requests.get(
        f"{PUBLIC_BASE}/v1/public/ticker",
        params={"symbol": SYMBOL}
    )
    print(r.status_code, r.text)
    data = r.json()
    return data["last"]

# ------------------------
# STEP 3 — SET LEVERAGE
# ------------------------
def set_leverage():
    print("\n🔹 Set Leverage")
    path = "/v1/leverage"
    body = {
        "symbol": SYMBOL,
        "leverage": LEVERAGE
    }
    r = requests.post(
        PRIVATE_BASE + path,
        json=body,
        headers=headers("POST", path, str(body))
    )
    print(r.status_code, r.text)

# ------------------------
# STEP 4 — PLACE LIMIT ORDER ✅
# ------------------------
def place_order(price):
    print("\n🔹 Place LIMIT Order (MANDATORY)")
    path = "/v1/order"

    body = {
        "symbol": SYMBOL,
        "side": "BUY",
        "orderType": "LIMIT",
        "price": price,
        "quantity": QTY,
        "openType": "ISOLATED",
        "positionSide": "LONG",
        "leverage": LEVERAGE
    }

    r = requests.post(
        PRIVATE_BASE + path,
        json=body,
        headers=headers("POST", path, str(body))
    )
    print("Status:", r.status_code)
    print("Response:", r.text)

# ------------------------
# MAIN
# ------------------------
def main():
    print("\n=== WEEX API TEST START ===")

    server_time()
    price = get_price()
    set_leverage()
    place_order(price)

    print("\n=== WEEX API TEST END ===")

if __name__ == "__main__":
    main()
