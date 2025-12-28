import time
import hmac
import hashlib
import base64
import json
import requests
import os
from dotenv import load_dotenv

load_dotenv()

# ===== CONFIG =====
API_KEY = os.getenv("WEEX_API_KEY")
API_SECRET = os.getenv("WEEX_API_SECRET")
PASSPHRASE = os.getenv("WEEX_API_PASSPHRASE")

if not all([API_KEY, API_SECRET, PASSPHRASE]):
    raise RuntimeError("Missing WEEX API credentials in .env file")


BASE_URL = "https://api.weex.com"
SYMBOL = "cmt_btcusdt"   # Common hackathon symbol
ORDER_SIZE = "0.0001"   # Very small & safe

# ===== SIGNATURE =====
def sign(timestamp, method, request_path, body=""):
    message = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign(ts, method, path, body),
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
        "locale": "en-US"
    }

# ===== 1️⃣ FETCH MARKET INFO =====
print("Fetching contract info...")
market_path = f"/capi/v2/market/contracts?symbol={SYMBOL}"
market_resp = requests.get(BASE_URL + market_path)
print(json.dumps(market_resp.json(), indent=2))

# ===== 2️⃣ PLACE ORDER =====
print("\nPlacing test order...")
order_path = "/capi/v2/order/placeOrder"

order_body = {
    "symbol": SYMBOL,
    "client_oid": f"omniquant_test_{int(time.time())}",
    "size": ORDER_SIZE,
    "type": "1",        # 1 = open long (safe demo)
    "order_type": "0",  # 0 = limit
    "match_price": "1", # market-like execution
    "price": "100000"   # far limit, won't affect fill
}

body_str = json.dumps(order_body)
order_resp = requests.post(
    BASE_URL + order_path,
    headers=headers("POST", order_path, body_str),
    data=body_str
)

print(json.dumps(order_resp.json(), indent=2))

# ===== 3️⃣ DONE =====
print("\nAPI test completed successfully.")

