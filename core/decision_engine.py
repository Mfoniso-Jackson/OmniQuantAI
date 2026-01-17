"""
OmniQuantAI - Decision Engine
----------------------------
Purpose:
Convert multiple trading signals into a single, explainable trading decision.

Used for:
- WEEX AI Wars
- Live / paper trading
- Auditable AI decisions
"""

from typing import Dict


# ===============================
# Configuration
# ===============================

WEIGHTS = {
    "momentum": 0.35,
    "trend": 0.30,
    "volatility": -0.20,   # risk reducer
    "sentiment": 0.15
}

BUY_THRESHOLD = 0.30
SELL_THRESHOLD = -0.30
MAX_VOLATILITY = 0.80


# ===============================
# Utilities
# ===============================

def clamp(value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
    """Clamp a value to a fixed range."""
    return max(min(value, max_val), min_val)


def normalize_signals(signals: Dict[str, float]) -> Dict[str, float]:
    """Ensure all signals are within expected bounds."""
    return {k: clamp(v) for k, v in signals.items()}


# ===============================
# Risk Management
# ===============================

def risk_check(signals: Dict[str, float]) -> bool:
    """
    Block trades in hostile market conditions.
    """
    if signals.get("volatility", 0) > MAX_VOLATILITY:
        return False
    return True


# ===============================
# Scoring Logic
# ===============================

def compute_score(signals: Dict[str, float]) -> float:
    """
    Compute weighted decision score.
    """
    score = 0.0
    for name, value in signals.items():
        score += WEIGHTS.get(name, 0.0) * value
    return score


def explain_decision(signals: Dict[str, float]) -> Dict[str, float]:
    """
    Return per-signal contribution for transparency.
    """
    return {
        name: round(value * WEIGHTS.get(name, 0.0), 4)
        for name, value in signals.items()
    }


# ===============================
# Decision Engine
# ===============================

def make_decision(raw_signals: Dict[str, float]) -> Dict[str, object]:
    """
    Main decision function.
    """

    signals = normalize_signals(raw_signals)

    if not risk_check(signals):
        return {
            "decision": "HOLD",
            "confidence": 0.0,
            "reason": "High volatility regime",
            "signals": signals,
            "explanation": explain_decision(signals)
        }

    score = compute_score(signals)

    if score >= BUY_THRESHOLD:
        decision = "BUY"
        confidence = round(score, 4)

    elif score <= SELL_THRESHOLD:
        decision = "SELL"
        confidence = round(abs(score), 4)

    else:
        decision = "HOLD"
        confidence = round(abs(score), 4)

    return {
        "decision": decision,
        "confidence": confidence,
        "score": round(score, 4),
        "signals": signals,
        "explanation": explain_decision(signals)
    }


# ===============================
# Example Run (Safe for Testing)
# ===============================

if __name__ == "__main__":
    example_signals = {
        "momentum": 0.6,
        "trend": 0.4,
        "volatility": 0.3,
        "sentiment": 0.5
    }

    decision = make_decision(example_signals)

    print("OmniQuantAI Decision Output")
    print("-" * 30)
    for k, v in decision.items():
        print(f"{k}: {v}")
