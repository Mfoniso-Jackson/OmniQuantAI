"""Section 18 experiment B: does regime-conditional strategy selection
recover an edge that no static baseline has?

walk_forward.py found that mean_reversion's strong TRAIN performance
(+25.4%, Sharpe 1.66) collapsed on VALIDATION/TEST, with a clear regime
break around fold 4. This script tests the natural hypothesis that follows:
if mean_reversion is only reliable in a specific regime, does explicitly
gating it to that regime (via RegimeSelectorStrategy) recover robustness
across the same TRAIN/VALIDATION/TEST split and rolling folds -- or does
the edge disappear regardless of regime-gating, meaning the problem isn't
"wrong regime" but "no real edge at all"?

Variants tested, all run through the same fresh-per-split engine as
walk_forward.py (no shared state, no look-ahead across boundaries):

- mean_reversion            : ungated baseline (for reference)
- mean_reversion_ranging    : gated to RANGING only
- momentum                  : ungated baseline (for reference)
- momentum_trending         : gated to TRENDING only
- regime_selector           : momentum in TRENDING, mean_reversion in
                              RANGING, flat in VOLATILE/UNKNOWN -- the
                              actual Section 9 strategy-selection pattern

Usage:
    PYTHONPATH=src python3 experiments/regime_gating.py [1d|1h] [folds]
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
    MeanReversionStrategy,
    MomentumStrategy,
    RegimeSelectorStrategy,
    gate_to_regimes,
)
from omniquantai.configuration.settings import TradingSettings
from omniquantai.domain.models import MarketBar, MarketRegime
from omniquantai.infrastructure.market_data import InMemoryMarketDataFeed, read_market_bars

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
PERIODS_PER_YEAR = {"1d": 365, "1h": 365 * 24}


def build_variants() -> dict[str, object]:
    return {
        "mean_reversion": MeanReversionStrategy(lookback=14),
        "mean_reversion_ranging": gate_to_regimes(MeanReversionStrategy(lookback=14), frozenset({MarketRegime.RANGING})),
        "momentum": MomentumStrategy(lookback=10),
        "momentum_trending": gate_to_regimes(MomentumStrategy(lookback=10), frozenset({MarketRegime.TRENDING})),
        "regime_selector": RegimeSelectorStrategy(
            {
                MarketRegime.TRENDING: MomentumStrategy(lookback=10),
                MarketRegime.RANGING: MeanReversionStrategy(lookback=14),
            },
            name="regime_selector",
        ),
    }


def run_variant_on_bars(name: str, strategy, bars: list[MarketBar], periods_per_year: int) -> dict:
    settings = TradingSettings()
    analytics = PerformanceAnalytics(settings.initial_cash, periods_per_year=periods_per_year)
    engine = PaperTradingEngine(
        feed=InMemoryMarketDataFeed(bars),
        broker=PaperBroker(settings),
        risk_engine=InstitutionalRiskEngine(settings),
        position_manager=PositionManager(settings.initial_cash),
        strategies=[strategy],
        analytics=analytics,
        regime_detector=SimpleRegimeDetector(lookback=14),
    )
    report = engine.run()
    result = asdict(report)
    result["strategy"] = name
    result["bar_count"] = len(bars)
    return result


def evaluate_splits(splits: list[DataSplit], periods_per_year: int) -> dict[str, list[dict]]:
    by_strategy: dict[str, list[dict]] = {name: [] for name in build_variants()}
    for split in splits:
        if not split.bars:
            continue
        for name, strategy in build_variants().items():
            result = run_variant_on_bars(name, strategy, split.bars, periods_per_year)
            result["split"] = split.name
            by_strategy[name].append(result)
    return by_strategy


def print_phase_table(title: str, by_strategy: dict[str, list[dict]]) -> None:
    print(f"\n{title}")
    header = f"{'strategy':<24}{'phase':<12}{'bars':>6}{'return':>10}{'max_dd':>9}{'sharpe':>9}{'win_rate':>10}"
    print(header)
    print("-" * len(header))
    for name, results in by_strategy.items():
        for result in results:
            win_rate = result["win_rate"]
            win_rate_display = f"{win_rate:.1%}" if win_rate is not None else "n/a"
            print(
                f"{name:<24}{result['split']:<12}{result['bar_count']:>6}"
                f"{result['total_return']:>9.2%} {result['max_drawdown']:>8.2%} "
                f"{result['sharpe_ratio']:>8.2f} {win_rate_display:>9}"
            )


def print_consistency_table(fold_results: dict[str, list[dict]]) -> None:
    print("\nFold-to-fold consistency (mean +/- stdev across folds)")
    header = f"{'strategy':<24}{'mean_return':>13}{'stdev_return':>14}{'mean_sharpe':>13}{'folds_positive':>16}"
    print(header)
    print("-" * len(header))
    for name, results in fold_results.items():
        returns = [float(result["total_return"]) for result in results]
        sharpes = [float(result["sharpe_ratio"]) for result in results]
        positive = sum(1 for value in returns if value > 0)
        mean_return = statistics.mean(returns) if returns else 0.0
        stdev_return = statistics.pstdev(returns) if len(returns) > 1 else 0.0
        mean_sharpe = statistics.mean(sharpes) if sharpes else 0.0
        print(f"{name:<24}{mean_return:>12.2%} {stdev_return:>13.2%} {mean_sharpe:>12.2f} {positive:>10}/{len(returns)}")


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
    output_path = RESULTS_DIR / f"regime_gating_{interval}.json"
    output_path.write_text(
        json.dumps({"train_validation_test": tvt_results, "rolling_folds": fold_results}, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"\nFull results written to {output_path}")


if __name__ == "__main__":
    main()
