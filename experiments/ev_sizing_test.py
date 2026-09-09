"""M4 of the system spec: does EV-driven sizing improve the one confirmed
edge, or is it dead weight -- the exact same question asked of every
other enhancement tried today (funding rate, change-point regime
detection), both of which failed. This one gets no special treatment.

Compares the confirmed BNBUSDT volatility_regime strategy (lookback=21,
vol_ceiling=0.05) unweighted against the same strategy wrapped in
EVSizedStrategy, on the identical TRAIN/VALIDATION/TEST split.

Usage:
    PYTHONPATH=src python3 experiments/ev_sizing_test.py
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from omniquantai.application.analytics import PerformanceAnalytics
from omniquantai.application.data_split import chronological_split
from omniquantai.application.engine import PaperTradingEngine
from omniquantai.application.ev_sizing import EVSizedStrategy
from omniquantai.application.paper_broker import PaperBroker
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.application.strategies import VolatilityRegimeStrategy
from omniquantai.configuration.settings import TradingSettings
from omniquantai.infrastructure.market_data import InMemoryMarketDataFeed, read_market_bars

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BASELINE_PARAMS = {"lookback": 21, "vol_ceiling": Decimal("0.05")}


def run(strategy, bars) -> dict:
    settings = TradingSettings()
    analytics = PerformanceAnalytics(settings.initial_cash, periods_per_year=365)
    engine = PaperTradingEngine(
        feed=InMemoryMarketDataFeed(bars),
        broker=PaperBroker(settings),
        risk_engine=InstitutionalRiskEngine(settings),
        position_manager=PositionManager(settings.initial_cash),
        strategies=[strategy],
        analytics=analytics,
        regime_detector=SimpleRegimeDetector(lookback=14),
    )
    return asdict(engine.run())


def main() -> None:
    bars = read_market_bars(DATA_DIR / "binance_bnbusdt_1d.csv")
    splits = {s.name: s.bars for s in chronological_split(bars, train_pct=0.5, validation_pct=0.25)}

    variants = {
        "baseline (fixed sizing)": lambda: VolatilityRegimeStrategy(**BASELINE_PARAMS),
        "EV-sized (fractional Kelly)": lambda: EVSizedStrategy(VolatilityRegimeStrategy(**BASELINE_PARAMS)),
    }

    print(f"{'variant':<32}{'train_ret':>11}{'val_ret':>10}{'test_ret':>10}{'test_sharpe':>13}{'test_maxdd':>12}{'test_trades':>13}")
    print("-" * 101)

    results_by_variant = {}
    for name, factory in variants.items():
        results = {phase: run(factory(), splits[phase]) for phase in ("train", "validation", "test")}
        results_by_variant[name] = results
        print(
            f"{name:<32}"
            f"{results['train']['total_return']:>10.2%} {results['validation']['total_return']:>9.2%} "
            f"{results['test']['total_return']:>9.2%} {results['test']['sharpe_ratio']:>12.2f} "
            f"{results['test']['max_drawdown']:>11.2%} {results['test']['trade_count']:>13}"
        )

    print("\n=== Acceptance check ===")
    baseline = results_by_variant["baseline (fixed sizing)"]["test"]
    ev_sized = results_by_variant["EV-sized (fractional Kelly)"]["test"]
    improves_return = ev_sized["total_return"] > baseline["total_return"]
    improves_sharpe = ev_sized["sharpe_ratio"] > baseline["sharpe_ratio"]
    improves_drawdown = ev_sized["max_drawdown"] <= baseline["max_drawdown"]

    print(f"TEST return:    baseline {baseline['total_return']:.2%}  vs  EV-sized {ev_sized['total_return']:.2%}  -> {'IMPROVED' if improves_return else 'no improvement'}")
    print(f"TEST sharpe:    baseline {baseline['sharpe_ratio']:.2f}  vs  EV-sized {ev_sized['sharpe_ratio']:.2f}  -> {'IMPROVED' if improves_sharpe else 'no improvement'}")
    print(f"TEST max_dd:    baseline {baseline['max_drawdown']:.2%}  vs  EV-sized {ev_sized['max_drawdown']:.2%}  -> {'IMPROVED (or equal)' if improves_drawdown else 'worse'}")

    if improves_return and improves_sharpe:
        print("\nEV-sizing clears the bar on both return and Sharpe -- adopt for the confirmed BNBUSDT signal.")
    else:
        print("\nEV-sizing does not clear the bar. Keep the fixed-sizing baseline.")


if __name__ == "__main__":
    main()
