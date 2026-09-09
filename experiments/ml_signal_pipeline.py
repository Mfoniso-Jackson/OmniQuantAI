"""ML signal-generation pipeline: multi-feature, multi-asset pooled model
instead of a hand-coded univariate threshold rule.

Every strategy tested today (momentum, mean_reversion, ma_trend,
volatility_regime, breakout, volatility_expansion) conditions on ONE
feature. This pipeline computes a 14-feature vector per bar
(infrastructure/features.py) and trains a real classifier to predict a
three-class forward-return label (up / down / flat-not-worth-trading,
Section 6's "no trade" as a legitimate output) from the combined feature
interactions no univariate rule can express.

Critical design choice: the model is trained on TRAIN data POOLED across
all 20 assets already gathered today, not fit separately per asset. Any
single asset only has ~700-1,400 daily bars -- too little to fit a model
without serious overfitting risk. Pooling gives ~14,000 training rows and
forces the model to learn patterns that generalize across assets, not
one asset's idiosyncratic noise. The asset identity itself is NOT a
feature, deliberately -- a model that only works because it memorized
"this is BNBUSDT" has learned nothing transferable.

Two models compared, same discipline as every hand-coded strategy today:
- LogisticRegression: simple, linear baseline (Rule 9)
- HistGradientBoostingClassifier: the sophisticated option, only kept if
  it actually beats the simple one

Evaluated two ways:
1. Classification metrics on pooled VALIDATION (sanity check only --
   accuracy alone doesn't mean tradeable)
2. REAL backtested trading performance through the actual
   PaperTradingEngine, per asset, aggregated across all 20 assets on
   VALIDATION, then a single reserved TEST check on whichever model
   survives that -- the only metric that actually matters.

Usage:
    PYTHONPATH=src python3 experiments/ml_signal_pipeline.py
"""

from __future__ import annotations

import statistics
import warnings
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from omniquantai.application.analytics import PerformanceAnalytics
from omniquantai.application.data_split import chronological_split
from omniquantai.application.engine import PaperTradingEngine
from omniquantai.application.paper_broker import PaperBroker
from omniquantai.application.position_manager import PositionManager
from omniquantai.application.regime import SimpleRegimeDetector
from omniquantai.application.risk import InstitutionalRiskEngine
from omniquantai.configuration.settings import TradingSettings
from omniquantai.domain.models import MarketBar, MarketRegime, PortfolioSnapshot, Signal, SignalAction
from omniquantai.infrastructure.features import FEATURE_NAMES, MIN_HISTORY, compute_features, label_forward_return
from omniquantai.infrastructure.market_data import InMemoryMarketDataFeed, read_market_bars

warnings.filterwarnings("ignore")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HORIZON = 5
COST_THRESHOLD = 0.008  # 0.8% -- must clear real trading costs with margin, not just be nonzero

ASSETS = [
    "btcusdt", "ethusdt", "solusdt", "dogeusdt", "xrpusdt", "bnbusdt", "linkusdt", "adausdt",
    "suiusdt", "trxusdt", "1000pepeusdt", "1000shibusdt",
]


