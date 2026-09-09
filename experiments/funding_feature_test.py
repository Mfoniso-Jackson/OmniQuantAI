"""Section 4/M1 of the system spec: does funding rate improve the one
confirmed edge (BNBUSDT daily volatility_regime), or is it dead weight?

Hypothesis: perpetual funding rate signals crowding. A strongly positive
funding rate means longs are paying shorts heavily -- the market is
long-crowded, raising the risk of a long-squeeze reversal. A strongly
negative rate is the mirror image. So: suppress the base strategy's BUY
signal when funding is extremely positive (crowded long), and suppress
SELL when extremely negative (crowded short), leaving everything else
unchanged.

Data: Binance funding-rate history (4+ years, matches the depth of the
already-confirmed price data), resampled to one average-per-day value to
align with the daily strategy. This is a genuine experiment per Rule 1
(no feature without an experiment) -- ships into the permanent strategy
library only if it clears the same bar as anything else: TRAIN/VALIDATION/
TEST, with the funded variant beating the plain confirmed strategy on the
TEST split, not just looking interesting on TRAIN.

Usage:
    PYTHONPATH=src python3 experiments/funding_feature_test.py
"""

from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from omniquantai.application.analytics import PerformanceAnalytics
from omniquantai.application.data_split import chronological_split
from omniquantai.application.engine import PaperTradingEngine
from omniquantai.application.paper_broker import PaperBroker
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.application.strategies import VolatilityRegimeStrategy
from omniquantai.configuration.settings import TradingSettings
from omniquantai.domain.models import MarketBar, MarketRegime, PortfolioSnapshot, Signal, SignalAction
from omniquantai.infrastructure.market_data import InMemoryMarketDataFeed, read_market_bars

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_daily_funding(symbol: str) -> dict[date, Decimal]:
    path = DATA_DIR / f"binance_{symbol.lower()}_funding.csv"
    by_day: dict[date, list[Decimal]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            day = datetime.fromisoformat(row["timestamp"]).date()
            by_day.setdefault(day, []).append(Decimal(row["funding_rate"]))
    return {day: sum(values) / Decimal(len(values)) for day, values in by_day.items()}


class FundingGatedVolatilityRegime:
    """Wraps VolatilityRegimeStrategy: suppresses a BUY when funding is
    extremely positive (crowded long) and a SELL when extremely negative
    (crowded short). Everything else is delegated unchanged."""

    name = "funding_gated_volatility_regime"

    def __init__(self, inner: VolatilityRegimeStrategy, funding_by_date: dict[date, Decimal], crowd_threshold: Decimal) -> None:
        self.inner = inner
        self.funding_by_date = funding_by_date
        self.crowd_threshold = crowd_threshold

    def on_bar(self, bar: MarketBar, history, regime: MarketRegime, portfolio: PortfolioSnapshot) -> Signal:
        signal = self.inner.on_bar(bar, history, regime, portfolio)
        funding = self.funding_by_date.get(bar.timestamp.date())
        if funding is None or signal.action is SignalAction.HOLD:
            return signal
        if signal.action is SignalAction.BUY and funding > self.crowd_threshold:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), f"Funding-gated: crowded long (funding={funding})")
        if signal.action is SignalAction.SELL and funding < -self.crowd_threshold:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.5"), f"Funding-gated: crowded short (funding={funding})")
        return signal


def run(strategy, bars: list[MarketBar]) -> dict:
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
    symbol = "bnbusdt"
    bars = read_market_bars(DATA_DIR / f"binance_{symbol}_1d.csv")
    funding_by_date = load_daily_funding(symbol)
    print(f"Loaded {len(funding_by_date)} days of funding data for {symbol.upper()}")

    splits = {s.name: s.bars for s in chronological_split(bars, train_pct=0.5, validation_pct=0.25)}

    # Confirmed baseline: lookback=21, vol_ceiling=0.05 (the one edge that
    # survived independently on two datasets).
    baseline_params = {"lookback": 21, "vol_ceiling": Decimal("0.05")}

    print(f"\n{'variant':<38}{'train_ret':>11}{'val_ret':>10}{'test_ret':>10}{'test_sharpe':>13}{'test_trades':>13}")
    header_len = 38 + 11 + 10 + 10 + 13 + 13
    print("-" * header_len)

    baseline_results = {}
    for name in ("train", "validation", "test"):
        baseline_results[name] = run(VolatilityRegimeStrategy(**baseline_params), splits[name])
    print(
        f"{'baseline (no funding gate)':<38}"
        f"{baseline_results['train']['total_return']:>10.2%} {baseline_results['validation']['total_return']:>9.2%} "
        f"{baseline_results['test']['total_return']:>9.2%} {baseline_results['test']['sharpe_ratio']:>12.2f} "
        f"{baseline_results['test']['trade_count']:>13}"
    )

    best_by_threshold = []
    for crowd_threshold in (Decimal("0.0003"), Decimal("0.0005"), Decimal("0.001"), Decimal("0.0015")):
        results = {}
        for name in ("train", "validation", "test"):
            inner = VolatilityRegimeStrategy(**baseline_params)
            strategy = FundingGatedVolatilityRegime(inner, funding_by_date, crowd_threshold)
            results[name] = run(strategy, splits[name])
        label = f"funding-gated (threshold={crowd_threshold})"
        print(
            f"{label:<38}"
            f"{results['train']['total_return']:>10.2%} {results['validation']['total_return']:>9.2%} "
            f"{results['test']['total_return']:>9.2%} {results['test']['sharpe_ratio']:>12.2f} "
            f"{results['test']['trade_count']:>13}"
        )
        best_by_threshold.append((crowd_threshold, results))

    print("\n=== Acceptance check ===")
    beats_baseline = [
        (threshold, r) for threshold, r in best_by_threshold
        if r["test"]["total_return"] > baseline_results["test"]["total_return"]
        and r["test"]["sharpe_ratio"] > baseline_results["test"]["sharpe_ratio"]
    ]
    if beats_baseline:
        print(f"{len(beats_baseline)} of {len(best_by_threshold)} funding-gate thresholds beat the baseline on BOTH TEST return and Sharpe.")
        print("Per the spec's acceptance bar, this is a candidate for the permanent strategy library -- pending a neighbor-stability check across thresholds.")
    else:
        print("No funding-gate threshold beat the baseline on both TEST return and Sharpe.")
        print("Verdict: funding rate does not improve this strategy. Not shipping it -- Rule 1 cuts both ways.")


if __name__ == "__main__":
    main()
