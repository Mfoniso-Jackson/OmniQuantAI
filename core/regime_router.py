"""
BTC Regime Router (WEEX AI Wars)
--------------------------------
Purpose:
Classify BTC market regime (TRENDING / CHOP / BREAKOUT / HIGH_VOL)
and return a config that adjusts trading aggressiveness.

Tuned to:
- trade LESS during chop
- trade MORE during clean momentum days
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any
import numpy as np
import pandas as pd


# =========================
# CONFIG (BTC-TUNED)
# =========================

SYMBOL_DEFAULT = "cmt_btcusdt"

ADX_PERIOD = 14
ATR_PERIOD = 14

# Trend thresholds
ADX_TREND_ON = 22.0
ADX_CHOP = 18.0

# Volatility thresholds (ATR as % of price)
ATR_PCT_LOW = 0.90     # < 0.90% = low vol chop zone (often noisy)
ATR_PCT_MED_HI = 1.40  # upper band for "tradable breakout"
ATR_PCT_DANGER_1 = 1.20
ATR_PCT_DANGER_2 = 1.80

# Slope threshold (EMA20 slope per candle, percent)
EMA20_SLOPE_MIN_PCT = 0.03  # prevents fake trend flips


# =========================
# OUTPUT SCHEMA
# =========================

@dataclass
class RegimeResult:
    symbol: str
    regime: str
    config: Dict[str, Any]
    features: Dict[str, float]
    debug: Dict[str, Any]


# =========================
# INDICATORS
# =========================

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = _true_range(high, low, close)
    return tr.rolling(period).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Classic ADX implementation.
    Returns ADX series.
    """
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = _true_range(high, low, close)
    atr = tr.rolling(period).mean()

    plus_di = 100 * pd.Series(plus_dm, index=high.index).rolling(period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).rolling(period).mean() / atr

    dx = (100 * (
