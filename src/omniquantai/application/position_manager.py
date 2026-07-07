from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from omniquantai.domain.models import Fill, PortfolioSnapshot, Position


class PositionManager:
    def __init__(self, initial_cash: Decimal) -> None:
        self.cash = initial_cash
        self.positions: dict[str, Position] = {}

    def apply_fill(self, fill: Fill) -> None:
        position = self.positions.setdefault(fill.symbol, Position(symbol=fill.symbol))
        position.apply_fill(fill)
        cash_delta = fill.notional + fill.commission
        self.cash += -cash_delta if fill.side.value == "buy" else fill.notional - fill.commission

    def position(self, symbol: str) -> Position:
        return self.positions.get(symbol, Position(symbol=symbol))

    def snapshot(self, marks: dict[str, Decimal], timestamp: datetime | None = None) -> PortfolioSnapshot:
        positions_value = Decimal("0")
        realized_pnl = Decimal("0")
        unrealized_pnl = Decimal("0")
        for symbol, position in self.positions.items():
            mark = marks.get(symbol, position.average_price)
            positions_value += position.market_value(mark)
            realized_pnl += position.realized_pnl
            unrealized_pnl += position.unrealized_pnl(mark)
        equity = self.cash + positions_value
        return PortfolioSnapshot(
            timestamp=timestamp or datetime.now(UTC),
            cash=self.cash,
            equity=equity,
            positions_value=positions_value,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
        )

