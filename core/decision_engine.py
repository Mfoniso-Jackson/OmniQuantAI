"""
OmniQuantAI - Decision Engine (Regime Routed)
--------------------------------------------
ticker -> regime_router -> signals -> decision

Used for:
- WEEX AI Wars live trading
- Auditable AI decisions + explainability
"""

from typing import Dict, Any

from regime_router import route


# ===============================
# Utilities
# ===============================

def clamp(value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
    return max(min(value, max_val), min_val)


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def normalize_signals(signals: Dict[str, float]) -> Dict[str, float]:
    return {k: clamp(v) for k, v in signals.items()}


# ===============================
# Scoring + Explainability
# ===============================

def compute_score(signals: Dict[str, float], weights: Dict[str, float]) -> float:
    score = 0.0
    for name, value in signals.items():
        score += weights.get(name, 0.0) * value
    return score


def explain_decision(signals: Dict[str, float], weights: Dict[str, float]) -> Dict[str, float]:
    return {name: round(value * weights.get(name, 0.0), 4) for name, value in signals.items()}


# ===============================
# Signal Extraction from WEEX ticker
# ===============================

def signals_from_weex_ticker(ticker: Dict[str, Any]) -> Dict[str, float]:
    change_24h = safe_float(ticker.get("priceChangePercent"), 0.0)
    best_ask = safe_float(ticker.get("best_ask") or ticker.get("bestAsk"), 0.0)
    best_bid = safe_float(ticker.get("best_bid") or ticker.get("bestBid"), 0.0)
    last = safe_float(ticker.get("last"), 0.0)

    # Momentum signal: map 24h change into [-1,1]
    momentum = clamp(change_24h / 0.02)

    # Trend signal: proxy as smoothed momentum
    trend = clamp(momentum * 0.9)

    # Volatility proxy: spread % scaled up
    spread = abs(best_ask - best_bid) if best_ask and best_bid else 0.0
    spread_pct = (spread / last) if last else 0.0
    volatility = clamp(spread_pct * 200.0)

    # Sentiment placeholder (0 for MVP)
    sentiment = 0.0

    return {
        "momentum": momentum,
        "trend": trend,
        "volatility": volatility,
        "sentiment": sentiment,
    }


# ===============================
# Decision Engine (Regime-aware)
# ===============================

def make_decision(raw_signals: Dict[str, float], profile: Dict[str, Any]) -> Dict[str, object]:
    signals = normalize_signals(raw_signals)

    weights = profile["weights"]
    buy_th = float(profile["buy_threshold"])
    sell_th = float(profile["sell_threshold"])
    max_vol = float(profile["max_volatility"])

    # Regime risk gate
    if signals.get("volatility", 0.0) > max_vol:
        return {
            "decision": "HOLD",
            "confidence": 0.0,
            "reason": f"Volatility gate (vol>{max_vol})",
            "score": 0.0,
            "signals": signals,
            "explanation": explain_decision(signals, weights),
        }

    score = compute_score(signals, weights)

    if score >= buy_th:
        return {
            "decision": "BUY",
            "confidence": round(abs(score), 4),
            "score": round(score, 4),
            "signals": signals,
            "explanation": explain_decision(signals, weights),
        }

    if score <= sell_th:
        return {
            "decision": "SELL",
            "confidence": round(abs(score), 4),
            "score": round(score, 4),
            "signals": signals,
            "explanation": explain_decision(signals, weights),
        }

    return {
        "decision": "HOLD",
        "confidence": round(abs(score), 4),
        "score": round(score, 4),
        "signals": signals,
        "explanation": explain_decision(signals, weights),
    }


def generate_decision(ticker: Dict[str, Any]) -> Dict[str, object]:
    """
    Full pipeline:
    ticker -> regime_router -> signals -> decision
    """
    routing = route(ticker)
    profile = routing["profile"]

    signals = signals_from_weex_ticker(ticker)
    out = make_decision(signals, profile)

    # Attach regime metadata for AI log transparency + judges
    out["regime"] = routing["regime"]
    out["strategy_profile"] = profile["name"]
    out["router_metrics"] = routing["metrics"]

    return out


# ===============================
# Local test
# ===============================

if __name__ == "__main__":
    example_ticker = {
        "last": "91358.1",
        "best_bid": "91358.0",
        "best_ask": "91358.1",
        "priceChangePercent": "0.017782",
    }

    decision = generate_decision(example_ticker)
    print(decision)
