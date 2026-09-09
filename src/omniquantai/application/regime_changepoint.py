from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

from omniquantai.domain.models import MarketBar, MarketRegime


class ChangePointRegimeDetector:
    """Two-sided CUSUM change-point detector (Section 8).

    SimpleRegimeDetector classifies the whole lookback window by comparing
    average absolute return to a fixed volatility threshold -- it never
    asks *when* the market's behavior actually shifted, just what the
    window looks like in aggregate. This detector runs a standard CUSUM
    test over standardized returns to find the most recent genuine change
    point in the window; only a change point in the recent portion of the
    window is classified (as TRENDING if the post-change segment shows a
    consistent directional drift, VOLATILE if it shows elevated dispersion
    instead). No recent change point means RANGING -- the market's
    statistics haven't shifted, whatever the absolute level of noise is.
    """

    def __init__(
        self,
        lookback: int = 30,
        drift_allowance: float = 0.5,
        decision_threshold: float = 4.0,
    ) -> None:
        self.lookback = lookback
        self.drift_allowance = drift_allowance
        self.decision_threshold = decision_threshold

    def detect(self, history: Sequence[MarketBar]) -> MarketRegime:
        if len(history) < max(10, self.lookback):
            return MarketRegime.UNKNOWN

        window = history[-self.lookback :]
        returns = [
            float((window[index].close - window[index - 1].close) / window[index - 1].close)
            for index in range(1, len(window))
            if window[index - 1].close != Decimal("0")
        ]
        if len(returns) < 8:
            return MarketRegime.UNKNOWN

        mean_return = sum(returns) / len(returns)
        variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
        sigma = math.sqrt(variance)
        if sigma == 0:
            return MarketRegime.RANGING

        k = self.drift_allowance * sigma
        threshold = self.decision_threshold * sigma
        s_pos = 0.0
        s_neg = 0.0
        change_point_index: int | None = None

        for index, value in enumerate(returns):
            deviation = value - mean_return
            s_pos = max(0.0, s_pos + deviation - k)
            s_neg = min(0.0, s_neg + deviation + k)
            if s_pos > threshold or s_neg < -threshold:
                change_point_index = index
                s_pos = 0.0
                s_neg = 0.0

        recent_boundary = len(returns) - max(3, len(returns) // 3)
        if change_point_index is None or change_point_index < recent_boundary:
            return MarketRegime.RANGING

        post_change = returns[change_point_index:]
        post_mean = sum(post_change) / len(post_change)
        post_variance = sum((value - post_mean) ** 2 for value in post_change) / len(post_change)
        post_sigma = math.sqrt(post_variance)

        if post_sigma > sigma * 1.5:
            return MarketRegime.VOLATILE
        if abs(post_mean) > post_sigma:
            return MarketRegime.TRENDING
        return MarketRegime.RANGING
