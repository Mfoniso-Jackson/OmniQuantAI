from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import uuid4


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class MarketRegime(str, Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MarketBar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError("low cannot exceed high")
        if not self.low <= self.close <= self.high:
            raise ValueError("close must sit inside high-low range")
        if self.volume < Decimal("0"):
            raise ValueError("volume cannot be negative")


@dataclass(frozen=True, slots=True)
class Signal:
    symbol: str
    action: SignalAction
    confidence: Decimal
    reason: str
    target_weight: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be between 0 and 1")
        if abs(self.target_weight) > Decimal("1"):
            raise ValueError("target_weight must be within -1 and 1")


@dataclass(frozen=True, slots=True)
class Order:
    symbol: str
    side: Side
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reason: str = ""

    def __post_init__(self) -> None:
        if self.quantity <= Decimal("0"):
            raise ValueError("order quantity must be positive")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require limit_price")


@dataclass(frozen=True, slots=True)
class Fill:
    order_id: str
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    commission: Decimal
    timestamp: datetime

    @property
    def notional(self) -> Decimal:
        return self.quantity * self.price


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: Decimal = Decimal("0")
    average_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")

    def apply_fill(self, fill: Fill) -> None:
        signed_quantity = fill.quantity if fill.side is Side.BUY else -fill.quantity
        if self.quantity == Decimal("0") or self.quantity.copy_sign(signed_quantity) == self.quantity:
            new_quantity = self.quantity + signed_quantity
            total_cost = (self.quantity * self.average_price) + (signed_quantity * fill.price)
            self.quantity = new_quantity
            self.average_price = Decimal("0") if new_quantity == Decimal("0") else total_cost / new_quantity
            return

        closing_quantity = min(abs(self.quantity), abs(signed_quantity))
        direction = Decimal("1") if self.quantity > Decimal("0") else Decimal("-1")
        self.realized_pnl += closing_quantity * (fill.price - self.average_price) * direction
        self.quantity += signed_quantity
        if self.quantity == Decimal("0"):
            self.average_price = Decimal("0")
        elif abs(signed_quantity) > closing_quantity:
            self.average_price = fill.price

    def market_value(self, mark_price: Decimal) -> Decimal:
        return self.quantity * mark_price

    def unrealized_pnl(self, mark_price: Decimal) -> Decimal:
        return self.quantity * (mark_price - self.average_price)


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    timestamp: datetime
    cash: Decimal
    equity: Decimal
    positions_value: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal

