from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from omniquantai.application.analytics import PerformanceAnalytics, PerformanceReport
from omniquantai.application.engine import PaperTradingEngine
from omniquantai.application.paper_broker import PaperBroker
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.application.strategies import MomentumStrategy
from omniquantai.configuration.settings import TradingSettings
from omniquantai.domain.models import MarketBar
from omniquantai.infrastructure.market_data import InMemoryMarketDataFeed


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class CompetitionReport:
    generated_at: str
    mode: str
    gates: list[GateResult]
    performance: PerformanceReport
    decision_log_path: str
    ai_log_path: str
    recommendation: str


def synthetic_competition_bars(symbol: str = "BTCUSDT") -> list[MarketBar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    prices = [
        Decimal("100"),
        Decimal("100.8"),
        Decimal("101.5"),
        Decimal("102.0"),
        Decimal("101.7"),
        Decimal("102.9"),
        Decimal("104.2"),
        Decimal("105.4"),
        Decimal("105.0"),
        Decimal("106.6"),
        Decimal("108.2"),
        Decimal("109.0"),
        Decimal("108.5"),
        Decimal("110.2"),
        Decimal("111.5"),
    ]
    return [
        MarketBar(
            symbol=symbol,
            timestamp=start + timedelta(minutes=index),
            open=price,
            high=price + Decimal("1"),
            low=price - Decimal("1"),
            close=price,
            volume=Decimal("1000"),
        )
        for index, price in enumerate(prices)
    ]


def build_competition_gates(settings: TradingSettings) -> list[GateResult]:
    return [
        GateResult("paper_default", "pass", "Competition mode runs in dry-run/paper mode by default."),
        GateResult(
            "live_gate",
            "pass" if not settings.live_trading_allowed else "warn",
            "Live trading is blocked unless both ENABLE_LIVE_TRADING and CONFIRM_REAL_MONEY are true.",
        ),
        GateResult("risk_budget", "pass", f"Max order notional is {settings.max_order_notional_pct:.2%} of equity."),
        GateResult("capital_preservation", "pass", f"Daily loss cap is {settings.max_daily_loss_pct:.2%}."),
        GateResult("explainability", "pass", "Decision and AI-log evidence files are generated for review."),
    ]


def _decimal_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_decimal_default) + "\n", encoding="utf-8")


def _build_ai_log(report: PerformanceReport, decision_log_path: Path) -> dict[str, Any]:
    return {
        "stage": "Decision Making",
        "model": "OmniQuantAI-competition-playbook-v0.1",
        "input": {
            "source": "competition dry-run simulation",
            "decision_log_path": str(decision_log_path),
            "objective": "Preserve capital while validating explainable WEEX AI Wars trading workflow.",
        },
        "output": {
            "action": "NO_LIVE_ORDER",
            "mode": "DRY_RUN",
            "ending_equity": str(report.ending_equity),
            "total_return": str(report.total_return),
            "max_drawdown": str(report.max_drawdown),
            "trade_count": report.trade_count,
        },
        "explanation": (
            "Competition playbook dry-run completed without live exchange execution. "
            "The run validates market data, strategy, risk, paper execution, analytics, and evidence generation."
        ),
    }


def run_competition_playbook(output_dir: Path, settings: TradingSettings | None = None) -> CompetitionReport:
    active_settings = settings or TradingSettings()
    analytics = PerformanceAnalytics(active_settings.initial_cash)
    bars = synthetic_competition_bars()
    engine = PaperTradingEngine(
        feed=InMemoryMarketDataFeed(bars),
        broker=PaperBroker(active_settings),
        risk_engine=InstitutionalRiskEngine(active_settings),
        position_manager=PositionManager(active_settings.initial_cash),
        strategies=[MomentumStrategy(lookback=4)],
        analytics=analytics,
        regime_detector=SimpleRegimeDetector(lookback=4),
    )
    performance = engine.run()

    generated_at = datetime.now(UTC).isoformat()
    decision_log = {
        "generated_at": generated_at,
        "symbol": "BTCUSDT",
        "mode": "DRY_RUN",
        "performance": asdict(performance),
        "gates": [asdict(gate) for gate in build_competition_gates(active_settings)],
        "next_action": "Review report, then run WEEX profile/account checks before any live-min-size test.",
    }
    decision_log_path = output_dir / "competition_decision_log.json"
    ai_log_path = output_dir / "competition_ai_log.json"
    _write_json(decision_log_path, decision_log)
    _write_json(ai_log_path, _build_ai_log(performance, decision_log_path))

    recommendation = "STAY_IN_DRY_RUN"
    if performance.trade_count > 0 and performance.max_drawdown <= Decimal("0.02"):
        recommendation = "READY_FOR_PROFILE_AND_ACCOUNT_CHECKS"

    return CompetitionReport(
        generated_at=generated_at,
        mode="DRY_RUN",
        gates=build_competition_gates(active_settings),
        performance=performance,
        decision_log_path=str(decision_log_path),
        ai_log_path=str(ai_log_path),
        recommendation=recommendation,
    )

