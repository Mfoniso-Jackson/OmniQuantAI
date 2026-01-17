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

from typing import Dict, Any


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


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


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
            "score": 0.0,
            "signals": signals,
            "explanation": explain_decision(signals)
        }

    score = compute_score(signals)

    if score >= BUY_THRESHOLD:
        decision = "BUY"
        confidence = round(abs(score), 4)

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
# WEEX Adapter (Drop-in for run.py)
# ===============================

def signals_from_weex_ticker(ticker: Dict[str, Any]) -> Dict[str, float]:
    """
    Convert WEEX ticker snapshot -> normalized signals in [-1, 1].

    Example ticker keys you saw:
    {
      "last": "91358.1",
      "best_bid": "91358.0",
      "best_ask": "91358.1",
      "priceChangePercent": "0.017782",
      "volume_24h": "...",
      "markPrice": "...",
      "indexPrice": "..."
    }
    """

    change_24h = safe_float(ticker.get("priceChangePercent"), 0.0)
    best_ask = safe_float(ticker.get("best_ask") or ticker.get("bestAsk"), 0.0)
    best_bid = safe_float(ticker.get("best_bid") or ticker.get("bestBid"), 0.0)
    last = safe_float(ticker.get("last"), 0.0)

    # Momentum signal: map 24h % change into [-1, 1]
    # If +2% => ~ +1 (aggressive). Tune later.
    momentum = clamp(change_24h / 0.02)

    # Trend signal: for MVP, treat as momentum proxy
    trend = clamp(momentum * 0.9)

    # Volatility proxy: spread% as a liquidity/instability warning
    spread = abs(best_ask - best_bid) if best_ask and best_bid else 0.0
    spread_pct = (spread / last) if last else 0.0
    volatility = clamp(spread_pct * 200.0)  # scales tiny spreads into usable signal

    # Sentiment: placeholder (0 = neutral). You can replace later.
    sentiment = 0.0

    return {
        "momentum": momentum,
        "trend": trend,
        "volatility": volatility,
        "sentiment": sentiment
    }


def generate_decision(ticker: Dict[str, Any]) -> Dict[str, object]:
    """
    Run full pipeline:
    WEEX ticker -> signals -> make_decision()

    This is what your run.py should call.
    """
    signals = signals_from_weex_ticker(ticker)
    return make_decision(signals)


# ===============================
# Example Run (Safe for Testing)
# ===============================

if __name__ == "__main__":
    example_ticker = {
        "last": "91358.1",
        "best_bid": "91358.0",
        "best_ask": "91358.1",
        "priceChangePercent": "0.017782",
        "volume_24h": "2862623799.40485",
        "markPrice": "91364.6",
        "indexPrice": "91407.677",
    }

    decision = generate_decision(example_ticker)

    print("OmniQuantAI Decision Output")
    print("-" * 30)
    for k, v in decision.items():
        print(f"{k}: {v}")
