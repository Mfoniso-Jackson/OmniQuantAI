from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from omniquantai.domain.models import MarketBar, MarketRegime


class SimpleRegimeDetector:
    def __init__(self, lookback: int = 12, volatility_threshold: Decimal = Decimal("0.03")) -> None:
        self.lookback = lookback
        self.volatility_threshold = volatility_threshold

    def detect(self, history: Sequence[MarketBar]) -> MarketRegime:
        if len(history) < max(3, self.lookback):
            return MarketRegime.UNKNOWN

        window = history[-self.lookback :]
        returns = [
            (window[index].close - window[index - 1].close) / window[index - 1].close
            for index in range(1, len(window))
            if window[index - 1].close != Decimal("0")
        ]
        if not returns:
            return MarketRegime.UNKNOWN

        avg_abs_return = sum(abs(item) for item in returns) / Decimal(len(returns))
        trend = (window[-1].close - window[0].close) / window[0].close
        if avg_abs_return > self.volatility_threshold:
            return MarketRegime.VOLATILE
        if abs(trend) > avg_abs_return * Decimal("3"):
            return MarketRegime.TRENDING
        return MarketRegime.RANGING

