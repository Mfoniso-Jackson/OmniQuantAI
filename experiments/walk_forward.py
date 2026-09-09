"""Section 10/11 walk-forward validation.

The baseline_comparison.py experiment found mean_reversion the standout
baseline on the full 999-day BTCUSDT window -- but that is a single
in-sample number and Section 11 is explicit that this is the biggest danger
in the whole project: a strategy that looks great on one historical window
and fails live. This script checks two things before anyone trusts that
result:

1. TRAIN / VALIDATION / TEST split -- does the ranking found on TRAIN
   (first 50% of history) hold up on VALIDATION (next 25%) and TEST
   (final 25%, never looked at until this run)?
2. Rolling folds -- split the whole series into N equal chronological
   windows and check whether each strategy's edge is consistent
   fold-to-fold, or concentrated in one lucky period.

Each split/fold is run through a brand-new engine with no shared state, so
there is no look-ahead or leakage across boundaries.

Usage:
    PYTHONPATH=src python3 experiments/walk_forward.py [1d|1h] [folds]
"""

from __future__ import annotations

import json
import statistics
import sys
from dataclasses import asdict
from pathlib import Path

from omniquantai.application.analytics import PerformanceAnalytics
from omniquantai.application.data_split import DataSplit, chronological_split, rolling_folds
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
from omniquantai.domain.models import MarketBar
from omniquantai.infrastructure.market_data import InMemoryMarketDataFeed, read_market_bars

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
PERIODS_PER_YEAR = {"1d": 365, "1h": 365 * 24}

BASELINES = {
    "buy_and_hold": lambda: BuyAndHoldStrategy(),
    "momentum": lambda: MomentumStrategy(lookback=10),
    "ma_trend": lambda: MovingAverageTrendStrategy(fast=10, slow=30),
    "mean_reversion": lambda: MeanReversionStrategy(lookback=14),
    "volatility_regime": lambda: VolatilityRegimeStrategy(lookback=14),
}


def run_baseline_on_bars(name: str, factory, bars: list[MarketBar], periods_per_year: int) -> dict:
    settings = TradingSettings()
    analytics = PerformanceAnalytics(settings.initial_cash, periods_per_year=periods_per_year)
    engine = PaperTradingEngine(
        feed=InMemoryMarketDataFeed(bars),
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
    result["bar_count"] = len(bars)
    return result


def evaluate_splits(splits: list[DataSplit], periods_per_year: int) -> dict[str, list[dict]]:
    by_strategy: dict[str, list[dict]] = {name: [] for name in BASELINES}
    for split in splits:
        if not split.bars:
            continue
        for name, factory in BASELINES.items():
            result = run_baseline_on_bars(name, factory, split.bars, periods_per_year)
            result["split"] = split.name
            by_strategy[name].append(result)
    return by_strategy


def print_phase_table(title: str, by_strategy: dict[str, list[dict]]) -> None:
    print(f"\n{title}")
    header = f"{'strategy':<18}{'phase':<12}{'bars':>6}{'return':>10}{'max_dd':>9}{'sharpe':>9}{'win_rate':>10}"
    print(header)
    print("-" * len(header))
    for name, results in by_strategy.items():
        for result in results:
            win_rate = result["win_rate"]
            win_rate_display = f"{win_rate:.1%}" if win_rate is not None else "n/a"
            print(
                f"{name:<18}{result['split']:<12}{result['bar_count']:>6}"
                f"{result['total_return']:>9.2%} {result['max_drawdown']:>8.2%} "
                f"{result['sharpe_ratio']:>8.2f} {win_rate_display:>9}"
            )


def print_consistency_table(fold_results: dict[str, list[dict]]) -> None:
    print("\nFold-to-fold consistency (mean +/- stdev across folds; lower stdev = more consistent edge)")
    header = f"{'strategy':<18}{'mean_return':>13}{'stdev_return':>14}{'mean_sharpe':>13}{'stdev_sharpe':>14}{'folds_positive':>16}"
    print(header)
    print("-" * len(header))
    for name, results in fold_results.items():
        returns = [float(result["total_return"]) for result in results]
        sharpes = [float(result["sharpe_ratio"]) for result in results]
        positive = sum(1 for value in returns if value > 0)
        mean_return = statistics.mean(returns) if returns else 0.0
        stdev_return = statistics.pstdev(returns) if len(returns) > 1 else 0.0
        mean_sharpe = statistics.mean(sharpes) if sharpes else 0.0
        stdev_sharpe = statistics.pstdev(sharpes) if len(sharpes) > 1 else 0.0
        print(
            f"{name:<18}{mean_return:>12.2%} {stdev_return:>13.2%} "
            f"{mean_sharpe:>12.2f} {stdev_sharpe:>13.2f} {positive:>10}/{len(returns)}"
        )


def main() -> None:
    interval = sys.argv[1] if len(sys.argv) > 1 else "1d"
    folds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    data_path = DATA_DIR / f"btcusdt_{interval}.csv"
    if not data_path.exists():
        raise SystemExit(f"Missing historical data at {data_path}. Run scripts/fetch_weex_klines.py first.")

    periods_per_year = PERIODS_PER_YEAR.get(interval, 365)
    bars = read_market_bars(data_path)

    tvt_splits = chronological_split(bars, train_pct=0.5, validation_pct=0.25)
    tvt_results = evaluate_splits(tvt_splits, periods_per_year)
    print_phase_table(f"TRAIN/VALIDATION/TEST -- {interval} ({len(bars)} bars)", tvt_results)

    fold_splits = rolling_folds(bars, folds=folds)
    fold_results = evaluate_splits(fold_splits, periods_per_year)
    print_phase_table(f"Rolling folds (k={folds}) -- {interval}", fold_results)
    print_consistency_table(fold_results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / f"walk_forward_{interval}.json"
    output_path.write_text(
        json.dumps({"train_validation_test": tvt_results, "rolling_folds": fold_results}, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"\nFull results written to {output_path}")


if __name__ == "__main__":
    main()
