"""M5: does running the confirmed signals as ONE coordinated portfolio
(shared cash, shared risk budget, correlation-aware sizing) actually beat
treating them as independent, uncoordinated books -- the real acceptance
test for a portfolio layer, not just "can we build one."

Routes BNBUSDT to its dedicated hand-validated volatility_regime signal
and the other 11 crypto assets to the pooled ML model (both confirmed
separately today), then compares three configurations on the SAME
multi-asset, chronologically-merged VALIDATION and TEST periods:

1. independent   -- each asset backtested alone with its own $100k
                     (the naive sum/average already reported earlier)
2. portfolio      -- one shared $100k book, gross-exposure risk engine
                     already built, just never fed multi-symbol data
3. portfolio+corr -- (2) plus CorrelationAwareRiskEngine, rejecting a new
                     position that's highly correlated with one already
                     open

The ML model here is the TRAIN-only-fit version (matching the original
walk-forward validation), NOT the all-history production model saved for
live monitoring -- this backtest reports historical performance, which
must never see data from its own future.

Usage:
    PYTHONPATH=src python3 experiments/portfolio_backtest.py
"""

from __future__ import annotations

import warnings
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from omniquantai.application.analytics import PerformanceAnalytics
from omniquantai.application.data_split import chronological_split
from omniquantai.application.engine import PaperTradingEngine
from omniquantai.application.paper_broker import PaperBroker
from omniquantai.application.portfolio import CorrelationAwareRiskEngine, SymbolRoutedStrategy, compute_correlation_matrix
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.application.strategies import VolatilityRegimeStrategy
from omniquantai.configuration.settings import TradingSettings
from omniquantai.infrastructure.market_data import read_market_bars
from omniquantai.infrastructure.multi_symbol_feed import MultiSymbolMarketDataFeed

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ml_signal_pipeline import ASSETS, DATA_DIR, MLSignalStrategy, build_dataset  # noqa: E402

warnings.filterwarnings("ignore")

BNB_SYMBOL = "BNBUSDT"


def build_routes(logistic, scaler, assets: list[str]) -> dict[str, object]:
    routes: dict[str, object] = {}
    for asset in assets:
        symbol = asset.upper()
        if symbol == BNB_SYMBOL:
            routes[symbol] = VolatilityRegimeStrategy(lookback=21, vol_ceiling=Decimal("0.05"))
        else:
            routes[symbol] = MLSignalStrategy(logistic, scaler, f"ml_{asset}")
    return routes


def run_independent(routes: dict, bars_by_symbol: dict[str, list]) -> dict:
    returns, sharpes, max_dds = [], [], []
    for symbol, bars in bars_by_symbol.items():
        settings = TradingSettings()
        analytics = PerformanceAnalytics(settings.initial_cash, periods_per_year=365)
        engine = PaperTradingEngine(
            feed=_single_feed(bars),
            broker=PaperBroker(settings),
            risk_engine=InstitutionalRiskEngine(settings),
            position_manager=PositionManager(settings.initial_cash),
            strategies=[routes[symbol]],
            analytics=analytics,
            regime_detector=SimpleRegimeDetector(lookback=14),
        )
        report = engine.run()
        returns.append(float(report.total_return))
        sharpes.append(float(report.sharpe_ratio))
        max_dds.append(float(report.max_drawdown))
    return {"mean_return": sum(returns) / len(returns), "mean_sharpe": sum(sharpes) / len(sharpes), "mean_max_dd": sum(max_dds) / len(max_dds)}


def _single_feed(bars):
    from omniquantai.infrastructure.market_data import InMemoryMarketDataFeed

    return InMemoryMarketDataFeed(bars)


def run_portfolio(routes: dict, bars_by_symbol: dict[str, list], correlation_matrix: dict | None) -> dict:
    settings = TradingSettings()
    analytics = PerformanceAnalytics(settings.initial_cash, periods_per_year=365)
    position_manager = PositionManager(settings.initial_cash)
    base_risk_engine = InstitutionalRiskEngine(settings)
    risk_engine = (
        CorrelationAwareRiskEngine(base_risk_engine, position_manager, correlation_matrix) if correlation_matrix is not None else base_risk_engine
    )
    engine = PaperTradingEngine(
        feed=MultiSymbolMarketDataFeed(bars_by_symbol),
        broker=PaperBroker(settings),
        risk_engine=risk_engine,
        position_manager=position_manager,
        strategies=[SymbolRoutedStrategy(routes)],
        analytics=analytics,
        regime_detector=SimpleRegimeDetector(lookback=14),
    )
    report = engine.run()
    return {"return": float(report.total_return), "sharpe": float(report.sharpe_ratio), "max_dd": float(report.max_drawdown), "trades": report.trade_count}


