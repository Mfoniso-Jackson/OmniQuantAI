"""Search for a genuine INTRADAY edge, at hourly granularity, for actual
day-trading use in the competition.

Everything validated so far (BNBUSDT/volatility_regime) is a daily-bar
swing signal -- it trades on the order of once every several days, not a
day-trading cadence. The one earlier look at hourly data was invalid: with
only 1000 hourly bars (~41.6 days) available from WEEX's public endpoint,
a TRAIN/VALIDATION/TEST split gives each phase only ~10 days, and
annualizing a 10-day Sharpe with sqrt(365*24) inflates ordinary noise into
numbers that look like skill (e.g. an actual 0.6% return over 5 days
reporting as "Sharpe 6"). That is a measurement artifact, not a signal.

This script fixes the methodology rather than the data (WEEX's endpoint
caps history regardless of interval, so more calendar days at hourly
resolution isn't available): selection is by RAW total return, win rate,
and profit factor over each split -- metrics that don't need annualizing
to be meaningful -- with annualized Sharpe reported only as supplementary
context, clearly labelled with the window length so it can't be misread
the way it was last time. The neighbor-stability check (a real edge sits
in a plateau, not an isolated spike -- Section 11) is run on raw return
instead of Sharpe for the same reason.

Parameter grids are rescaled for hourly dynamics (smaller thresholds,
shorter lookbacks in hours rather than days) versus the daily-bar search
in parameter_search.py.

Usage:
    PYTHONPATH=src python3 experiments/day_trading_search.py [symbol]
"""

from __future__ import annotations

