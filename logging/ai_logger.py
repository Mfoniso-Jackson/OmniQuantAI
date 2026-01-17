"""
ai_logger.py
------------
Purpose:
Create and upload WEEX AI Logs for AI Wars compliance.

Requirements (from WEEX docs):
- model version
- input/output data
- execution details
- explanation (<= 1000 chars)

Endpoint:
POST /capi/v2/order/uploadAiLog
"""

import os
import time
import hmac
import hashlib
import json
import requests
from typing import Dict, Any, Optional
from dotenv import load_dotenv


# ============================================================
# ENV + CONSTANTS
# ============================================================

load_dotenv()

BASE_URL = "https://api-contract.weex.com"
UPLOAD_PATH = "/capi/v2/order/uploadAiLog"
METHOD = "POST"

API_KEY = os.getenv("WEEX_API_KEY")
API_SECRET = os.getenv("WEEX_API_SECRET")
API_PASSPHRASE = os.getenv("WEEX_API_PASSPHRASE")

if not API_KEY or not API_SECRET or not API_PASSPHRASE:
    raise RuntimeError("❌ Missing WEEX_API_KEY / WEEX_API_SECRET / WEEX_API_PASSPHRASE in .env")


# ============================================================
# SIGNING (WORKING FORMAT)
# sign = Base64(HMAC_SHA256(secret, ts + method + path + body))
# ============================================================

def _base64_hmac_sha256(secret: str, msg: str) -> str:
    raw = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
    # WEEX expects base64 for many capi endpoints (this matches your working run)
    import base64
    return base64.b64encode(raw).decode("utf-8")


def build_headers(ts: str, body_json: str) -> Dict[str, str]:
    payload = f"{ts}{METHOD}{UPLOAD_PATH}{body_json}"
    signature = _base64_hmac_sha256(API_SECRET, payload)

    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "locale": "en-US",
        "Content-Type": "application/json",
    }


# ============================================================
# PAYLOAD BUILDER (Clean + Judge-Friendly)
# ============================================================

def _truncate_explanation(text: str, max_len: int = 1000) -> str:
    if not text:
        return ""
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def build_ai_log_from_decision_record(
    order_id: Optional[int],
    decision_record: Dict[str, Any],
    stage: str,
    model: str,
) -> Dict[str, Any]:
    """
    decision_record should contain (from run.py):
    - symbol
    - price
    - decision
    - confidence
    - signals
    - score (optional)
    - explanation (optional)
    """

    symbol = decision_record.get("symbol")
    price = decision_record.get("price")
    decision = decision_record.get("decision")
    confidence = decision_record.get("confidence")
    signals = decision_record.get("signals", {})
    score = decision_record.get("score", None)
    explanation_obj = decision_record.get("explanation", None)

    # Create a clean, human-readable explanation string
    if isinstance(explanation_obj, dict):
        # explanation from your engine = per-signal weighted contributions
        exp_str = (
            f"Weighted explainable decision. "
            f"Decision={decision}, Confidence={confidence}. "
            f"Contributions={explanation_obj}"
        )
    elif isinstance(explanation_obj, str):
        exp_str = explanation_obj
    else:
        exp_str = (
            f"Decision={decision} based on weighted signals. "
            f"Confidence={confidence}."
        )

    exp_str = _truncate_explanation(exp_str, 1000)

    # WEEX requires JSON for input/output fields
    ai_input = {
        "symbol": symbol,
        "features": signals,
        "price": price,
        "timestamp": decision_record.get("timestamp"),
    }

    ai_output = {
        "signal": decision,
        "confidence": confidence,
        "score": score,
        "execution": {
            "symbol": symbol,
            "side": "BUY" if decision == "BUY" else ("SELL" if decision == "SELL" else "NONE"),
            "order_type": "IOC",
        },
    }

    payload = {
        "orderId": int(order_id) if order_id is not None else None,
        "stage": stage,
        "model": model,
        "input": ai_input,
        "output": ai_output,
        "explanation": exp_str,
    }

    return payload


# ============================================================
# UPLOAD
# ============================================================

def upload_ai_log(client, ai_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upload AI log using the same credentials.
    client param is accepted for compatibility with run.py, but not required.
    We'll send directly via requests to avoid coupling.
    """
    url = BASE_URL + UPLOAD_PATH

    body_json = json.dumps(ai_payload, separators=(",", ":"), ensure_ascii=False)
    ts = str(int(time.time() * 1000))
    headers = build_headers(ts, body_json)

    r = requests.post(url, headers=headers, data=body_json, timeout=15)

    # For debugging:
    # print("AI LOG STATUS:", r.status_code)
    # print("AI LOG TEXT:", r.text)

    if r.status_code != 200:
        raise RuntimeError(f"AI log upload failed: {r.status_code} {r.text}")

    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


# ============================================================
# CLI TEST (optional)
# ============================================================

if __name__ == "__main__":
    # Minimal local test without placing real orders.
    fake_decision_record = {
        "symbol": "cmt_btcusdt",
        "price": 91358.1,
        "decision": "BUY",
        "confidence": 0.78,
        "signals": {"momentum": 0.6, "trend": 0.4, "volatility": 0.2, "sentiment": 0.0},
        "score": 0.42,
        "explanation": {"momentum": 0.21, "trend": 0.12, "volatility": -0.04, "sentiment": 0.0},
        "timestamp": int(time.time()),
    }

    payload = build_ai_log_from_decision_record(
        order_id=None,
        decision_record=fake_decision_record,
        stage="Decision Making",
        model="OmniQuantAI-v0.1",
    )

    print("✅ AI LOG PAYLOAD PREVIEW:")
    print(json.dumps(payload, indent=2))

    # Uncomment to actually upload (ONLY if your UID has permission)
    # print(upload_ai_log(None, payload))
