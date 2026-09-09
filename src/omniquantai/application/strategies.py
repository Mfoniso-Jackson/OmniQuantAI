from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from omniquantai.application.protocols import Strategy
from omniquantai.domain.models import MarketBar, MarketRegime, PortfolioSnapshot, Signal, SignalAction


class RegimeSelectorStrategy:
    """Section 9 minimal strategy-selection agent: routes each bar to exactly
    one sub-strategy keyed by the detected regime. A regime with no assigned
    strategy stays flat rather than silently falling back to some default --
    "no trade" must be a reachable outcome, not just an accident of gaps."""

    def __init__(self, regime_map: dict[MarketRegime, Strategy], name: str = "regime_selector") -> None:
        self.regime_map = regime_map
        self.name = name

    def on_bar(
        self,
        bar: MarketBar,
        history: Sequence[MarketBar],
        regime: MarketRegime,
        portfolio: PortfolioSnapshot,
    ) -> Signal:
        strategy = self.regime_map.get(regime)
        if strategy is None:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), f"No strategy assigned to {regime.value} regime; staying flat")
        return strategy.on_bar(bar, history, regime, portfolio)


def gate_to_regimes(strategy: Strategy, allowed_regimes: frozenset[MarketRegime], name: str | None = None) -> RegimeSelectorStrategy:
    """Convenience constructor: run `strategy` only in the given regimes, flat otherwise."""
    return RegimeSelectorStrategy({regime: strategy for regime in allowed_regimes}, name=name or f"{strategy.name}_gated")


class MomentumStrategy:
    name = "momentum"

    def __init__(
        self,
        lookback: int = 8,
        threshold: Decimal = Decimal("0.01"),
        target_weight: Decimal = Decimal("0.03"),
    ) -> None:
        self.lookback = lookback
        self.threshold = threshold
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
        if momentum > self.threshold:
            return Signal(bar.symbol, SignalAction.BUY, min(Decimal("0.95"), abs(momentum) * Decimal("10")), "Positive momentum breakout", self.target_weight)
        if momentum < -self.threshold:
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

    def __init__(
        self,
        lookback: int = 10,
        threshold: Decimal = Decimal("0.015"),
        target_weight: Decimal = Decimal("0.03"),
    ) -> None:
        self.lookback = lookback
        self.threshold = threshold
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
        if deviation < -self.threshold:
            return Signal(bar.symbol, SignalAction.BUY, min(Decimal("0.9"), abs(deviation) * Decimal("12")), "Price below rolling mean", self.target_weight)
        if deviation > self.threshold:
            return Signal(bar.symbol, SignalAction.SELL, min(Decimal("0.9"), abs(deviation) * Decimal("12")), "Price above rolling mean", -self.target_weight)
        return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), "Deviation is below action threshold")


class BreakoutStrategy:
    """M3 addition: enters on a genuine N-period channel breakout, with a
    confirmation buffer so a bar that merely ties the recent extreme
    doesn't trigger noise trades."""

    name = "breakout"

    def __init__(
        self,
        lookback: int = 20,
        confirmation: Decimal = Decimal("0.005"),
        target_weight: Decimal = Decimal("0.03"),
    ) -> None:
        self.lookback = lookback
        self.confirmation = confirmation
        self.target_weight = target_weight

    def on_bar(
        self,
        bar: MarketBar,
        history: Sequence[MarketBar],
        regime: MarketRegime,
        portfolio: PortfolioSnapshot,
    ) -> Signal:
        # `history` already includes the current bar (the engine appends
        # before calling strategies) -- the channel must be built from
        # PRIOR bars only, or today's own high/low always sets the
        # channel bound and a breakout can never register on exactly the
        # day it should.
        prior_history = history[:-1]
        if len(prior_history) < self.lookback:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.2"), "Insufficient history for breakout")
        window = prior_history[-self.lookback :]
        highest = max(item.high for item in window)
        lowest = min(item.low for item in window)
        if highest == Decimal("0"):
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.2"), "Channel high is zero")
        upper_trigger = highest * (Decimal("1") + self.confirmation)
        lower_trigger = lowest * (Decimal("1") - self.confirmation)
        if bar.close > upper_trigger:
            breakout_size = (bar.close - highest) / highest
            return Signal(bar.symbol, SignalAction.BUY, min(Decimal("0.95"), breakout_size * Decimal("30")), "Confirmed breakout above N-period high", self.target_weight)
        if bar.close < lower_trigger:
            breakout_size = (lowest - bar.close) / lowest
            return Signal(bar.symbol, SignalAction.SELL, min(Decimal("0.95"), breakout_size * Decimal("30")), "Confirmed breakdown below N-period low", -self.target_weight)
        return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), "Price inside the established channel")


