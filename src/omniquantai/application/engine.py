from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal

from omniquantai.application.analytics import PerformanceAnalytics, PerformanceReport
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.protocols import Broker, MarketDataFeed, RiskEngine, Strategy
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.domain.models import MarketBar, MarketRegime, Order, Side, SignalAction


class PaperTradingEngine:
    def __init__(
        self,
        feed: MarketDataFeed,
        broker: Broker,
        risk_engine: RiskEngine,
        position_manager: PositionManager,
        strategies: list[Strategy],
        analytics: PerformanceAnalytics,
        regime_detector: SimpleRegimeDetector,
        logger: logging.Logger | None = None,
    ) -> None:
        self.feed = feed
        self.broker = broker
        self.risk_engine = risk_engine
        self.position_manager = position_manager
        self.strategies = strategies
        self.analytics = analytics
        self.regime_detector = regime_detector
        self.logger = logger or logging.getLogger(__name__)
        self.history: dict[str, list[MarketBar]] = defaultdict(list)
        self.marks: dict[str, Decimal] = {}

    def run(self) -> PerformanceReport:
        for bar in self.feed.stream():
            self.marks[bar.symbol] = bar.close
            symbol_history = self.history[bar.symbol]
            symbol_history.append(bar)
            portfolio = self.position_manager.snapshot(self.marks, bar.timestamp)
            regime = self.regime_detector.detect(symbol_history)
            self.logger.info("bar received", extra={"symbol": bar.symbol, "close": str(bar.close), "regime": regime.value})

            for strategy in self.strategies:
                signal = strategy.on_bar(bar, symbol_history, regime, portfolio)
                self.logger.info("signal generated", extra={"strategy": strategy.name, "signal": signal.action.value, "reason": signal.reason})
                if signal.action is SignalAction.HOLD:
                    continue
                quantity = self._quantity_for_signal(signal.target_weight, portfolio.equity, bar.close)
                if quantity <= Decimal("0"):
                    continue
                side = Side.BUY if signal.action is SignalAction.BUY else Side.SELL
                order = Order(symbol=bar.symbol, side=side, quantity=quantity, reason=signal.reason)
                approved, reason = self.risk_engine.approve_order(order, bar, portfolio)
                self.logger.info("risk decision", extra={"approved": approved, "reason": reason})
                if not approved:
                    continue
                realized_before = portfolio.realized_pnl
                fill = self.broker.execute(order, bar)
                self.position_manager.apply_fill(fill)
                portfolio = self.position_manager.snapshot(self.marks, bar.timestamp)
                self.analytics.record_fill(fill, realized_pnl_delta=portfolio.realized_pnl - realized_before)

            self.analytics.record_snapshot(self.position_manager.snapshot(self.marks, bar.timestamp))

        return self.analytics.report()

    @staticmethod
    def _quantity_for_signal(target_weight: Decimal, equity: Decimal, price: Decimal) -> Decimal:
        if price <= Decimal("0"):
            return Decimal("0")
        return abs((equity * target_weight) / price).quantize(Decimal("0.0001"))

