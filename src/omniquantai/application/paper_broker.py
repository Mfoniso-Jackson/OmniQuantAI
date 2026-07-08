from __future__ import annotations

from decimal import Decimal

from omniquantai.configuration.settings import TradingSettings
from omniquantai.domain.models import Fill, MarketBar, Order, Side


class PaperBroker:
    def __init__(self, settings: TradingSettings) -> None:
        self.settings = settings

    def execute(self, order: Order, bar: MarketBar) -> Fill:
        slippage_multiplier = self.settings.slippage_bps / Decimal("10000")
        price = bar.close * (Decimal("1") + slippage_multiplier if order.side is Side.BUY else Decimal("1") - slippage_multiplier)
        commission = order.quantity * price * self.settings.commission_bps / Decimal("10000")
        return Fill(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            commission=commission,
            timestamp=bar.timestamp,
        )

