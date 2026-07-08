from __future__ import annotations

import unittest

from core.decision_engine import make_decision
from core.regime_router import route_regime


class CoreCompatibilityTests(unittest.TestCase):
    def test_router_returns_profile_and_signals_for_decision_engine(self) -> None:
        ticker = {
            "symbol": "cmt_btcusdt",
            "last": "100.0",
            "best_bid": "99.99",
            "best_ask": "100.01",
            "priceChangePercent": "0.018",
        }

        router = route_regime(ticker)
        decision = make_decision(router["signals"], router["profile"])

        self.assertIn(router["regime"], {"TRENDING", "RANGING", "HIGH_VOLATILITY"})
        self.assertIn(decision["decision"], {"BUY", "SELL", "HOLD"})
        self.assertIn("explanation", decision)

