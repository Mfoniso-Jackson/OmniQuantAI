from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from omniquantai.application.protocols import Strategy
from omniquantai.domain.models import MarketBar, MarketRegime, PortfolioSnapshot, Signal, SignalAction


class EVSizedStrategy:
    """M4: expected-value-driven position sizing (Section 6).

    Wraps a strategy and scales its target_weight by a fractional-Kelly
    estimate from that strategy's OWN recent, causally-realized win rate
    and payoff ratio -- literally sizing bigger when the edge has been
    working and smaller (or not trading at all) when it hasn't, instead
    of the fixed weight every strategy in this project has used so far
    regardless of recent form.

    Kelly fraction: f* = win_rate - (1 - win_rate) / payoff_ratio, where
    payoff_ratio = average win / average loss. A negative f* means the
    strategy's own recent trades have net-negative expectancy -- Section
    6's "should we trade at all?" answered "no," so the signal is
    suppressed entirely rather than merely downsized.

    Deliberately simple (Rule 9): a rolling lookup of realized outcomes,
    not a fitted model. Realized PnL is observed from the portfolio
    snapshot's cumulative realized_pnl each bar (a delta since the last
    bar means a trade closed) rather than requiring any change to the
    engine or protocols -- the same non-invasive wrapper pattern as
    RegimeSelectorStrategy.

    Cold start: below min_samples closed trades (fresh at the start of
    every walk-forward phase, by design -- no stats carry across a
    TRAIN/VALIDATION/TEST boundary), sizing multiplier is 1.0, i.e. the
    wrapped strategy's own fixed sizing, unchanged.
    """

    def __init__(
        self,
        inner: Strategy,
        window: int = 20,
        min_samples: int = 10,
        kelly_ceiling: Decimal = Decimal("0.3"),
        min_size_multiplier: Decimal = Decimal("0.25"),
        max_size_multiplier: Decimal = Decimal("1.5"),
    ) -> None:
        self.inner = inner
        self.window = window
        self.min_samples = min_samples
        self.kelly_ceiling = kelly_ceiling
        self.min_size_multiplier = min_size_multiplier
        self.max_size_multiplier = max_size_multiplier
        self.name = f"ev_sized_{inner.name}"
        self._closed_trade_pnls: list[Decimal] = []
        self._last_realized_pnl: Decimal | None = None

    def _observe_realized_pnl(self, portfolio: PortfolioSnapshot) -> None:
        if self._last_realized_pnl is None:
            self._last_realized_pnl = portfolio.realized_pnl
            return
        delta = portfolio.realized_pnl - self._last_realized_pnl
        if delta != Decimal("0"):
            self._closed_trade_pnls.append(delta)
            if len(self._closed_trade_pnls) > self.window:
                self._closed_trade_pnls.pop(0)
        self._last_realized_pnl = portfolio.realized_pnl

    def _kelly_fraction(self) -> Decimal | None:
        if len(self._closed_trade_pnls) < self.min_samples:
            return None
        wins = [pnl for pnl in self._closed_trade_pnls if pnl > Decimal("0")]
        losses = [pnl for pnl in self._closed_trade_pnls if pnl < Decimal("0")]
        if not wins or not losses:
            return None
        win_rate = Decimal(len(wins)) / Decimal(len(self._closed_trade_pnls))
        avg_win = sum(wins, Decimal("0")) / Decimal(len(wins))
        avg_loss = abs(sum(losses, Decimal("0")) / Decimal(len(losses)))
        if avg_loss == Decimal("0"):
            return None
        payoff_ratio = avg_win / avg_loss
        return win_rate - (Decimal("1") - win_rate) / payoff_ratio

    def _size_multiplier(self) -> Decimal | None:
        """Returns None if the trade should be suppressed entirely."""
        kelly = self._kelly_fraction()
        if kelly is None:
            return Decimal("1")  # not enough data yet -- use the wrapped strategy's own sizing
        if kelly <= Decimal("0"):
            return None  # recent realized edge is non-positive -- Section 6's "no trade"
        clamped = min(kelly, self.kelly_ceiling)
        span = self.max_size_multiplier - self.min_size_multiplier
        return self.min_size_multiplier + (clamped / self.kelly_ceiling) * span

    def on_bar(
        self,
        bar: MarketBar,
        history: Sequence[MarketBar],
        regime: MarketRegime,
        portfolio: PortfolioSnapshot,
    ) -> Signal:
        self._observe_realized_pnl(portfolio)
        signal = self.inner.on_bar(bar, history, regime, portfolio)
        if signal.action is SignalAction.HOLD:
            return signal

        multiplier = self._size_multiplier()
        if multiplier is None:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), f"EV-suppressed: recent realized edge is non-positive ({signal.reason})")

        return Signal(
            bar.symbol,
            signal.action,
            signal.confidence,
            f"{signal.reason} (EV size x{multiplier:.2f})",
            signal.target_weight * multiplier,
        )
