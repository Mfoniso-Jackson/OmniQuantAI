"""
OmniQuantAI - Regime Router
---------------------------
Classifies a WEEX ticker snapshot into a simple, explainable market
regime and returns a strategy profile for the decision engine.

This module is intentionally dependency-light so the live runner can boot
even when research indicators are unavailable.
"""

from __future__ import annotations

from typing import Any, Dict


DEFAULT_PROFILE: Dict[str, Any] = {
    "name": "balanced",
    "buy_threshold": 0.30,
    "sell_threshold": -0.30,
    "max_volatility": 0.80,
    "weights": {
        "momentum": 0.35,
        "trend": 0.30,
        "volatility": -0.20,
        "sentiment": 0.15,
    },
}

CHOP_PROFILE: Dict[str, Any] = {
    **DEFAULT_PROFILE,
    "name": "capital_preservation_chop",
    "buy_threshold": 0.45,
    "sell_threshold": -0.45,
    "max_volatility": 0.55,
}

TREND_PROFILE: Dict[str, Any] = {
    **DEFAULT_PROFILE,
    "name": "trend_following",
    "buy_threshold": 0.25,
    "sell_threshold": -0.25,
    "max_volatility": 0.90,
}

HIGH_VOL_PROFILE: Dict[str, Any] = {
    **DEFAULT_PROFILE,
    "name": "high_volatility_defensive",
    "buy_threshold": 0.60,
    "sell_threshold": -0.60,
    "max_volatility": 0.35,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    return max(min(value, maximum), minimum)


def route_regime(ticker: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(ticker.get("symbol") or "cmt_btcusdt")
    last = _safe_float(ticker.get("last"))
    best_bid = _safe_float(ticker.get("best_bid") or ticker.get("bestBid"))
    best_ask = _safe_float(ticker.get("best_ask") or ticker.get("bestAsk"))
    change_24h = _safe_float(ticker.get("priceChangePercent"))

    spread = abs(best_ask - best_bid) if best_ask and best_bid else 0.0
    spread_pct = spread / last if last else 0.0

    trend_score = _clamp(change_24h / 0.02)
    vol_score = _clamp(spread_pct * 200.0, 0.0, 1.0)
    chop_score = _clamp(1.0 - abs(trend_score) - vol_score, 0.0, 1.0)

    if vol_score >= 0.70:
        regime = "HIGH_VOLATILITY"
        profile = HIGH_VOL_PROFILE
        why = "Spread-derived volatility is elevated, so execution is defensive."
    elif abs(trend_score) >= 0.50:
        regime = "TRENDING"
        profile = TREND_PROFILE
        why = "24h price change indicates directional momentum."
    else:
        regime = "RANGING"
        profile = CHOP_PROFILE
        why = "Momentum is weak and volatility is contained."

    confidence = max(abs(trend_score), vol_score, chop_score)
    signals = {
        "momentum": trend_score,
        "trend": _clamp(trend_score * 0.9),
        "volatility": vol_score,
        "sentiment": 0.0,
    }

    return {
        "symbol": symbol,
        "regime": regime,
        "confidence": round(confidence, 4),
        "trend_score": round(trend_score, 4),
        "chop_score": round(chop_score, 4),
        "vol_score": round(vol_score, 4),
        "signals": signals,
        "profile": profile,
        "thresholds": {
            "trend_abs": 0.50,
            "high_volatility": 0.70,
        },
        "why": why,
    }


def route(ticker: Dict[str, Any]) -> Dict[str, Any]:
    return route_regime(ticker)

