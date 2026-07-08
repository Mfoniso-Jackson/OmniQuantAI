from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from omniquantai.application.analytics import PerformanceAnalytics
from omniquantai.application.engine import PaperTradingEngine
from omniquantai.application.paper_broker import PaperBroker
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.application.strategies import MomentumStrategy
from omniquantai.configuration.settings import load_settings
from omniquantai.domain.models import MarketBar
from omniquantai.infrastructure.logging import configure_logging
from omniquantai.infrastructure.market_data import InMemoryMarketDataFeed


def synthetic_bars() -> list[MarketBar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    prices = [Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103"), Decimal("104"), Decimal("105"), Decimal("106"), Decimal("108"), Decimal("109"), Decimal("110"), Decimal("109"), Decimal("111")]
    return [
        MarketBar("BTCUSDT", start + timedelta(minutes=index), price, price + Decimal("1"), price - Decimal("1"), price, Decimal("1000"))
        for index, price in enumerate(prices)
    ]


def main() -> None:
    settings = load_settings()
    logger = configure_logging()
    engine = PaperTradingEngine(
        feed=InMemoryMarketDataFeed(synthetic_bars()),
        broker=PaperBroker(settings),
        risk_engine=InstitutionalRiskEngine(settings),
        position_manager=PositionManager(settings.initial_cash),
        strategies=[MomentumStrategy()],
        analytics=PerformanceAnalytics(settings.initial_cash),
        regime_detector=SimpleRegimeDetector(),
        logger=logger,
    )
    report = engine.run()
    print(report)


if __name__ == "__main__":
    main()

