"""M1-follow-on: engineered features for the ML signal-generation pipeline.

Every hand-coded strategy tested today conditioned on ONE feature at a
time (momentum OR mean-deviation OR volatility OR channel position). Real
signal generation typically finds edge in how MULTIPLE features interact
-- e.g. "momentum only continues when volume confirms and volatility
isn't already elevated," a three-way interaction no univariate threshold
rule can express. This module computes a fixed, named feature vector per
bar so a model can learn those interactions instead of a human guessing
which one indicator to hand-code.

Every feature here is strictly causal: computed only from `history`,
which by convention (matching every strategy in this project) already
includes the current bar as its last element. No feature looks ahead.

Returns None when there isn't enough history for every feature to be
well-defined -- the caller should skip that bar rather than get a
partially-computed row.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

from omniquantai.domain.models import MarketBar

FEATURE_NAMES = [
    "return_1",
    "return_3",
    "return_7",
    "return_14",
    "return_30",
    "vol_7",
    "vol_14",
    "vol_30",
    "vol_ratio_short_long",
    "volume_zscore_14",
    "distance_from_mean_14",
    "distance_from_high_20",
    "distance_from_low_20",
    "rsi_14",
]

MIN_HISTORY = 31  # the longest lookback (return_30 / vol_30) needs 31 bars including current


def _returns(bars: Sequence[MarketBar]) -> list[float]:
    return [
        float((bars[index].close - bars[index - 1].close) / bars[index - 1].close)
        for index in range(1, len(bars))
        if bars[index - 1].close != Decimal("0")
    ]


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _rsi(returns: list[float]) -> float:
    if not returns:
        return 50.0
    gains = [r for r in returns if r > 0]
    losses = [-r for r in returns if r < 0]
    avg_gain = sum(gains) / len(returns)
    avg_loss = sum(losses) / len(returns)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_features(history: Sequence[MarketBar]) -> dict[str, float] | None:
    if len(history) < MIN_HISTORY:
        return None

    current = history[-1]
    if current.close == Decimal("0"):
        return None

    def return_over(n: int) -> float:
        anchor = history[-(n + 1)].close
        if anchor == Decimal("0"):
            return 0.0
        return float((current.close - anchor) / anchor)

    def realized_vol(n: int) -> float:
        window = history[-(n + 1) :]
        return _stdev(_returns(window))

    vol_7 = realized_vol(7)
    vol_14 = realized_vol(14)
    vol_30 = realized_vol(30)

    closes_14 = [float(bar.close) for bar in history[-14:]]
    mean_14 = sum(closes_14) / len(closes_14)
    distance_from_mean_14 = (float(current.close) - mean_14) / mean_14 if mean_14 else 0.0

    window_20 = history[-20:]
    high_20 = float(max(bar.high for bar in window_20))
    low_20 = float(min(bar.low for bar in window_20))
    distance_from_high_20 = (float(current.close) - high_20) / high_20 if high_20 else 0.0
    distance_from_low_20 = (float(current.close) - low_20) / low_20 if low_20 else 0.0

    volumes_14 = [float(bar.volume) for bar in history[-14:]]
    volume_mean = sum(volumes_14) / len(volumes_14)
    volume_std = _stdev(volumes_14) if len(volumes_14) > 1 else 0.0
    volume_zscore_14 = (float(current.volume) - volume_mean) / volume_std if volume_std else 0.0

    rsi_14 = _rsi(_returns(history[-15:]))

    return {
        "return_1": return_over(1),
        "return_3": return_over(3),
        "return_7": return_over(7),
        "return_14": return_over(14),
        "return_30": return_over(30),
        "vol_7": vol_7,
        "vol_14": vol_14,
        "vol_30": vol_30,
        "vol_ratio_short_long": (vol_7 / vol_30) if vol_30 else 1.0,
        "volume_zscore_14": volume_zscore_14,
        "distance_from_mean_14": distance_from_mean_14,
        "distance_from_high_20": distance_from_high_20,
        "distance_from_low_20": distance_from_low_20,
        "rsi_14": rsi_14,
    }


def label_forward_return(bars: Sequence[MarketBar], index: int, horizon: int, cost_threshold: float) -> int | None:
    """Three-class label for the bar at `index`: +1 if the forward return
    over `horizon` bars clears cost_threshold to the upside, -1 if it
    clears it to the downside, 0 if the move is too small to be worth
    trading net of costs -- "no trade" as a legitimate label, not an
    afterthought (Section 6). Returns None if there aren't `horizon` bars
    of future data available (only usable when building a TRAINING
    dataset from historical data; never available for a live decision).
    """
    if index + horizon >= len(bars):
        return None
    entry = bars[index].close
    exit_ = bars[index + horizon].close
    if entry == Decimal("0"):
        return None
    forward_return = float((exit_ - entry) / entry)
    if forward_return > cost_threshold:
        return 1
    if forward_return < -cost_threshold:
        return -1
    return 0
