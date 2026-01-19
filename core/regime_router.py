"""
regime_router.py
----------------
Purpose:
Detect market regime and select a strategy profile for decision_engine.

Regimes:
- TRENDING
- RANGING
- HIGH_VOL

This is deliberately lightweight + stable for Day-1 live trading.
"""

from typing import Dict, Any
import math


def safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# -----------------------------
# Strategy Profiles
# -----------------------------
# These profiles change how aggressive the engine is.

PROFILES = {
    "TREND_FOLLOW": {
        "weights": {"momentum": 0.45, "trend": 0.35, "volatility": -0.20, "sentiment": 0.00},
        "buy_threshold": 0.28,
        "sell_threshold": -0.28,
        "max_volatility": 0.85,
    },
    "MEAN_REVERT": {
        "weights": {"momentum": 0.20, "trend": 0.15, "volatility": -0.35, "sentiment": 0.30},
        "buy_threshold": 0.35,
        "sell_threshold": -0.35,
        "max_volatility": 0.70,
    },
    "DEFENSIVE": {
        "weights": {"momentum": 0.30, "trend": 0.25, "volatility": -0.45, "sentiment": 0.00},
        "buy_threshold": 0.45,
        "sell_threshold": -0.45,
        "max_volatility": 0.55,
    },
}


# -----------------------------
# Regime Detection
# -----------------------------

def detect_regime_from_ticker(ticker: Dict[str, Any]) -> Dict[str, Any]:
    """
    Uses only ticker fields that you already have working on WEEX.

    Inputs (WEEX ticker you already saw):
    - last
    - best_ask / best_bid
    - priceChangePercent

    Outputs:
    - regime: TRENDING / RANGING / HIGH_VOL
    - metrics: {change_24h, spread_pct, abs_change_24h}
    """

    last = safe_float(ticker.get("last"), 0.0)
    best_ask = safe_float(ticker.get("best_ask") or ticker.get("bestAsk"), last)
    best_bid = safe_float(ticker.get("best_bid") or ticker.get("bestBid"), last)
    change_24h = safe_float(ticker.get("priceChangePercent"), 0.0)

    spread = abs(best_ask - best_bid) if best_ask and best_bid else 0.0
    spread_pct = (spread / last) if last else 0.0

    abs_change = abs(change_24h)

    # Heuristics (tunable):
    # - HIGH_VOL: large 24h move OR poor liquidity/spread
    # - TRENDING: clear move but not insane
    # - RANGING: small move + decent spread
    if abs_change >= 0.03 or spread_pct >= 0.00030:
        regime = "HIGH_VOL"
    elif abs_change >= 0.012:
        regime = "TRENDING"
    else:
        regime = "RANGING"

    return {
        "regime": regime,
        "metrics": {
            "change_24h": change_24h,
            "abs_change_24h": abs_change,
            "spread_pct": spread_pct,
        },
    }


def select_profile(regime: str) -> Dict[str, Any]:
    """
    Choose strategy profile based on regime.
    """
    if regime == "TRENDING":
        return {"name": "TREND_FOLLOW", **PROFILES["TREND_FOLLOW"]}
    elif regime == "RANGING":
        return {"name": "MEAN_REVERT", **PROFILES["MEAN_REVERT"]}
    else:
        return {"name": "DEFENSIVE", **PROFILES["DEFENSIVE"]}


def route(ticker: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main router function.
    Returns:
    {
      "regime": ...,
      "profile": {...},
      "metrics": {...}
    }
    """
    info = detect_regime_from_ticker(ticker)
    profile = select_profile(info["regime"])

    return {
        "regime": info["regime"],
        "profile": profile,
        "metrics": info["metrics"],
    }
