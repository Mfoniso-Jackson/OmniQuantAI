"""Section 5 baseline experiment.

Runs the five required baseline strategies against identical historical
BTCUSDT data, transaction costs, and risk constraints, so we know whether
OmniQuantAI's regime detection / strategy selection / agentic layers are
actually earning their keep (Section 18's "key experiment") before adding
any more sophistication on top of them.

Usage:
    PYTHONPATH=src python3 experiments/baseline_comparison.py [1d|1h]
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from omniquantai.application.analytics import PerformanceAnalytics
from omniquantai.application.engine import PaperTradingEngine
from omniquantai.application.paper_broker import PaperBroker
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.application.strategies import (
    BuyAndHoldStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    MovingAverageTrendStrategy,
    VolatilityRegimeStrategy,
)
from omniquantai.configuration.settings import TradingSettings
from omniquantai.infrastructure.market_data import CsvMarketDataFeed

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

# periods_per_year for annualizing Sharpe/Sortino: crypto trades 24/7.
PERIODS_PER_YEAR = {"1d": 365, "1h": 365 * 24}

BASELINES = {
    "buy_and_hold": lambda: BuyAndHoldStrategy(),
    "momentum": lambda: MomentumStrategy(lookback=10),
    "ma_trend": lambda: MovingAverageTrendStrategy(fast=10, slow=30),
    "mean_reversion": lambda: MeanReversionStrategy(lookback=14),
    "volatility_regime": lambda: VolatilityRegimeStrategy(lookback=14),
}


def run_baseline(name: str, factory, data_path: Path, periods_per_year: int) -> dict:
    settings = TradingSettings()
    analytics = PerformanceAnalytics(settings.initial_cash, periods_per_year=periods_per_year)
    engine = PaperTradingEngine(
        feed=CsvMarketDataFeed(data_path),
        broker=PaperBroker(settings),
        risk_engine=InstitutionalRiskEngine(settings),
        position_manager=PositionManager(settings.initial_cash),
        strategies=[factory()],
        analytics=analytics,
        regime_detector=SimpleRegimeDetector(lookback=14),
    )
    report = engine.run()
    result = asdict(report)
    result["strategy"] = name
    return result


def print_table(results: list[dict]) -> None:
    header = (
        f"{'strategy':<18}{'return':>10}{'max_dd':>9}{'sharpe':>9}{'sortino':>9}"
        f"{'trades':>8}{'closed':>8}{'win_rate':>10}{'profit_fac':>12}{'expectancy':>13}"
    )
    print(header)
    print("-" * len(header))
    for result in results:
        profit_factor = result["profit_factor"]
        pf_display = f"{profit_factor:.2f}" if profit_factor is not None else "n/a"
        print(
            f"{result['strategy']:<18}"
            f"{result['total_return']:>9.2%} "
            f"{result['max_drawdown']:>8.2%} "
            f"{result['sharpe_ratio']:>8.2f} "
            f"{result['sortino_ratio']:>8.2f} "
            f"{result['trade_count']:>7} "
            f"{result['closed_trade_count']:>7} "
            f"{result['win_rate']:>9.1%} "
            f"{pf_display:>11} "
            f"{result['expectancy']:>12.2f}"
        )


def main() -> None:
    interval = sys.argv[1] if len(sys.argv) > 1 else "1d"
    data_path = DATA_DIR / f"btcusdt_{interval}.csv"
    if not data_path.exists():
        raise SystemExit(f"Missing historical data at {data_path}. Run scripts/fetch_weex_klines.py first.")

    periods_per_year = PERIODS_PER_YEAR.get(interval, 365)
    results = [run_baseline(name, factory, data_path, periods_per_year) for name, factory in BASELINES.items()]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_path = RESULTS_DIR / f"baseline_comparison_{interval}.json"
    results_path.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")

    print(f"BTCUSDT baseline comparison -- interval={interval}, data={data_path.name}\n")
    print_table(results)
    print(f"\nFull results written to {results_path}")


if __name__ == "__main__":
    main()
