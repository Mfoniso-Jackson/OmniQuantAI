"""
OmniQuantAI - Risk Engine
------------------------
Purpose:
Enforce capital preservation rules before any order is sent.

Used for:
- WEEX AI Wars
- Live / paper trading
- Deterministic risk control
"""

from typing import Dict


# ===============================
# Risk Parameters
# ===============================

MAX_RISK_PER_TRADE = 0.01      # 1% of equity
MAX_POSITION_SIZE = 0.20      # 20% of equity
MAX_DAILY_DRAWDOWN = 0.05     # 5%
MIN_CONFIDENCE = 0.20         # ignore weak signals


# ===============================
# Risk State (in-memory MVP)
# ===============================

risk_state = {
    "daily_pnl": 0.0,
    "open_exposure": 0.0
}


# ===============================
# Utilities
# ===============================

def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min(value, max_val), min_val)


# ===============================
# Core Risk Checks
# ===============================

def check_drawdown() -> bool:
    """
    Block trading if daily drawdown breached.
    """
    return abs(risk_state["daily_pnl"]) < MAX_DAILY_DRAWDOWN


def check_confidence(confidence: float) -> bool:
    """
    Ensure decision confidence is meaningful.
    """
    return confidence >= MIN_CONFIDENCE


def check_exposure(equity: float, new_position_size: float) -> bool:
    """
    Prevent over-leveraging.
    """
    max_allowed = equity * MAX_POSITION_SIZE
    return (risk_state["open_exposure"] + new_position_size) <= max_allowed


# ===============================
# Position Sizing
# ===============================

def calculate_position_size(
    equity: float,
    confidence: float
) -> float:
    """
    Dynamic position sizing based on confidence.
    """
    base_risk = equity * MAX_RISK_PER_TRADE
    size = base_risk * clamp(confidence, 0.0, 1.0)
    return round(size, 2)


# ===============================
# Risk Gatekeeper
# ===============================

def approve_trade(
    decision_payload: Dict[str, object],
    equity: float
) -> Dict[str, object]:
    """
    Final risk approval before execution.
    """

    decision = decision_payload.get("decision")
    confidence = decision_payload.get("confidence", 0.0)

    if decision == "HOLD":
        return {"approved": False, "reason": "No trade decision"}

    if not check_confidence(confidence):
        return {"approved": False, "reason": "Low confidence signal"}

    if not check_drawdown():
        return {"approved": False, "reason": "Daily drawdown limit breached"}

    position_size = calculate_position_size(equity, confidence)

    if not check_exposure(equity, position_size):
        return {"approved": False, "reason": "Exposure limit exceeded"}

    return {
        "approved": True,
        "decision": decision,
        "position_size": position_size,
        "confidence": confidence
    }


# ===============================
# State Updates (MVP)
# ===============================

def update_after_trade(pnl: float, position_size: float):
    """
    Update risk state after trade closes.
    """
    risk_state["daily_pnl"] += pnl
    risk_state["open_exposure"] -= position_size
    risk_state["open_exposure"] = max(risk_state["open_exposure"], 0.0)


def register_open_trade(position_size: float):
    """
    Track open exposure.
    """
    risk_state["open_exposure"] += position_size


# ===============================
# Example Run
# ===============================

if __name__ == "__main__":
    mock_decision = {
        "decision": "BUY",
        "confidence": 0.55
    }

    equity = 1000.0

    approval = approve_trade(mock_decision, equity)

    print("OmniQuantAI Risk Engine Output")
    print("-" * 30)
    for k, v in approval.items():
        print(f"{k}: {v}")
