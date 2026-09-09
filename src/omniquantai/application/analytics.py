from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from omniquantai.domain.models import Fill, PortfolioSnapshot


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    starting_equity: Decimal
    ending_equity: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    trade_count: int
    closed_trade_count: int = 0
    win_rate: Decimal | None = None  # None means no trades closed yet, not "0% -- every trade lost"
    profit_factor: Decimal | None = None
    expectancy: Decimal = Decimal("0")
    sharpe_ratio: Decimal = Decimal("0")
    sortino_ratio: Decimal = Decimal("0")


class PerformanceAnalytics:
    def __init__(self, starting_equity: Decimal, periods_per_year: int = 365) -> None:
        self.starting_equity = starting_equity
        self.periods_per_year = periods_per_year
        self.snapshots: list[PortfolioSnapshot] = []
        self.fills: list[Fill] = []
        self.closed_trade_pnls: list[Decimal] = []

    def record_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        self.snapshots.append(snapshot)

    def record_fill(self, fill: Fill, realized_pnl_delta: Decimal = Decimal("0")) -> None:
        self.fills.append(fill)
        if realized_pnl_delta != Decimal("0"):
            self.closed_trade_pnls.append(realized_pnl_delta)

    def _bar_returns(self) -> list[float]:
        returns: list[float] = []
        for previous, current in zip(self.snapshots, self.snapshots[1:]):
            if previous.equity > Decimal("0"):
                returns.append(float((current.equity - previous.equity) / previous.equity))
        return returns

    def _sharpe(self, returns: list[float]) -> Decimal:
        if len(returns) < 2:
            return Decimal("0")
        mean = sum(returns) / len(returns)
        variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
        stdev = math.sqrt(variance)
        if stdev == 0:
            return Decimal("0")
        return Decimal(str(round((mean / stdev) * math.sqrt(self.periods_per_year), 4)))

    def _sortino(self, returns: list[float]) -> Decimal:
        if len(returns) < 2:
            return Decimal("0")
        mean = sum(returns) / len(returns)
        downside_variance = sum(min(value, 0.0) ** 2 for value in returns) / len(returns)
        downside_dev = math.sqrt(downside_variance)
        if downside_dev == 0:
            return Decimal("0")
        return Decimal(str(round((mean / downside_dev) * math.sqrt(self.periods_per_year), 4)))

    def report(self) -> PerformanceReport:
        if not self.snapshots:
            return PerformanceReport(self.starting_equity, self.starting_equity, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), 0)

        peak = self.snapshots[0].equity
        max_drawdown = Decimal("0")
        for snapshot in self.snapshots:
            peak = max(peak, snapshot.equity)
            if peak > Decimal("0"):
                max_drawdown = max(max_drawdown, (peak - snapshot.equity) / peak)

        latest = self.snapshots[-1]

        wins = [pnl for pnl in self.closed_trade_pnls if pnl > Decimal("0")]
        losses = [pnl for pnl in self.closed_trade_pnls if pnl < Decimal("0")]
        closed_count = len(self.closed_trade_pnls)
        win_rate = (Decimal(len(wins)) / Decimal(closed_count)) if closed_count else None
        gross_profit = sum(wins, Decimal("0"))
        gross_loss = abs(sum(losses, Decimal("0")))
        profit_factor = (gross_profit / gross_loss) if gross_loss > Decimal("0") else None
        expectancy = (sum(self.closed_trade_pnls, Decimal("0")) / Decimal(closed_count)) if closed_count else Decimal("0")

        returns = self._bar_returns()

        return PerformanceReport(
            starting_equity=self.starting_equity,
            ending_equity=latest.equity,
            total_return=(latest.equity - self.starting_equity) / self.starting_equity,
            max_drawdown=max_drawdown,
            realized_pnl=latest.realized_pnl,
            unrealized_pnl=latest.unrealized_pnl,
            trade_count=len(self.fills),
            closed_trade_count=closed_count,
            win_rate=win_rate,
            profit_factor=profit_factor,
            expectancy=expectancy,
            sharpe_ratio=self._sharpe(returns),
            sortino_ratio=self._sortino(returns),
        )
