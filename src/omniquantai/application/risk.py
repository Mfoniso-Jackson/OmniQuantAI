from __future__ import annotations

from decimal import Decimal

from omniquantai.configuration.settings import TradingSettings
from omniquantai.domain.models import MarketBar, Order, PortfolioSnapshot


class InstitutionalRiskEngine:
    def __init__(self, settings: TradingSettings) -> None:
        self.settings = settings
        self.starting_equity = settings.initial_cash

    def approve_order(self, order: Order, bar: MarketBar, portfolio: PortfolioSnapshot) -> tuple[bool, str]:
        if portfolio.equity <= Decimal("0"):
            return False, "Rejected: portfolio equity is non-positive"

        notional = order.quantity * bar.close
        if notional > portfolio.equity * self.settings.max_order_notional_pct:
            return False, "Rejected: order notional exceeds max order risk budget"

        projected_symbol_exposure = abs(notional)
        if projected_symbol_exposure > portfolio.equity * self.settings.max_symbol_exposure_pct:
            return False, "Rejected: symbol exposure exceeds configured cap"

        projected_gross = abs(portfolio.positions_value) + abs(notional)
        if projected_gross > portfolio.equity * self.settings.max_gross_exposure_pct:
            return False, "Rejected: gross exposure exceeds configured cap"

        daily_loss = self.starting_equity - portfolio.equity
        if daily_loss > self.starting_equity * self.settings.max_daily_loss_pct:
            return False, "Rejected: daily loss limit breached"

        return True, "Approved: order is within configured risk limits"

