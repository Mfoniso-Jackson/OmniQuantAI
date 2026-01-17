"""
OmniQuantAI - AI Logger (WEEX Compliant)
---------------------------------------
Creates and uploads WEEX-compliant AI logs:
POST /capi/v2/order/uploadAiLog

Required by WEEX live phase:
- model version
- input/output data
- order execution details

This module should be called after every executed order.
"""

from __future__ import annotations

from typing import Dict, Any, Optional
import json
import time


# ===============================
# Utilities
# ===============================

def _truncate(text: str, max_len: int = 1000) -> str:
    """WEEX explanation max length is 1000 chars."""
    if text is None:
        return ""
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


# ===============================
# Payload Builder
# ===============================

def build_ai_log_payload(
    *,
    order_id: Optional[int],
    stage: str,
    model: str,
    symbol: str,
    decision: str,
    confidence: float,
    features: Optional[Dict[str, Any]] = None,
    execution: Optional[Dict[str, Any]] = None,
    explanation: str = ""
) -> Dict[str, Any]:
    """
    Build a WEEX-compliant AI log JSON payload.

    WEEX Required fields:
    - stage (str)
    - model (str)
    - input (json)
    - output (json)
    - explanation (str <= 1000)
    orderId is optional in WEEX docs, but recommended if you have it.
    """

    payload: Dict[str, Any] = {
        "orderId": int(order_id) if order_id is not None else None,
        "stage": stage,
        "model": model,
        "input": {
            "symbol": symbol,
            "features": features or {},
        },
        "output": {
            "signal": decision,
            "confidence": round(_safe_float(confidence), 4),
            "order": execution or {},
        },
        "explanation": _truncate(explanation, 1000),
    }

    return payload


# ===============================
# Canonical OmniQuant Bridge
# ===============================

def build_ai_log_from_decision_record(
    *,
    order_id: Optional[int],
    decision_record: Dict[str, Any],
    stage: str = "Decision Making",
    model: str = "OmniQuantAI-v0.1",
) -> Dict[str, Any]:
    """
    Build AI log payload directly from your canonical DecisionRecord dict.

    Expected decision_record keys (from decision_record.py):
    - symbol, price, timeframe, decision, confidence, signals, model_version
    - approved, position_size, rejection_reason (optional)
    """

    symbol = str(decision_record.get("symbol", ""))
    decision = str(decision_record.get("decision", "HOLD"))
    confidence = float(decision_record.get("confidence", 0.0))
    signals = decision_record.get("signals") or {}
    price = decision_record.get("price")

    # Features = what AI saw
    features = {
        "timeframe": decision_record.get("timeframe"),
        "price": price,
        "signals": signals,
        "decision_hash": decision_record.get("decision_hash"),
    }

    # Execution details = what we tried to do
    execution = {
        "symbol": symbol,
        "side": "BUY" if decision == "BUY" else ("SELL" if decision == "SELL" else "NONE"),
        "order_type": "IOC",
        "requested_position_size": decision_record.get("position_size"),
        "approved": decision_record.get("approved"),
    }

    explanation = (
        f"OmniQuantAI generated a {decision} decision for {symbol} "
        f"based on regime-aware signals (momentum/trend/volatility). "
        f"Confidence={round(confidence, 2)}. "
    )

    # Add risk outcome if exists
    if decision_record.get("approved") is False:
        explanation += f"Trade blocked by risk engine: {decision_record.get('rejection_reason')}."
    elif decision_record.get("approved") is True:
        explanation += "Trade approved under risk constraints."

    # Override model with record model_version if present
    model_final = decision_record.get("model_version") or model

    return build_ai_log_payload(
        order_id=order_id,
        stage=stage,
        model=model_final,
        symbol=symbol,
        decision=decision,
        confidence=confidence,
        features=features,
        execution=execution,
        explanation=explanation,
    )


# ===============================
# Upload Helper
# ===============================

def upload_ai_log(
    client,
    ai_log_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Upload AI log using a WEEX client that supports:

    client.private_post("/capi/v2/order/uploadAiLog", body=<dict>)

    Returns response JSON.
    """

    path = "/capi/v2/order/uploadAiLog"

    print("\n🧠 Uploading WEEX AI Log")
    print("➡️ Endpoint:", path)
    print("➡️ orderId:", ai_log_payload.get("orderId"))
    print("➡️ stage:", ai_log_payload.get("stage"))
    print("➡️ model:", ai_log_payload.get("model"))
    print("➡️ payload:", json.dumps(ai_log_payload, separators=(",", ":")))

    status, text = client.private_post(path, body=ai_log_payload)

    # WEEX success example:
    # {"code":"00000","msg":"success","data":"upload success"}
    if status != 200:
        raise RuntimeError(f"AI log upload failed: status={status}, response={text}")

    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


# ===============================
# Example Usage
# ===============================

if __name__ == "__main__":
    # Example decision record (normally created by decision_record.py)
    example_decision_record = {
        "decision_id": "abc123",
        "timestamp": str(int(time.time())),
        "symbol": "cmt_btcusdt",
        "timeframe": "1m",
        "price": 91358.1,
        "decision": "BUY",
        "confidence": 0.78,
        "signals": {"momentum": 0.6, "trend": 0.4, "volatility": 0.3},
        "model_version": "OmniQuantAI-v0.1",
        "approved": True,
        "position_size": 10.0,
        "decision_hash": "deadbeef123",
    }

    payload = build_ai_log_from_decision_record(
        order_id=702628302073888771,
        decision_record=example_decision_record,
        stage="Decision Making",
        model="OmniQuantAI-v0.1",
    )

    print("\n✅ Generated AI Log Payload:")
    print(json.dumps(payload, indent=2))
