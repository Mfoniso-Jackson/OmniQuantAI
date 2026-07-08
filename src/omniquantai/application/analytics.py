from __future__ import annotations

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


class PerformanceAnalytics:
    def __init__(self, starting_equity: Decimal) -> None:
        self.starting_equity = starting_equity
        self.snapshots: list[PortfolioSnapshot] = []
        self.fills: list[Fill] = []

    def record_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        self.snapshots.append(snapshot)

    def record_fill(self, fill: Fill) -> None:
        self.fills.append(fill)

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
        return PerformanceReport(
            starting_equity=self.starting_equity,
            ending_equity=latest.equity,
            total_return=(latest.equity - self.starting_equity) / self.starting_equity,
            max_drawdown=max_drawdown,
            realized_pnl=latest.realized_pnl,
            unrealized_pnl=latest.unrealized_pnl,
            trade_count=len(self.fills),
        )

