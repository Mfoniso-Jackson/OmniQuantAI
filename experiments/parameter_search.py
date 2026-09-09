"""Search for a genuine, walk-forward-robust edge, properly disciplined:

1. Grid-search each strategy family's parameters on TRAIN only (first 50% of
   history). Selection metric is Sharpe ratio, not raw return.
2. For each candidate, also compute a "neighbor stability" score: the mean
   Sharpe of its immediate neighbors in the grid (holding other parameters
   fixed). A parameter setting that only works in isolation, with worse
   neighbors on every side, is exactly the "spectacular fragile backtest"
   Section 11 warns about -- an isolated spike is not an edge, it's noise
   that happened to line up with this data. Combined score rewards points
   that sit in a stable, positive-Sharpe plateau, not lucky isolated peaks.
3. Take the single best-combined-score candidate per family and evaluate it
   ONCE on VALIDATION (untouched until this point). This is the actual
   out-of-sample check -- if it doesn't hold up here, the "edge" found on
   TRAIN was overfitting, full stop, regardless of how good it looked.
4. TEST is reserved for a single final check on the overall winner (across
   all families), not spent on every candidate -- checking TEST for many
   candidates and picking whichever looks best there just moves the
   overfitting from TRAIN to TEST.

Usage:
    PYTHONPATH=src python3 experiments/parameter_search.py [symbol] [1d|1h]
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import sys

from omniquantai.application.analytics import PerformanceAnalytics
from omniquantai.application.data_split import chronological_split
from omniquantai.application.engine import PaperTradingEngine
from omniquantai.application.paper_broker import PaperBroker
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.application.strategies import (
    BreakoutStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    MovingAverageTrendStrategy,
    VolatilityExpansionStrategy,
    VolatilityRegimeStrategy,
)
from omniquantai.configuration.settings import TradingSettings
from omniquantai.domain.models import MarketBar
from omniquantai.infrastructure.market_data import InMemoryMarketDataFeed, read_market_bars

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
PERIODS_PER_YEAR = {"1d": 365, "1h": 365 * 24}

MIN_TRADES_TO_QUALIFY = 5  # ignore parameter points that barely traded -- not a real signal


def run(strategy, bars: list[MarketBar], periods_per_year: int) -> dict:
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
    return asdict(report)


def momentum_grid():
    for lookback in (3, 5, 8, 14, 20):
        for threshold in (Decimal("0.005"), Decimal("0.01"), Decimal("0.02"), Decimal("0.03")):
            yield {"lookback": lookback, "threshold": threshold}, lambda lb=lookback, th=threshold: MomentumStrategy(lookback=lb, threshold=th)


def mean_reversion_grid():
    for lookback in (5, 7, 10, 14, 20, 30):
        for threshold in (Decimal("0.005"), Decimal("0.01"), Decimal("0.015"), Decimal("0.02"), Decimal("0.03")):
            yield {"lookback": lookback, "threshold": threshold}, lambda lb=lookback, th=threshold: MeanReversionStrategy(lookback=lb, threshold=th)


def ma_trend_grid():
    for fast, slow in ((5, 20), (10, 30), (10, 50), (20, 50), (20, 100)):
        yield {"fast": fast, "slow": slow}, lambda f=fast, s=slow: MovingAverageTrendStrategy(fast=f, slow=s)


def volatility_regime_grid():
    for lookback in (7, 14, 21, 30):
        for vol_ceiling in (Decimal("0.02"), Decimal("0.03"), Decimal("0.05")):
            yield {"lookback": lookback, "vol_ceiling": vol_ceiling}, lambda lb=lookback, vc=vol_ceiling: VolatilityRegimeStrategy(lookback=lb, vol_ceiling=vc)


def breakout_grid():
    for lookback in (10, 20, 30, 50):
        for confirmation in (Decimal("0.003"), Decimal("0.005"), Decimal("0.01")):
            yield {"lookback": lookback, "confirmation": confirmation}, lambda lb=lookback, cf=confirmation: BreakoutStrategy(lookback=lb, confirmation=cf)


def volatility_expansion_grid():
    for short_lookback, baseline_lookback in ((3, 14), (5, 20), (5, 30), (7, 30)):
        for expansion_ratio in (Decimal("1.3"), Decimal("1.5"), Decimal("2.0")):
            yield (
                {"short_lookback": short_lookback, "baseline_lookback": baseline_lookback, "expansion_ratio": expansion_ratio},
                lambda sl=short_lookback, bl=baseline_lookback, er=expansion_ratio: VolatilityExpansionStrategy(
                    short_lookback=sl, baseline_lookback=bl, expansion_ratio=er
                ),
            )


FAMILIES = {
    "momentum": momentum_grid,
    "mean_reversion": mean_reversion_grid,
    "ma_trend": ma_trend_grid,
    "volatility_regime": volatility_regime_grid,
    "breakout": breakout_grid,
    "volatility_expansion": volatility_expansion_grid,
}


def neighbor_key_dims(params: dict) -> list[str]:
    return [key for key in params if not isinstance(params[key], str)]


def sharpe_lookup(candidates: list[dict]) -> dict[tuple, float]:
    lookup = {}
    for candidate in candidates:
        key = tuple(sorted((k, str(v)) for k, v in candidate["params"].items()))
        lookup[key] = candidate["sharpe"] if candidate["trade_count"] >= MIN_TRADES_TO_QUALIFY else None
    return lookup


def param_grid_values(candidates: list[dict]) -> dict[str, list]:
    values: dict[str, set] = {}
    for candidate in candidates:
        for key, value in candidate["params"].items():
            values.setdefault(key, set()).add(value)
    return {key: sorted(vals, key=str) for key, vals in values.items()}


def neighbor_average(candidate: dict, all_candidates: list[dict], grid_values: dict[str, list]) -> float | None:
    scores = []
    for dim, values in grid_values.items():
        current = candidate["params"][dim]
        idx = values.index(current)
        for neighbor_idx in (idx - 1, idx + 1):
            if 0 <= neighbor_idx < len(values):
                neighbor_params = dict(candidate["params"])
                neighbor_params[dim] = values[neighbor_idx]
                match = next(
                    (c for c in all_candidates if c["params"] == neighbor_params),
                    None,
                )
                if match is not None and match["trade_count"] >= MIN_TRADES_TO_QUALIFY:
                    scores.append(match["sharpe"])
    return statistics.mean(scores) if scores else None


def search_family(name: str, grid_fn, train_bars: list[MarketBar], periods_per_year: int) -> list[dict]:
    candidates = []
    for params, factory in grid_fn():
        result = run(factory(), train_bars, periods_per_year)
        candidates.append(
            {
                "params": params,
                "sharpe": result["sharpe_ratio"],
                "return": result["total_return"],
                "max_drawdown": result["max_drawdown"],
                "win_rate": result["win_rate"],
                "trade_count": result["trade_count"],
            }
        )

    grid_values = param_grid_values(candidates)
    for candidate in candidates:
        candidate["neighbor_avg_sharpe"] = neighbor_average(candidate, candidates, grid_values)

    qualified = [c for c in candidates if c["trade_count"] >= MIN_TRADES_TO_QUALIFY and c["neighbor_avg_sharpe"] is not None]
    for candidate in qualified:
        candidate["combined_score"] = 0.5 * float(candidate["sharpe"]) + 0.5 * float(candidate["neighbor_avg_sharpe"])

    qualified.sort(key=lambda c: c["combined_score"], reverse=True)
    return qualified


def factory_for(name: str, params: dict):
    if name == "momentum":
        return MomentumStrategy(lookback=params["lookback"], threshold=params["threshold"])
    if name == "mean_reversion":
        return MeanReversionStrategy(lookback=params["lookback"], threshold=params["threshold"])
    if name == "ma_trend":
        return MovingAverageTrendStrategy(fast=params["fast"], slow=params["slow"])
    if name == "volatility_regime":
        return VolatilityRegimeStrategy(lookback=params["lookback"], vol_ceiling=params["vol_ceiling"])
    if name == "breakout":
        return BreakoutStrategy(lookback=params["lookback"], confirmation=params["confirmation"])
    if name == "volatility_expansion":
        return VolatilityExpansionStrategy(
            short_lookback=params["short_lookback"], baseline_lookback=params["baseline_lookback"], expansion_ratio=params["expansion_ratio"]
        )
    raise ValueError(name)


def search_symbol(symbol: str, interval: str = "1d", verbose: bool = True, data_prefix: str = "") -> dict:
    data_path = DATA_DIR / f"{data_prefix}{symbol.lower()}_{interval}.csv"
    if not data_path.exists():
        raise SystemExit(f"Missing historical data at {data_path}. Run scripts/fetch_weex_klines.py first.")

    def log(message: str) -> None:
        if verbose:
            print(message)

    periods_per_year = PERIODS_PER_YEAR.get(interval, 365)
    bars = read_market_bars(data_path)
    splits = {split.name: split.bars for split in chronological_split(bars, train_pct=0.5, validation_pct=0.25)}

    winners = {}
    for name, grid_fn in FAMILIES.items():
        log(f"\n=== {symbol} / {name}: grid search on TRAIN ({len(splits['train'])} bars) ===")
        ranked = search_family(name, grid_fn, splits["train"], periods_per_year)
        if not ranked:
            log("  No parameter setting traded enough to evaluate.")
            continue
        log(f"  {len(ranked)} qualifying candidates (>= {MIN_TRADES_TO_QUALIFY} trades, has neighbors)")
        for candidate in ranked[:3]:
            log(
                f"  params={candidate['params']} train_sharpe={candidate['sharpe']:.2f} "
                f"neighbor_avg_sharpe={candidate['neighbor_avg_sharpe']:.2f} "
                f"combined={candidate['combined_score']:.2f} trades={candidate['trade_count']}"
            )
        winners[name] = ranked[0]

    log(f"\n=== {symbol}: Out-of-sample check -- best TRAIN candidate per family, evaluated on VALIDATION ===")
    validation_results = {}
    header = f"{'strategy':<18}{'params':<32}{'train_sharpe':>13}{'val_sharpe':>12}{'val_return':>12}{'val_win_rate':>13}"
    log(header)
    log("-" * len(header))
    for name, candidate in winners.items():
        strategy = factory_for(name, candidate["params"])
        val_result = run(strategy, splits["validation"], periods_per_year)
        validation_results[name] = {"params": candidate["params"], "train": candidate, "validation": val_result}
        val_win_rate = val_result["win_rate"]
        val_win_rate_display = f"{val_win_rate:.1%}" if val_win_rate is not None else "n/a"
        log(
            f"{name:<18}{str(candidate['params']):<32}{candidate['sharpe']:>13.2f}"
            f"{val_result['sharpe_ratio']:>12.2f}{val_result['total_return']:>12.2%}{val_win_rate_display:>13}"
        )

    robust = {
        name: info
        for name, info in validation_results.items()
        if info["train"]["sharpe"] > 0
        and info["validation"]["sharpe_ratio"] > 0
        and info["validation"]["win_rate"] is not None  # require actual closed round trips, not one lucky still-open position
    }

    log(f"\n{len(robust)} of {len(validation_results)} families kept a positive Sharpe on VALIDATION after TRAIN-only tuning.")

    summary = {
        "symbol": symbol,
        "interval": interval,
        "families_tested": len(validation_results),
        "families_robust": len(robust),
        "best_name": None,
        "best_params": None,
        "validation_sharpe": None,
        "test_result": None,
    }

    if robust:
        best_name = max(robust, key=lambda n: robust[n]["validation"]["sharpe_ratio"])
        best = robust[best_name]
        log(f"\nBest candidate surviving VALIDATION: {best_name} {best['params']}")
        log("Running the single reserved TEST check now (spent once, on this winner only)...")
        strategy = factory_for(best_name, best["params"])
        test_result = run(strategy, splits["test"], periods_per_year)
        test_win_rate = test_result["win_rate"]
        test_win_rate_display = f"{test_win_rate:.1%}" if test_win_rate is not None else "n/a"
        log(
            f"TEST: sharpe={test_result['sharpe_ratio']:.2f} return={test_result['total_return']:.2%} "
            f"max_dd={test_result['max_drawdown']:.2%} win_rate={test_win_rate_display} trades={test_result['trade_count']}"
        )
        validation_results[best_name]["test"] = test_result
        summary.update(
            {
                "best_name": best_name,
                "best_params": {k: str(v) for k, v in best["params"].items()},
                "validation_sharpe": best["validation"]["sharpe_ratio"],
                "test_result": test_result,
            }
        )
    else:
        log("\nNo family survived VALIDATION with a positive Sharpe. Not spending the TEST check -- there is nothing to confirm.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / f"parameter_search_{data_prefix}{symbol.lower()}_{interval}.json"
    output_path.write_text(json.dumps(validation_results, indent=2, default=str) + "\n", encoding="utf-8")
    log(f"\nFull results written to {output_path}")
    summary["output_path"] = str(output_path)
    return summary


def main() -> None:
    args = sys.argv[1:]
    data_prefix = ""
    if args and args[0] == "--binance":
        data_prefix = "binance_"
        args = args[1:]
    symbol = args[0] if len(args) > 0 else "btcusdt"
    interval = args[1] if len(args) > 1 else "1d"
    search_symbol(symbol, interval, data_prefix=data_prefix)


if __name__ == "__main__":
    main()