def main() -> None:
    print(f"Loading {len(ASSETS)} assets and building splits...")
    splits_by_asset = {}
    for asset in ASSETS:
        path = DATA_DIR / f"binance_{asset}_1d.csv"
        if not path.exists():
            continue
        bars = read_market_bars(path)
        splits_by_asset[asset] = {s.name: s.bars for s in chronological_split(bars, train_pct=0.5, validation_pct=0.25)}

    train_bars_by_asset = {a: s["train"] for a, s in splits_by_asset.items()}
    X_train, y_train = build_dataset(train_bars_by_asset)
    scaler = StandardScaler().fit(X_train)
    logistic = LogisticRegression(class_weight="balanced", max_iter=2000).fit(scaler.transform(X_train), y_train)

    correlation_matrix = compute_correlation_matrix({a.upper(): bars for a, bars in train_bars_by_asset.items()})
    routes = build_routes(logistic, scaler, list(splits_by_asset.keys()))

    print(f"\n{'phase':<12}{'configuration':<20}{'return':>10}{'sharpe':>9}{'max_dd':>9}{'trades':>8}")
    print("-" * 68)

    results = {}
    for phase in ("validation",):
        bars_by_symbol = {asset.upper(): splits["validation"] for asset, splits in splits_by_asset.items()}

        independent = run_independent(routes, bars_by_symbol)
        print(f"{phase:<12}{'independent':<20}{independent['mean_return']:>9.2%} {independent['mean_sharpe']:>8.2f} {independent['mean_max_dd']:>8.2%}{'--':>8}")

        portfolio_plain = run_portfolio(routes, bars_by_symbol, correlation_matrix=None)
        print(f"{phase:<12}{'portfolio':<20}{portfolio_plain['return']:>9.2%} {portfolio_plain['sharpe']:>8.2f} {portfolio_plain['max_dd']:>8.2%}{portfolio_plain['trades']:>8}")

        portfolio_corr = run_portfolio(routes, bars_by_symbol, correlation_matrix=correlation_matrix)
        print(f"{phase:<12}{'portfolio+corr':<20}{portfolio_corr['return']:>9.2%} {portfolio_corr['sharpe']:>8.2f} {portfolio_corr['max_dd']:>8.2%}{portfolio_corr['trades']:>8}")

        results[phase] = {"independent": independent, "portfolio": portfolio_plain, "portfolio_corr": portfolio_corr}

    print("\n=== Acceptance check (VALIDATION) ===")
    val = results["validation"]
    print(f"Coordinating as one portfolio vs independent books: max_dd {val['independent']['mean_max_dd']:.2%} -> {val['portfolio']['max_dd']:.2%}")
    print(f"Adding correlation-awareness on top: max_dd {val['portfolio']['max_dd']:.2%} -> {val['portfolio_corr']['max_dd']:.2%}, return {val['portfolio']['return']:.2%} -> {val['portfolio_corr']['return']:.2%}")

    corr_helps = val["portfolio_corr"]["max_dd"] <= val["portfolio"]["max_dd"] and val["portfolio_corr"]["sharpe"] >= val["portfolio"]["sharpe"]
    if corr_helps:
        print("\nCorrelation-awareness clears the bar on VALIDATION -- running the single reserved TEST check.")
        bars_by_symbol_test = {asset.upper(): splits["test"] for asset, splits in splits_by_asset.items()}
        test_independent = run_independent(routes, bars_by_symbol_test)
        test_portfolio = run_portfolio(routes, bars_by_symbol_test, correlation_matrix=None)
        test_portfolio_corr = run_portfolio(routes, bars_by_symbol_test, correlation_matrix=correlation_matrix)
        print(f"TEST independent:     mean_return={test_independent['mean_return']:.2%} mean_sharpe={test_independent['mean_sharpe']:.2f} mean_max_dd={test_independent['mean_max_dd']:.2%}")
        print(f"TEST portfolio:       return={test_portfolio['return']:.2%} sharpe={test_portfolio['sharpe']:.2f} max_dd={test_portfolio['max_dd']:.2%}")
        print(f"TEST portfolio+corr:  return={test_portfolio_corr['return']:.2%} sharpe={test_portfolio_corr['sharpe']:.2f} max_dd={test_portfolio_corr['max_dd']:.2%}")
    else:
        print("\nCorrelation-awareness does not clear the bar on VALIDATION (no drawdown improvement without hurting Sharpe). Not spending the TEST check on it.")
        print("Still reporting whether plain portfolio coordination alone (no correlation logic) beats independent books, since that's a separate, already-decided comparison above.")


if __name__ == "__main__":
    main()
