from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from omniquantai.application.analytics import PerformanceAnalytics
from omniquantai.application.engine import PaperTradingEngine
from omniquantai.application.paper_broker import PaperBroker
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.application.strategies import MomentumStrategy
from omniquantai.configuration.settings import TradingSettings
from omniquantai.domain.models import MarketBar
from omniquantai.infrastructure.market_data import InMemoryMarketDataFeed


class EngineIntegrationTests(unittest.TestCase):
    def test_engine_runs_end_to_end_without_credentials(self) -> None:
        settings = TradingSettings(initial_cash=Decimal("100000"))
        start = datetime(2026, 1, 1, tzinfo=UTC)
        bars = [
            MarketBar("BTCUSDT", start + timedelta(minutes=index), price, price + Decimal("1"), price - Decimal("1"), price, Decimal("100"))
            for index, price in enumerate(
                [Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103"), Decimal("104"), Decimal("106"), Decimal("108"), Decimal("109"), Decimal("111"), Decimal("113")]
            )
        ]
        analytics = PerformanceAnalytics(settings.initial_cash)
        engine = PaperTradingEngine(
            feed=InMemoryMarketDataFeed(bars),
            broker=PaperBroker(settings),
            risk_engine=InstitutionalRiskEngine(settings),
            position_manager=PositionManager(settings.initial_cash),
            strategies=[MomentumStrategy(lookback=3)],
            analytics=analytics,
            regime_detector=SimpleRegimeDetector(lookback=3),
        )

        report = engine.run()

        self.assertGreaterEqual(report.trade_count, 1)
        self.assertNotEqual(report.ending_equity, Decimal("100000"))

