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


class BuyAndHoldStrategy:
    """Baseline 1: passive benchmark. Enters once, then never trades again.

    target_weight defaults to 3% to match the other baselines' per-order size
    -- InstitutionalRiskEngine caps any single order at max_order_notional_pct
    (5% by default), so all five baselines must share a comparable weight to
    be a fair, identical-risk-budget comparison rather than one strategy
    simply being allowed a bigger position.
    """

    name = "buy_and_hold"

    def __init__(self, target_weight: Decimal = Decimal("0.03")) -> None:
        self.target_weight = target_weight
        self._entered = False

    def on_bar(
        self,
        bar: MarketBar,
        history: Sequence[MarketBar],
        regime: MarketRegime,
        portfolio: PortfolioSnapshot,
    ) -> Signal:
        if self._entered:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("1.0"), "Buy-and-hold: position already established")
        self._entered = True
        return Signal(bar.symbol, SignalAction.BUY, Decimal("1.0"), "Buy-and-hold: initial entry", self.target_weight)


class MovingAverageTrendStrategy:
    """Baseline 3: classic fast/slow moving-average crossover trend follower."""

    name = "ma_trend"

    def __init__(self, fast: int = 10, slow: int = 30, target_weight: Decimal = Decimal("0.03")) -> None:
        if fast >= slow:
            raise ValueError("fast lookback must be shorter than slow lookback")
        self.fast = fast
        self.slow = slow
        self.target_weight = target_weight

    def on_bar(
        self,
        bar: MarketBar,
        history: Sequence[MarketBar],
        regime: MarketRegime,
        portfolio: PortfolioSnapshot,
    ) -> Signal:
        if len(history) < self.slow:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.2"), "Insufficient history for moving average trend")
        fast_ma = sum((item.close for item in history[-self.fast :]), Decimal("0")) / Decimal(self.fast)
        slow_ma = sum((item.close for item in history[-self.slow :]), Decimal("0")) / Decimal(self.slow)
        if slow_ma == Decimal("0"):
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.2"), "Slow moving average is zero")
        spread = (fast_ma - slow_ma) / slow_ma
        if spread > Decimal("0.002"):
            return Signal(bar.symbol, SignalAction.BUY, min(Decimal("0.95"), abs(spread) * Decimal("50")), "Fast MA above slow MA", self.target_weight)
        if spread < Decimal("-0.002"):
            return Signal(bar.symbol, SignalAction.SELL, min(Decimal("0.95"), abs(spread) * Decimal("50")), "Fast MA below slow MA", -self.target_weight)
        return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), "Moving averages converged; no clear trend")


class VolatilityRegimeStrategy:
    """Baseline 5: trades trend direction only while realized volatility stays
    below a ceiling, sizing positions inversely to volatility and going flat
    the moment the volatility regime turns hostile."""

    name = "volatility_regime"

    def __init__(
        self,
        lookback: int = 14,
        vol_ceiling: Decimal = Decimal("0.03"),
        target_weight: Decimal = Decimal("0.03"),
    ) -> None:
        self.lookback = lookback
        self.vol_ceiling = vol_ceiling
        self.target_weight = target_weight

    def on_bar(
        self,
        bar: MarketBar,
        history: Sequence[MarketBar],
        regime: MarketRegime,
        portfolio: PortfolioSnapshot,
    ) -> Signal:
        if len(history) < self.lookback + 1:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.2"), "Insufficient history for volatility regime read")
        window = history[-self.lookback :]
        returns = [
            (window[index].close - window[index - 1].close) / window[index - 1].close
            for index in range(1, len(window))
            if window[index - 1].close != Decimal("0")
        ]
        if not returns:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.2"), "No usable return series")
        realized_vol = sum(abs(item) for item in returns) / Decimal(len(returns))
        if regime is MarketRegime.VOLATILE or realized_vol > self.vol_ceiling:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.6"), "Realized volatility above ceiling; staying flat for capital preservation")
        trend = (bar.close - window[0].close) / window[0].close
        vol_scalar = Decimal("1") - min(Decimal("1"), realized_vol / self.vol_ceiling)
        sized_weight = self.target_weight * vol_scalar
        if trend > Decimal("0.005"):
            return Signal(bar.symbol, SignalAction.BUY, min(Decimal("0.9"), abs(trend) * Decimal("20")), "Low-volatility uptrend; size scaled by inverse volatility", sized_weight)
        if trend < Decimal("-0.005"):
            return Signal(bar.symbol, SignalAction.SELL, min(Decimal("0.9"), abs(trend) * Decimal("20")), "Low-volatility downtrend; size scaled by inverse volatility", -sized_weight)
        return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), "No directional edge within acceptable volatility band")


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
