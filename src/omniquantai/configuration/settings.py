from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TradingSettings:
    initial_cash: Decimal = Decimal("100000")
    max_order_notional_pct: Decimal = Decimal("0.05")
    max_symbol_exposure_pct: Decimal = Decimal("0.20")
    max_gross_exposure_pct: Decimal = Decimal("1.00")
    max_daily_loss_pct: Decimal = Decimal("0.03")
    commission_bps: Decimal = Decimal("1")
    slippage_bps: Decimal = Decimal("2")
    enable_live_trading: bool = False
    confirm_real_money: bool = False

    @property
    def live_trading_allowed(self) -> bool:
        return self.enable_live_trading and self.confirm_real_money


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> TradingSettings:
    return TradingSettings(
        initial_cash=Decimal(os.getenv("INITIAL_CASH", "100000")),
        max_order_notional_pct=Decimal(os.getenv("MAX_ORDER_NOTIONAL_PCT", "0.05")),
        max_symbol_exposure_pct=Decimal(os.getenv("MAX_SYMBOL_EXPOSURE_PCT", "0.20")),
        max_gross_exposure_pct=Decimal(os.getenv("MAX_GROSS_EXPOSURE_PCT", "1.00")),
        max_daily_loss_pct=Decimal(os.getenv("MAX_DAILY_LOSS_PCT", "0.03")),
        commission_bps=Decimal(os.getenv("COMMISSION_BPS", "1")),
        slippage_bps=Decimal(os.getenv("SLIPPAGE_BPS", "2")),
        enable_live_trading=_env_bool("ENABLE_LIVE_TRADING"),
        confirm_real_money=_env_bool("CONFIRM_REAL_MONEY"),
    )


def assert_live_trading_permitted(settings: TradingSettings) -> None:
    if not settings.live_trading_allowed:
        raise PermissionError("Live trading requires ENABLE_LIVE_TRADING=true and CONFIRM_REAL_MONEY=true")


def assert_exchange_execution_permitted(mode: str, settings: TradingSettings) -> None:
    normalized_mode = mode.strip().lower()
    if normalized_mode != "live":
        raise PermissionError(
            f"WEEX exchange execution is disabled while bot.mode={mode!r}. "
            "Use the paper trading CLI for credentials-free simulation."
        )
    assert_live_trading_permitted(settings)
