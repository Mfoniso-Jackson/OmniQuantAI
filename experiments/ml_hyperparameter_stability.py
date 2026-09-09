"""Stress-test the ML signal pipeline's own hyperparameters (label horizon
and cost threshold) for neighbor-stability -- the one piece of rigor the
ML finding hasn't had yet. Every hand-coded strategy today was grid-
checked against neighboring parameter values before being trusted
(Section 11: an isolated spike with worse neighbors on every side is
noise, not edge). The ML pipeline's horizon=5 days / cost_threshold=0.8%
was a reasonable starting choice, never actually checked against nearby
values the same way.

Sweeps each axis independently around the original point (full 2D
cross-product would mean ~16 combinations x 12-asset backtests each --
too slow to be worth it when the real question is just "is this an
isolated lucky pick"). For each hyperparameter setting: rebuild the
pooled TRAIN dataset with that label definition, fit a fresh
LogisticRegression, evaluate via the real trading engine (aggregate
across 12 assets) on VALIDATION. A genuinely stable finding should show
positive aggregate Sharpe across a range of nearby settings, not just
the one point already reported.

Usage:
    PYTHONPATH=src python3 experiments/ml_hyperparameter_stability.py
"""

from __future__ import annotations

import statistics
import warnings
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ml_signal_pipeline import ASSETS, DATA_DIR, MLSignalStrategy, run_backtest  # noqa: E402

from omniquantai.application.data_split import chronological_split  # noqa: E402
from omniquantai.infrastructure.features import FEATURE_NAMES, MIN_HISTORY, compute_features, label_forward_return  # noqa: E402
from omniquantai.infrastructure.market_data import read_market_bars  # noqa: E402

ORIGINAL_HORIZON = 5
ORIGINAL_COST_THRESHOLD = 0.008


def build_dataset_for(bars_by_asset: dict, horizon: int, cost_threshold: float) -> tuple[np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    labels: list[int] = []
    for bars in bars_by_asset.values():
        for index in range(MIN_HISTORY - 1, len(bars) - horizon):
            history = bars[: index + 1]
            features = compute_features(history)
            if features is None:
                continue
            label = label_forward_return(bars, index, horizon, cost_threshold)
            if label is None:
                continue
            rows.append([features[name] for name in FEATURE_NAMES])
            labels.append(label)
    return np.array(rows), np.array(labels)


def evaluate(horizon: int, cost_threshold: float, splits_by_asset: dict) -> dict:
    train_bars = {a: s["train"] for a, s in splits_by_asset.items()}
    X_train, y_train = build_dataset_for(train_bars, horizon, cost_threshold)
    if len(set(y_train)) < 2:
        return {"mean_return": float("nan"), "mean_sharpe": float("nan"), "positive": 0, "n": len(splits_by_asset)}

    scaler = StandardScaler().fit(X_train)
    model = LogisticRegression(class_weight="balanced", max_iter=2000).fit(scaler.transform(X_train), y_train)

    returns, sharpes = [], []
    for asset, splits in splits_by_asset.items():
        strategy = MLSignalStrategy(model, scaler, f"ml_{asset}_h{horizon}_c{cost_threshold}")
        result = run_backtest(lambda s=strategy: s, splits["validation"])
        returns.append(float(result["total_return"]))
        sharpes.append(float(result["sharpe_ratio"]))

    return {
        "mean_return": statistics.mean(returns),
        "mean_sharpe": statistics.mean(sharpes),
        "positive": sum(1 for r in returns if r > 0),
        "n": len(returns),
    }


def main() -> None:
    print(f"Loading {len(ASSETS)} assets...")
    splits_by_asset = {}
    for asset in ASSETS:
        path = DATA_DIR / f"binance_{asset}_1d.csv"
        if not path.exists():
            continue
        bars = read_market_bars(path)
        splits_by_asset[asset] = {s.name: s.bars for s in chronological_split(bars, train_pct=0.5, validation_pct=0.25)}

    print(f"\n{'axis':<10}{'value':>10}{'mean_return':>13}{'mean_sharpe':>13}{'positive_assets':>17}")
    print("-" * 63)

    results = {}

    print(f"{'horizon':<10}{ORIGINAL_HORIZON:>10}", end="")
    base = evaluate(ORIGINAL_HORIZON, ORIGINAL_COST_THRESHOLD, splits_by_asset)
    print(f"{base['mean_return']:>12.2%}{base['mean_sharpe']:>13.2f}{base['positive']:>13}/{base['n']}")
    results[("horizon", ORIGINAL_HORIZON)] = base

    for horizon in (3, 7, 10):
        result = evaluate(horizon, ORIGINAL_COST_THRESHOLD, splits_by_asset)
        results[("horizon", horizon)] = result
        print(f"{'horizon':<10}{horizon:>10}{result['mean_return']:>12.2%}{result['mean_sharpe']:>13.2f}{result['positive']:>13}/{result['n']}")

    for cost_threshold in (0.005, 0.01, 0.015):
        result = evaluate(ORIGINAL_HORIZON, cost_threshold, splits_by_asset)
        results[("cost_threshold", cost_threshold)] = result
        print(f"{'cost_thr':<10}{cost_threshold:>10}{result['mean_return']:>12.2%}{result['mean_sharpe']:>13.2f}{result['positive']:>13}/{result['n']}")

    print("\n=== Stability assessment ===")
    horizon_results = [v for k, v in results.items() if k[0] == "horizon"]
    cost_results = [v for k, v in results.items() if k[0] == "cost_threshold"]
    horizon_positive_sharpe = sum(1 for r in horizon_results if r["mean_sharpe"] > 0)
    cost_positive_sharpe = sum(1 for r in cost_results if r["mean_sharpe"] > 0)
    print(f"Horizon axis: {horizon_positive_sharpe}/{len(horizon_results)} settings show positive mean Sharpe (3, 5, 7, 10 days tested)")
    print(f"Cost-threshold axis: {cost_positive_sharpe + (1 if base['mean_sharpe'] > 0 else 0)}/{len(cost_results) + 1} settings show positive mean Sharpe (0.5%, 0.8%, 1.0%, 1.5% tested)")

    if horizon_positive_sharpe >= 3 and cost_positive_sharpe >= 2:
        print("\nBroad stability: the finding holds across nearby hyperparameter choices, not just the one point originally reported. Confidence strengthened.")
    else:
        print("\nNarrow: only the original point (or a minority of neighbors) shows positive Sharpe. This looks more like a specific choice that happened to work than a broad, robust region -- treat the original finding with more caution than previously stated.")


if __name__ == "__main__":
    main()