import json
import statistics
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from omniquantai.application.analytics import PerformanceAnalytics
from omniquantai.application.data_split import chronological_split
from omniquantai.application.engine import PaperTradingEngine
from omniquantai.application.paper_broker import PaperBroker
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.application.strategies import (
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
PERIODS_PER_YEAR = 365 * 24
MIN_TRADES_TO_QUALIFY = 8  # need real activity to trust return/win-rate at all


def momentum_grid():
    for lookback in (4, 8, 12, 24, 48):
        for threshold in (Decimal("0.005"), Decimal("0.01"), Decimal("0.02")):
            yield {"lookback": lookback, "threshold": threshold}, lambda lb=lookback, th=threshold: MomentumStrategy(lookback=lb, threshold=th)


def mean_reversion_grid():
    for lookback in (6, 12, 24, 48, 72):
        for threshold in (Decimal("0.003"), Decimal("0.005"), Decimal("0.01"), Decimal("0.015")):
            yield {"lookback": lookback, "threshold": threshold}, lambda lb=lookback, th=threshold: MeanReversionStrategy(lookback=lb, threshold=th)


def ma_trend_grid():
    for fast, slow in ((4, 12), (6, 24), (12, 24), (12, 48), (24, 72)):
        yield {"fast": fast, "slow": slow}, lambda f=fast, s=slow: MovingAverageTrendStrategy(fast=f, slow=s)


def volatility_regime_grid():
    for lookback in (12, 24, 48, 72):
        for vol_ceiling in (Decimal("0.005"), Decimal("0.01"), Decimal("0.02")):
            yield {"lookback": lookback, "vol_ceiling": vol_ceiling}, lambda lb=lookback, vc=vol_ceiling: VolatilityRegimeStrategy(lookback=lb, vol_ceiling=vc)


FAMILIES = {
    "momentum": momentum_grid,
    "mean_reversion": mean_reversion_grid,
    "ma_trend": ma_trend_grid,
    "volatility_regime": volatility_regime_grid,
}


def run(strategy, bars: list[MarketBar]) -> dict:
    settings = TradingSettings()
    analytics = PerformanceAnalytics(settings.initial_cash, periods_per_year=PERIODS_PER_YEAR)
    engine = PaperTradingEngine(
        feed=InMemoryMarketDataFeed(bars),
        broker=PaperBroker(settings),
        risk_engine=InstitutionalRiskEngine(settings),
        position_manager=PositionManager(settings.initial_cash),
        strategies=[strategy],
        analytics=analytics,
        regime_detector=SimpleRegimeDetector(lookback=24),
    )
    report = asdict(engine.run())
    report["bars_evaluated"] = len(bars)
    report["days_evaluated"] = round(len(bars) / 24, 1)
    report["trades_per_day"] = round(report["trade_count"] / max(report["days_evaluated"], 0.01), 2)
    return report


def factory_for(name: str, params: dict):
    if name == "momentum":
        return MomentumStrategy(lookback=params["lookback"], threshold=params["threshold"])
    if name == "mean_reversion":
        return MeanReversionStrategy(lookback=params["lookback"], threshold=params["threshold"])
    if name == "ma_trend":
        return MovingAverageTrendStrategy(fast=params["fast"], slow=params["slow"])
    if name == "volatility_regime":
        return VolatilityRegimeStrategy(lookback=params["lookback"], vol_ceiling=params["vol_ceiling"])
    raise ValueError(name)


def param_grid_values(candidates: list[dict]) -> dict[str, list]:
    values: dict[str, set] = {}
    for candidate in candidates:
        for key, value in candidate["params"].items():
            values.setdefault(key, set()).add(value)
    return {key: sorted(vals, key=str) for key, vals in values.items()}


def neighbor_average_return(candidate: dict, all_candidates: list[dict], grid_values: dict[str, list]) -> float | None:
    scores = []
    for dim, values in grid_values.items():
        current = candidate["params"][dim]
        idx = values.index(current)
        for neighbor_idx in (idx - 1, idx + 1):
            if 0 <= neighbor_idx < len(values):
                neighbor_params = dict(candidate["params"])
                neighbor_params[dim] = values[neighbor_idx]
                match = next((c for c in all_candidates if c["params"] == neighbor_params), None)
                if match is not None and match["trade_count"] >= MIN_TRADES_TO_QUALIFY:
                    scores.append(match["return"])
    return statistics.mean(scores) if scores else None


def search_family(name: str, grid_fn, train_bars: list[MarketBar]) -> list[dict]:
    candidates = []
    for params, factory in grid_fn():
        result = run(factory(), train_bars)
        candidates.append(
            {
                "params": params,
                "return": result["total_return"],
                "sharpe_annualized": result["sharpe_ratio"],
                "max_drawdown": result["max_drawdown"],
                "win_rate": result["win_rate"],
                "profit_factor": result["profit_factor"],
                "trade_count": result["trade_count"],
                "trades_per_day": result["trades_per_day"],
            }
        )

    grid_values = param_grid_values(candidates)
    for candidate in candidates:
        candidate["neighbor_avg_return"] = neighbor_average_return(candidate, candidates, grid_values)

    qualified = [c for c in candidates if c["trade_count"] >= MIN_TRADES_TO_QUALIFY and c["neighbor_avg_return"] is not None]
    for candidate in qualified:
        candidate["combined_score"] = 0.5 * float(candidate["return"]) + 0.5 * float(candidate["neighbor_avg_return"])

    qualified.sort(key=lambda c: c["combined_score"], reverse=True)
    return qualified


def search_symbol(symbol: str, verbose: bool = True) -> dict:
    data_path = DATA_DIR / f"{symbol.lower()}_1h.csv"
    if not data_path.exists():
        raise SystemExit(f"Missing hourly data at {data_path}. Run scripts/fetch_weex_klines.py first.")

    def log(message: str) -> None:
        if verbose:
            print(message)

    bars = read_market_bars(data_path)
    splits = {s.name: s.bars for s in chronological_split(bars, train_pct=0.5, validation_pct=0.25)}
    log(f"\n{symbol}: TRAIN={len(splits['train'])} bars ({len(splits['train'])/24:.1f}d), "
        f"VALIDATION={len(splits['validation'])} bars ({len(splits['validation'])/24:.1f}d), "
        f"TEST={len(splits['test'])} bars ({len(splits['test'])/24:.1f}d)")

    winners = {}
    for name, grid_fn in FAMILIES.items():
        ranked = search_family(name, grid_fn, splits["train"])
        if not ranked:
            log(f"  {name}: no parameter setting traded enough to evaluate")
            continue
        best = ranked[0]
        log(
            f"  {name}: best TRAIN params={best['params']} return={best['return']:.2%} "
            f"neighbor_avg_return={best['neighbor_avg_return']:.2%} trades/day={best['trades_per_day']:.1f} "
            f"(annualized sharpe {best['sharpe_annualized']:.2f} -- reference only, window is short)"
        )
        winners[name] = best

    log(f"\n{symbol}: Out-of-sample check -- best TRAIN candidate per family, evaluated on VALIDATION")
    validation_results = {}
    for name, candidate in winners.items():
        strategy = factory_for(name, candidate["params"])
        val_result = run(strategy, splits["validation"])
        validation_results[name] = {"params": candidate["params"], "train": candidate, "validation": val_result}
        val_win_rate = val_result["win_rate"]
        val_win_rate_display = f"{val_win_rate:.1%}" if val_win_rate is not None else "n/a (no closed trades)"
        log(
            f"  {name}: val_return={val_result['total_return']:.2%} val_win_rate={val_win_rate_display} "
            f"val_profit_factor={val_result['profit_factor']} val_trades/day={val_result['trades_per_day']:.1f}"
        )

    robust = {
        name: info
        for name, info in validation_results.items()
        if info["train"]["return"] > 0
        and info["validation"]["total_return"] > 0
        and info["validation"]["trade_count"] >= MIN_TRADES_TO_QUALIFY
        and info["validation"]["win_rate"] is not None  # require actual closed round trips, not one lucky still-open position
    }

    summary = {
        "symbol": symbol,
        "families_tested": len(validation_results),
        "families_robust": len(robust),
        "best_name": None,
        "best_params": None,
        "test_result": None,
    }

    if robust:
        best_name = max(robust, key=lambda n: robust[n]["validation"]["total_return"])
        best = robust[best_name]
        strategy = factory_for(best_name, best["params"])
        test_result = run(strategy, splits["test"])
        test_win_rate = test_result["win_rate"]
        test_win_rate_display = f"{test_win_rate:.1%}" if test_win_rate is not None else "n/a (no closed trades)"
        log(
            f"\n{symbol}: best surviving VALIDATION -- {best_name} {best['params']}. "
            f"TEST: return={test_result['total_return']:.2%} win_rate={test_win_rate_display} "
            f"trades/day={test_result['trades_per_day']:.1f} profit_factor={test_result['profit_factor']}"
        )
        validation_results[best_name]["test"] = test_result
        summary.update(
            {
                "best_name": best_name,
                "best_params": {k: str(v) for k, v in best["params"].items()},
                "test_result": test_result,
            }
        )
    else:
        log(f"\n{symbol}: nothing survived VALIDATION with positive return and enough trades.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / f"day_trading_search_{symbol.lower()}.json"
    output_path.write_text(json.dumps(validation_results, indent=2, default=str) + "\n", encoding="utf-8")
    summary["output_path"] = str(output_path)
    return summary


def main() -> None:
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["btcusdt", "ethusdt", "solusdt", "dogeusdt", "xrpusdt", "bnbusdt", "linkusdt", "adausdt"]
    summaries = [search_symbol(symbol) for symbol in symbols]

    print("\n=== Consolidated day-trading search results ===")
    header = f"{'symbol':<12}{'robust_families':>16}{'best_strategy':<20}{'test_return':>12}{'test_trades/day':>17}"
    print(header)
    print("-" * len(header))
    for summary in summaries:
        test_return = summary["test_result"]["total_return"] if summary["test_result"] else None
        test_tpd = summary["test_result"]["trades_per_day"] if summary["test_result"] else None
        print(
            f"{summary['symbol']:<12}{summary['families_robust']:>16}{(summary['best_name'] or '-'):<20}"
            f"{(f'{test_return:.2%}' if test_return is not None else '-'):>12}"
            f"{(f'{test_tpd:.2f}' if test_tpd is not None else '-'):>17}"
        )


if __name__ == "__main__":
    main()
