from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

from omniquantai.application.position_manager import PositionManager
from omniquantai.application.protocols import RiskEngine, Strategy
from omniquantai.domain.models import MarketBar, MarketRegime, Order, PortfolioSnapshot, Signal, SignalAction


class SymbolRoutedStrategy:
    """M5 portfolio layer: dispatches each bar to whichever strategy is
    assigned to that bar's symbol, so a single engine run can trade
    several assets with different strategies simultaneously against one
    shared cash/risk pool -- BNBUSDT gets its dedicated hand-validated
    signal, other assets get the pooled ML model, rather than either
    strategy seeing bars it was never meant to trade."""

    name = "symbol_routed"

    def __init__(self, routes: dict[str, Strategy]) -> None:
        self.routes = routes

    def on_bar(self, bar: MarketBar, history: Sequence[MarketBar], regime: MarketRegime, portfolio: PortfolioSnapshot) -> Signal:
        strategy = self.routes.get(bar.symbol)
        if strategy is None:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), f"No strategy routed for {bar.symbol}")
        return strategy.on_bar(bar, history, regime, portfolio)


def compute_correlation_matrix(bars_by_symbol: dict[str, list[MarketBar]]) -> dict[tuple[str, str], float]:
    """Pairwise Pearson correlation of daily returns, estimated once from
    TRAIN-only data (the caller's responsibility to pass only that) --
    static for the whole backtest, not continuously re-estimated. Simple
    first (Rule 9): a fixed correlation snapshot is enough to avoid
    stacking several highly-correlated bets as if they were independent,
    without building a rolling-correlation estimator this project
    doesn't yet have evidence it needs.
    """
    returns_by_symbol: dict[str, dict] = {}
    for symbol, bars in bars_by_symbol.items():
        by_date = {}
        for index in range(1, len(bars)):
            if bars[index - 1].close == Decimal("0"):
                continue
            by_date[bars[index].timestamp.date()] = float((bars[index].close - bars[index - 1].close) / bars[index - 1].close)
        returns_by_symbol[symbol] = by_date

    matrix: dict[tuple[str, str], float] = {}
    symbols = list(bars_by_symbol.keys())
    for i, symbol_a in enumerate(symbols):
        for symbol_b in symbols[i:]:
            shared_dates = set(returns_by_symbol[symbol_a]) & set(returns_by_symbol[symbol_b])
            if len(shared_dates) < 30:
                correlation = 0.0
            else:
                a_values = [returns_by_symbol[symbol_a][d] for d in shared_dates]
                b_values = [returns_by_symbol[symbol_b][d] for d in shared_dates]
                correlation = _pearson(a_values, b_values)
            matrix[(symbol_a, symbol_b)] = correlation
            matrix[(symbol_b, symbol_a)] = correlation
    return matrix


def _pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    mean_a, mean_b = sum(a) / n, sum(b) / n
    cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
    std_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
    std_b = math.sqrt(sum((x - mean_b) ** 2 for x in b))
    if std_a == 0 or std_b == 0:
        return 0.0
    return cov / (std_a * std_b)


class CorrelationAwareRiskEngine:
    """Wraps a base RiskEngine: after the base engine's checks pass,
    scales down (or rejects) an order if the account already holds a
    position in a highly-correlated symbol -- two 3%-weight positions in
    assets with 0.9 correlation are close to one 6% bet, not two
    independent 3% bets, and the base engine's gross-exposure check alone
    doesn't see that distinction. Needs direct read access to the
    PositionManager (not just the aggregate PortfolioSnapshot) to know
    which symbols are actually open, since PortfolioSnapshot only carries
    portfolio-level aggregates.
    """

    def __init__(
        self,
        base_risk_engine: RiskEngine,
        position_manager: PositionManager,
        correlation_matrix: dict[tuple[str, str], float],
        correlation_threshold: Decimal = Decimal("0.7"),
    ) -> None:
        self.base_risk_engine = base_risk_engine
        self.position_manager = position_manager
        self.correlation_matrix = correlation_matrix
        self.correlation_threshold = correlation_threshold

    def approve_order(self, order: Order, bar: MarketBar, portfolio: PortfolioSnapshot) -> tuple[bool, str]:
        approved, reason = self.base_risk_engine.approve_order(order, bar, portfolio)
        if not approved:
            return approved, reason

        open_symbols = [symbol for symbol, position in self.position_manager.positions.items() if position.quantity != Decimal("0") and symbol != order.symbol]
        for other_symbol in open_symbols:
            correlation = self.correlation_matrix.get((order.symbol, other_symbol))
            if correlation is not None and abs(Decimal(str(correlation))) >= self.correlation_threshold:
                return False, f"Rejected: {order.symbol} correlates {correlation:.2f} with already-open {other_symbol}, exceeding {self.correlation_threshold} threshold"

        return True, reason
