# api_test.py
import time
import hmac
import hashlib
import base64
import requests
import json
import os
from dotenv import load_dotenv

# ------------------------
# LOAD ENV
# ------------------------
load_dotenv()

API_KEY = os.getenv("WEEX_API_KEY")
API_SECRET = os.getenv("WEEX_API_SECRET")
API_PASSPHRASE = os.getenv("WEEX_API_PASSPHRASE")

assert API_KEY and API_SECRET and API_PASSPHRASE, "❌ Missing API credentials"

<<<<<<< HEAD
PUBLIC_BASE = "https://contract.weex.com"
PRIVATE_BASE = "https://api-contract.weex.com"

SYMBOL = "cmt_btcusdt"
LEVERAGE = 1
QTY = "0.0002"  # ~10 USDT
=======
>>>>>>> da3740cb80f2cca9eff4df1d31b2a17a60dad186
BASE_URL = "https://api-contract.weex.com"

# ------------------------
# SIGNATURES
# ------------------------
def sign_get(secret, timestamp, method, path, query):
    msg = f"{timestamp}{method}{path}{query}"
    digest = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()

def sign_post(secret, timestamp, method, path, query, body):
    msg = f"{timestamp}{method}{path}{query}{body}"
    digest = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()

def auth_headers(signature, timestamp):
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json",
        "locale": "en-US"
    }

# ------------------------
# REQUEST HELPERS
# ------------------------
def private_get(path, query=""):
    timestamp = str(int(time.time() * 1000))
    sig = sign_get(API_SECRET, timestamp, "GET", path, query)
    headers = auth_headers(sig, timestamp)

    url = BASE_URL + path + query
    print("\n➡️ REQUEST URL:", url)

    r = requests.get(url, headers=headers, timeout=10)
    print("⬅️ STATUS:", r.status_code)
    print("⬅️ RESPONSE:", r.text)
    return r

def private_post(path, body):
    timestamp = str(int(time.time() * 1000))
    body_json = json.dumps(body)
    sig = sign_post(API_SECRET, timestamp, "POST", path, "", body_json)
    headers = auth_headers(sig, timestamp)

    url = BASE_URL + path
    print("\n➡️ REQUEST URL:", url)

    r = requests.post(url, headers=headers, data=body_json, timeout=10)
    print("⬅️ STATUS:", r.status_code)
    print("⬅️ RESPONSE:", r.text)
    return r

def public_get(path, params=""):
    url = BASE_URL + path + params
    print("\n➡️ REQUEST URL:", url)

    r = requests.get(url, timeout=10)
    print("⬅️ STATUS:", r.status_code)
    print("⬅️ RESPONSE:", r.text)
    return r

# ------------------------
# API FUNCTIONS
# ------------------------
# Account Balance
def test_balance():
    print("\n🔹 Account Balance Test")
    return private_get("/capi/v2/account/assets")

# Price Ticker
def test_price(symbol="cmt_btcusdt"):
    print("\n🔹 Price Ticker Test")
    return public_get(f"/capi/v2/market/ticker?symbol={symbol}")

# Set Leverage
def set_leverage(symbol, margin_mode=1, long_leverage="2", short_leverage=None):
    """
    margin_mode: 1=Cross, 3=Isolated
    long_leverage: string
    short_leverage: string, optional (if Cross, must match long_leverage)
    """
    if short_leverage is None:
        short_leverage = long_leverage

    body = {
        "symbol": symbol,
        "marginMode": margin_mode,
        "longLeverage": long_leverage,
        "shortLeverage": short_leverage
    }
    print(f"\n🔹 Set Leverage ({symbol})")
    return private_post("/capi/v2/account/leverage", body)

# Place Order
def place_order(symbol, client_oid, size, type_, order_type="0", match_price="0", price="0",
                presetTakeProfitPrice=None, presetStopLossPrice=None, margin_mode=1):
    """
    type_: 1=open long, 2=open short, 3=close long, 4=close short
    order_type: 0=Normal, 1=Post-Only, 2=FOK, 3=IOC
    match_price: 0=Limit, 1=Market
    """
    body = {
        "symbol": symbol,
        "client_oid": client_oid,
        "size": size,
        "type": str(type_),
        "order_type": order_type,
        "match_price": match_price,
        "price": str(price),
        "marginMode": margin_mode
    }
    if presetTakeProfitPrice:
        body["presetTakeProfitPrice"] = str(presetTakeProfitPrice)
    if presetStopLossPrice:
        body["presetStopLossPrice"] = str(presetStopLossPrice)

    print(f"\n🔹 Place Order ({symbol}, {client_oid})")
    return private_post("/capi/v2/order/placeOrder", body)

# Get Current Orders
def get_current_orders(symbol=None, order_id=None, start_time=None, end_time=None, limit=100, page=0):
    print(f"\n🔹 Get Current Orders ({symbol})")
    query_params = [f"limit={limit}", f"page={page}"]
    if symbol:
        query_params.append(f"symbol={symbol}")
    if order_id:
        query_params.append(f"orderId={order_id}")
    if start_time:
        query_params.append(f"startTime={start_time}")
    if end_time:
        query_params.append(f"endTime={end_time}")
    query_string = "?" + "&".join(query_params)
    return private_get("/capi/v2/order/current", query_string)

# Get History Orders
def get_order_history(symbol=None, page_size=100, create_date=None, end_create_date=None):
    print(f"\n🔹 Get History Orders ({symbol})")
    query_params = [f"pageSize={page_size}"]
    if symbol:
        query_params.append(f"symbol={symbol}")
    if create_date:
        query_params.append(f"createDate={create_date}")
    if end_create_date:
        query_params.append(f"endCreateDate={end_create_date}")
    query_string = "?" + "&".join(query_params)
    return private_get("/capi/v2/order/history", query_string)

# Get Fills
def get_order_fills(symbol=None, order_id=None, start_time=None, end_time=None, limit=100):
    print(f"\n🔹 Get Fills ({symbol})")
    query_params = [f"limit={limit}"]
    if symbol:
        query_params.append(f"symbol={symbol}")
    if order_id:
        query_params.append(f"orderId={order_id}")
    if start_time:
        query_params.append(f"startTime={start_time}")
    if end_time:
        query_params.append(f"endTime={end_time}")
    query_string = "?" + "&".join(query_params)
    return private_get("/capi/v2/order/fills", query_string)

# ------------------------
# MAIN TEST FLOW
# ------------------------
if __name__ == "__main__":
    print("\n=== WEEX API TEST START ===")

    # 1. Check account balance
    test_balance()

    # 2. Check BTC/USDT price
    test_price("cmt_btcusdt")

    # 3. Set leverage example
    set_leverage(symbol="cmt_btcusdt", margin_mode=1, long_leverage="5")

    # 4. Place a test order
    place_order(
        symbol="cmt_btcusdt",
        client_oid=str(int(time.time()*1000)),
        size="0.001",
        type_=1,  # Open long
        order_type="0",
        match_price="1",  # Market
    )

    # 5. Get current open orders
    get_current_orders(symbol="cmt_btcusdt")

    # 6. Get historical orders
    get_order_history(symbol="cmt_btcusdt", page_size=10)

    # 7. Get fills (executed trades)
    get_order_fills(symbol="cmt_btcusdt", limit=10)

    print("\n=== WEEX API TEST END ===")