class VolatilityExpansionStrategy:
    """M3 addition: the mirror image of VolatilityRegimeStrategy. That
    strategy trades trend direction only while volatility stays
    contracted; this one waits for a volatility squeeze (short-term
    realized vol well below its own longer baseline) and then trades the
    breakout direction the moment short-term vol expands past the
    baseline again -- a classic squeeze-then-expand setup, distinct from
    trading during calm conditions."""

    name = "volatility_expansion"

    def __init__(
        self,
        short_lookback: int = 5,
        baseline_lookback: int = 20,
        expansion_ratio: Decimal = Decimal("1.5"),
        squeeze_ratio: Decimal = Decimal("0.7"),
        target_weight: Decimal = Decimal("0.03"),
    ) -> None:
        if short_lookback >= baseline_lookback:
            raise ValueError("short_lookback must be shorter than baseline_lookback")
        self.short_lookback = short_lookback
        self.baseline_lookback = baseline_lookback
        self.expansion_ratio = expansion_ratio
        self.squeeze_ratio = squeeze_ratio
        self.target_weight = target_weight

    @staticmethod
    def _realized_vol(bars: Sequence[MarketBar]) -> Decimal:
        returns = [
            abs((bars[index].close - bars[index - 1].close) / bars[index - 1].close)
            for index in range(1, len(bars))
            if bars[index - 1].close != Decimal("0")
        ]
        if not returns:
            return Decimal("0")
        return sum(returns) / Decimal(len(returns))

    def on_bar(
        self,
        bar: MarketBar,
        history: Sequence[MarketBar],
        regime: MarketRegime,
        portfolio: PortfolioSnapshot,
    ) -> Signal:
        if len(history) < self.baseline_lookback + 1:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.2"), "Insufficient history for volatility expansion read")
        baseline_window = history[-self.baseline_lookback :]
        short_window = history[-self.short_lookback :]
        prior_short_window = history[-(self.short_lookback + 1) : -1]

        baseline_vol = self._realized_vol(baseline_window)
        short_vol = self._realized_vol(short_window)
        prior_short_vol = self._realized_vol(prior_short_window)
        if baseline_vol == Decimal("0"):
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.2"), "No usable baseline volatility")

        was_squeezed = prior_short_vol < baseline_vol * self.squeeze_ratio
        now_expanding = short_vol > baseline_vol * self.expansion_ratio
        if not (was_squeezed and now_expanding):
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), "No squeeze-then-expand setup present")

        trend = (bar.close - short_window[0].close) / short_window[0].close
        confidence = min(Decimal("0.95"), (short_vol / baseline_vol) * Decimal("0.5"))
        if trend > Decimal("0"):
            return Signal(bar.symbol, SignalAction.BUY, confidence, "Volatility squeeze released to the upside", self.target_weight)
        if trend < Decimal("0"):
            return Signal(bar.symbol, SignalAction.SELL, confidence, "Volatility squeeze released to the downside", -self.target_weight)
        return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), "Volatility expanded but direction is unclear")
