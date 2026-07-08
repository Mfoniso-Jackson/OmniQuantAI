from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from omniquantai.domain.models import MarketBar, MarketRegime, PortfolioSnapshot, Signal, SignalAction


class MomentumStrategy:
    name = "momentum"

    def __init__(self, lookback: int = 8, target_weight: Decimal = Decimal("0.03")) -> None:
        self.lookback = lookback
        self.target_weight = target_weight

    def on_bar(
        self,
        bar: MarketBar,
        history: Sequence[MarketBar],
        regime: MarketRegime,
        portfolio: PortfolioSnapshot,
    ) -> Signal:
        if len(history) < self.lookback:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.2"), "Insufficient history for momentum")
        anchor = history[-self.lookback].close
        momentum = (bar.close - anchor) / anchor
        if regime is MarketRegime.VOLATILE:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.4"), "Volatile regime suppresses momentum entry")
        if momentum > Decimal("0.01"):
            return Signal(bar.symbol, SignalAction.BUY, min(Decimal("0.95"), abs(momentum) * Decimal("10")), "Positive momentum breakout", self.target_weight)
        if momentum < Decimal("-0.01"):
            return Signal(bar.symbol, SignalAction.SELL, min(Decimal("0.95"), abs(momentum) * Decimal("10")), "Negative momentum reversal", -self.target_weight)
        return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), "Momentum is below action threshold")


class MeanReversionStrategy:
    name = "mean_reversion"

    def __init__(self, lookback: int = 10, target_weight: Decimal = Decimal("0.03")) -> None:
        self.lookback = lookback
        self.target_weight = target_weight

    def on_bar(
        self,
        bar: MarketBar,
        history: Sequence[MarketBar],
        regime: MarketRegime,
        portfolio: PortfolioSnapshot,
    ) -> Signal:
        if len(history) < self.lookback:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.2"), "Insufficient history for mean reversion")
        if regime is MarketRegime.TRENDING:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.4"), "Trending regime suppresses mean reversion")
        closes = [item.close for item in history[-self.lookback :]]
        mean = sum(closes) / Decimal(len(closes))
        deviation = (bar.close - mean) / mean
        if deviation < Decimal("-0.015"):
            return Signal(bar.symbol, SignalAction.BUY, min(Decimal("0.9"), abs(deviation) * Decimal("12")), "Price below rolling mean", self.target_weight)
        if deviation > Decimal("0.015"):
            return Signal(bar.symbol, SignalAction.SELL, min(Decimal("0.9"), abs(deviation) * Decimal("12")), "Price above rolling mean", -self.target_weight)
        return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), "Deviation is below action threshold")