def build_dataset(bars_by_asset: dict[str, list[MarketBar]]) -> tuple[np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    labels: list[int] = []
    for bars in bars_by_asset.values():
        for index in range(MIN_HISTORY - 1, len(bars) - HORIZON):
            history = bars[: index + 1]
            features = compute_features(history)
            if features is None:
                continue
            label = label_forward_return(bars, index, HORIZON, COST_THRESHOLD)
            if label is None:
                continue
            rows.append([features[name] for name in FEATURE_NAMES])
            labels.append(label)
    return np.array(rows), np.array(labels)


class MLSignalStrategy:
    """Wraps a trained classifier + optional scaler as a Strategy. Predicts
    the three-class label live (no future data, unlike training) and
    converts it directly to a signal at the project's standard fixed
    target_weight -- comparing pure signal-generation quality against the
    hand-coded strategies, not yet combined with EV sizing (M4 already
    showed that hurts this project's confirmed edge; kept out here to
    isolate what the model itself contributes)."""

    def __init__(self, model, scaler: StandardScaler | None, name: str, target_weight: Decimal = Decimal("0.03")) -> None:
        self.model = model
        self.scaler = scaler
        self.name = name
        self.target_weight = target_weight

    def on_bar(self, bar: MarketBar, history, regime: MarketRegime, portfolio: PortfolioSnapshot) -> Signal:
        features = compute_features(history)
        if features is None:
            return Signal(bar.symbol, SignalAction.HOLD, Decimal("0.2"), "Insufficient history for ML features")
        vector = np.array([[features[name] for name in FEATURE_NAMES]])
        if self.scaler is not None:
            vector = self.scaler.transform(vector)
        prediction = self.model.predict(vector)[0]
        probabilities = self.model.predict_proba(vector)[0]
        confidence = Decimal(str(round(max(probabilities), 4)))

        if prediction == 1:
            return Signal(bar.symbol, SignalAction.BUY, confidence, "ML model predicts forward move clears cost threshold to the upside", self.target_weight)
        if prediction == -1:
            return Signal(bar.symbol, SignalAction.SELL, confidence, "ML model predicts forward move clears cost threshold to the downside", -self.target_weight)
        return Signal(bar.symbol, SignalAction.HOLD, confidence, "ML model predicts no move worth trading net of costs")


def run_backtest(strategy_factory, bars: list[MarketBar]) -> dict:
    settings = TradingSettings()
    analytics = PerformanceAnalytics(settings.initial_cash, periods_per_year=365)
    engine = PaperTradingEngine(
        feed=InMemoryMarketDataFeed(bars),
        broker=PaperBroker(settings),
        risk_engine=InstitutionalRiskEngine(settings),
        position_manager=PositionManager(settings.initial_cash),
        strategies=[strategy_factory()],
        analytics=analytics,
        regime_detector=SimpleRegimeDetector(lookback=14),
    )
    return asdict(engine.run())


def main() -> None:
    print(f"Loading {len(ASSETS)} assets' deep daily data and building TRAIN/VALIDATION/TEST splits...")
    splits_by_asset = {}
    for asset in ASSETS:
        path = DATA_DIR / f"binance_{asset}_1d.csv"
        if not path.exists():
            print(f"  skipping {asset}: no data at {path}")
            continue
        bars = read_market_bars(path)
        splits_by_asset[asset] = {s.name: s.bars for s in chronological_split(bars, train_pct=0.5, validation_pct=0.25)}

    train_bars_by_asset = {asset: splits["train"] for asset, splits in splits_by_asset.items()}
    X_train, y_train = build_dataset(train_bars_by_asset)
    print(f"Pooled TRAIN dataset: {X_train.shape[0]} rows from {len(train_bars_by_asset)} assets, label distribution {dict(zip(*np.unique(y_train, return_counts=True)))}")

    scaler = StandardScaler().fit(X_train)
    X_train_scaled = scaler.transform(X_train)

    logistic = LogisticRegression(class_weight="balanced", max_iter=2000).fit(X_train_scaled, y_train)
    gbm = HistGradientBoostingClassifier(max_depth=4, max_iter=150, l2_regularization=1.0, class_weight="balanced").fit(X_train, y_train)

    val_bars_by_asset = {asset: splits["validation"] for asset, splits in splits_by_asset.items()}
    X_val, y_val = build_dataset(val_bars_by_asset)
    X_val_scaled = scaler.transform(X_val)

    print("\n=== Pooled VALIDATION classification accuracy (sanity check only) ===")
    for name, model, X in (("LogisticRegression", logistic, X_val_scaled), ("HistGradientBoosting", gbm, X_val)):
        predictions = model.predict(X)
        accuracy = (predictions == y_val).mean()
        nonflat_mask = predictions != 0
        nonflat_accuracy = (predictions[nonflat_mask] == y_val[nonflat_mask]).mean() if nonflat_mask.any() else float("nan")
        print(f"{name:<24} overall_accuracy={accuracy:.2%}  accuracy_when_predicting_a_direction={nonflat_accuracy:.2%}  trades_predicted={nonflat_mask.sum()}/{len(y_val)}")

    print("\n=== Real backtested trading performance, per model, aggregated across all assets ===")
    models = {
        "logistic_regression": lambda: MLSignalStrategy(logistic, scaler, "ml_logistic"),
        "gradient_boosting": lambda: MLSignalStrategy(gbm, None, "ml_gbm"),
    }

    summary_by_model = {}
    for model_name, factory in models.items():
        print(f"\n--- {model_name} ---")
        val_returns, val_sharpes = [], []
        for asset, splits in splits_by_asset.items():
            result = run_backtest(factory, splits["validation"])
            val_returns.append(result["total_return"])
            val_sharpes.append(result["sharpe_ratio"])
            print(f"  {asset:<16} val_return={result['total_return']:>9.2%}  val_sharpe={result['sharpe_ratio']:>7.2f}  trades={result['trade_count']:>4}")
        mean_return = statistics.mean(float(r) for r in val_returns)
        mean_sharpe = statistics.mean(float(s) for s in val_sharpes)
        positive_count = sum(1 for r in val_returns if r > 0)
        summary_by_model[model_name] = {"mean_return": mean_return, "mean_sharpe": mean_sharpe, "positive_count": positive_count, "n": len(val_returns)}
        print(f"  AGGREGATE: mean_return={mean_return:.2%}  mean_sharpe={mean_sharpe:.2f}  positive_assets={positive_count}/{len(val_returns)}")

    print("\n=== Acceptance check ===")
    best_model_name = max(summary_by_model, key=lambda n: summary_by_model[n]["mean_sharpe"])
    best = summary_by_model[best_model_name]
    print(f"Best on VALIDATION: {best_model_name} (mean_sharpe={best['mean_sharpe']:.2f}, mean_return={best['mean_return']:.2%}, {best['positive_count']}/{best['n']} assets positive)")

    if best["mean_sharpe"] > 0 and best["positive_count"] > best["n"] / 2:
        print("Clears a minimal bar (positive mean Sharpe, majority of assets positive) -- running the single reserved TEST check.")
        factory = models[best_model_name]
        test_returns, test_sharpes = [], []
        for asset, splits in splits_by_asset.items():
            result = run_backtest(factory, splits["test"])
            test_returns.append(result["total_return"])
            test_sharpes.append(result["sharpe_ratio"])
        mean_test_return = statistics.mean(float(r) for r in test_returns)
        mean_test_sharpe = statistics.mean(float(s) for s in test_sharpes)
        positive_test = sum(1 for r in test_returns if r > 0)
        print(f"TEST: mean_return={mean_test_return:.2%}  mean_sharpe={mean_test_sharpe:.2f}  positive_assets={positive_test}/{len(test_returns)}")
    else:
        print("Does not clear even a minimal bar on VALIDATION. Not spending the TEST check -- there is nothing to confirm.")


if __name__ == "__main__":
    main()
