from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from omniquantai.domain.models import Fill, MarketBar, MarketRegime, Order, PortfolioSnapshot, Signal


class MarketDataFeed(Protocol):
    def stream(self) -> Iterable[MarketBar]:
        """Yield market bars in chronological order."""


class Strategy(Protocol):
    name: str

    def on_bar(
        self,
        bar: MarketBar,
        history: Sequence[MarketBar],
        regime: MarketRegime,
        portfolio: PortfolioSnapshot,
    ) -> Signal:
        """Return an explainable trading signal for the current bar."""


class Broker(Protocol):
    def execute(self, order: Order, bar: MarketBar) -> Fill:
        """Execute an accepted order against the current market state."""


class RiskEngine(Protocol):
    def approve_order(self, order: Order, bar: MarketBar, portfolio: PortfolioSnapshot) -> tuple[bool, str]:
        """Approve or reject an order with an explainable reason."""

