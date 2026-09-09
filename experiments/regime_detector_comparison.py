"""M2 of the system spec: does the change-point regime detector improve
the one confirmed edge, or does the current rule-based one stay?

Section 8's own standard, quoted directly: "The regime detector is not
successful because it looks mathematically sophisticated. It is
successful if strategy performance improves when using it." This runs
the confirmed BNBUSDT volatility_regime strategy (lookback=21,
vol_ceiling=0.05) unchanged, swapping only the regime detector, across
the same TRAIN/VALIDATION/TEST split the base strategy was validated on.

Usage:
    PYTHONPATH=src python3 experiments/regime_detector_comparison.py
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from omniquantai.application.analytics import PerformanceAnalytics
from omniquantai.application.data_split import chronological_split
from omniquantai.application.engine import PaperTradingEngine
from omniquantai.application.paper_broker import PaperBroker
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.application.regime_changepoint import ChangePointRegimeDetector
from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.application.strategies import VolatilityRegimeStrategy
from omniquantai.configuration.settings import TradingSettings
from omniquantai.infrastructure.market_data import InMemoryMarketDataFeed, read_market_bars

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BASELINE_PARAMS = {"lookback": 21, "vol_ceiling": Decimal("0.05")}


def run(regime_detector, bars) -> dict:
    settings = TradingSettings()
    analytics = PerformanceAnalytics(settings.initial_cash, periods_per_year=365)
    engine = PaperTradingEngine(
        feed=InMemoryMarketDataFeed(bars),
        broker=PaperBroker(settings),
        risk_engine=InstitutionalRiskEngine(settings),
        position_manager=PositionManager(settings.initial_cash),
        strategies=[VolatilityRegimeStrategy(**BASELINE_PARAMS)],
        analytics=analytics,
        regime_detector=regime_detector,
    )
    return asdict(engine.run())


def main() -> None:
    bars = read_market_bars(DATA_DIR / "binance_bnbusdt_1d.csv")
    splits = {s.name: s.bars for s in chronological_split(bars, train_pct=0.5, validation_pct=0.25)}

    detectors = {
        "SimpleRegimeDetector (current)": lambda: SimpleRegimeDetector(lookback=14),
        "ChangePointRegimeDetector (candidate)": lambda: ChangePointRegimeDetector(lookback=30),
    }

    print(f"{'detector':<40}{'train_ret':>11}{'val_ret':>10}{'test_ret':>10}{'test_sharpe':>13}{'test_maxdd':>12}{'test_trades':>13}")
    print("-" * 109)

    results_by_detector = {}
    for name, factory in detectors.items():
        results = {phase: run(factory(), splits[phase]) for phase in ("train", "validation", "test")}
        results_by_detector[name] = results
        print(
            f"{name:<40}"
            f"{results['train']['total_return']:>10.2%} {results['validation']['total_return']:>9.2%} "
            f"{results['test']['total_return']:>9.2%} {results['test']['sharpe_ratio']:>12.2f} "
            f"{results['test']['max_drawdown']:>11.2%} {results['test']['trade_count']:>13}"
        )

    print("\n=== Acceptance check (Section 8's own standard) ===")
    current = results_by_detector["SimpleRegimeDetector (current)"]["test"]
    candidate = results_by_detector["ChangePointRegimeDetector (candidate)"]["test"]
    improves_return = candidate["total_return"] > current["total_return"]
    improves_sharpe = candidate["sharpe_ratio"] > current["sharpe_ratio"]
    improves_drawdown = candidate["max_drawdown"] < current["max_drawdown"]

    print(f"TEST return:    current {current['total_return']:.2%}  vs  candidate {candidate['total_return']:.2%}  -> {'IMPROVED' if improves_return else 'no improvement'}")
    print(f"TEST sharpe:    current {current['sharpe_ratio']:.2f}  vs  candidate {candidate['sharpe_ratio']:.2f}  -> {'IMPROVED' if improves_sharpe else 'no improvement'}")
    print(f"TEST max_dd:    current {current['max_drawdown']:.2%}  vs  candidate {candidate['max_drawdown']:.2%}  -> {'IMPROVED' if improves_drawdown else 'no improvement'}")

    if improves_return and improves_sharpe:
        print("\nCandidate clears the bar on both return and Sharpe -- worth adopting, pending a parameter-stability check on its own lookback/threshold settings.")
    else:
        print("\nCandidate does not clear the bar. Per Section 8: it is not successful because it's more sophisticated. Keep SimpleRegimeDetector.")


if __name__ == "__main__":
    main()
