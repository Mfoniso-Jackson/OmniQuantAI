from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import unittest

from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.configuration.settings import TradingSettings
from omniquantai.domain.models import MarketBar, Order, PortfolioSnapshot, Side


class RiskTests(unittest.TestCase):
    def test_rejects_oversized_order(self) -> None:
        settings = TradingSettings(initial_cash=Decimal("1000"), max_order_notional_pct=Decimal("0.05"))
        engine = InstitutionalRiskEngine(settings)
        bar = MarketBar("BTCUSDT", datetime.now(UTC), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1"))
        order = Order("BTCUSDT", Side.BUY, Decimal("1"))
        portfolio = PortfolioSnapshot(datetime.now(UTC), Decimal("1000"), Decimal("1000"), Decimal("0"), Decimal("0"), Decimal("0"))

        approved, reason = engine.approve_order(order, bar, portfolio)

        self.assertFalse(approved)
        self.assertIn("order notional", reason)

