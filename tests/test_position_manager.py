from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import unittest

from omniquantai.application.position_manager import PositionManager
from omniquantai.domain.models import Fill, Side


class PositionManagerTests(unittest.TestCase):
    def test_apply_buy_and_sell_updates_cash_and_pnl(self) -> None:
        manager = PositionManager(Decimal("1000"))
        manager.apply_fill(Fill("o1", "BTCUSDT", Side.BUY, Decimal("2"), Decimal("100"), Decimal("1"), datetime.now(UTC)))
        manager.apply_fill(Fill("o2", "BTCUSDT", Side.SELL, Decimal("1"), Decimal("110"), Decimal("1"), datetime.now(UTC)))

        snapshot = manager.snapshot({"BTCUSDT": Decimal("120")})

        self.assertEqual(manager.position("BTCUSDT").quantity, Decimal("1"))
        self.assertEqual(manager.position("BTCUSDT").realized_pnl, Decimal("10"))
        self.assertEqual(snapshot.unrealized_pnl, Decimal("20"))
        self.assertEqual(snapshot.cash, Decimal("908"))

