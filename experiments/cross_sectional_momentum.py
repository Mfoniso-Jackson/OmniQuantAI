"""Push the ML approach further: a cross-sectional signal, a genuinely
different paradigm from everything else tried today.

Every strategy and the ML model so far ask "does this asset's own history
predict its own future return?" (time-series / absolute). Cross-sectional
asks a different question: "which assets look best RELATIVE to the
others right now?" -- rank the whole universe by a factor each day, hold
the top-K equally weighted. This can have real structural edge (sector/
altcoin rotation) that absolute single-asset rules miss, and it
diversifies away single-asset idiosyncratic noise by construction.

Deliberately NOT reusing PaperTradingEngine's compounding % of shared
equity -- portfolio_backtest.py just showed that creates unstable,
path-dependent behavior (a 121% return that was a sizing artifact, not
skill). This uses a FIXED, non-compounding dollar allocation per slot
(initial_capital / K), rebalanced daily, so each day's return contribution
is independent of the path so far -- simple and correct for testing
whether the ranking signal itself has edge, before worrying about capital
compounding at all (Rule 9: isolate one question at a time).

Ranking factor: 14-day momentum (same horizon the ML model's coefficients
found most informative). Long-only, top-K, matching Section 9's
simpler-first guidance -- no shorting complexity on a first pass.

Usage:
    PYTHONPATH=src python3 experiments/cross_sectional_momentum.py
"""

from __future__ import annotations

import statistics
from decimal import Decimal
from pathlib import Path

from omniquantai.application.data_split import chronological_split
from omniquantai.infrastructure.market_data import read_market_bars

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ASSETS = [
    "btcusdt", "ethusdt", "solusdt", "dogeusdt", "xrpusdt", "bnbusdt", "linkusdt", "adausdt",
    "suiusdt", "trxusdt", "1000pepeusdt", "1000shibusdt",
]
MOMENTUM_LOOKBACK = 14
TOP_K = 3
COMMISSION_BPS = Decimal("1")  # matches PaperBroker's default elsewhere in this project


def momentum(bars: list, index: int, lookback: int) -> float | None:
    if index < lookback:
        return None
    anchor = bars[index - lookback].close
    if anchor == Decimal("0"):
        return None
    return float((bars[index].close - anchor) / anchor)


def build_date_index(bars_by_asset: dict[str, list]) -> dict:
    """date -> {asset: bar_index}, so each day's ranking only uses bars
    that asset actually has, without assuming perfectly aligned calendars."""
    index: dict = {}
    for asset, bars in bars_by_asset.items():
        for i, bar in enumerate(bars):
            index.setdefault(bar.timestamp.date(), {})[asset] = i
    return index


def backtest_phase(bars_by_asset: dict[str, list]) -> dict:
    date_index = build_date_index(bars_by_asset)
    dates = sorted(date_index.keys())

    daily_returns: list[float] = []
    total_trades = 0

    for day_idx in range(MOMENTUM_LOOKBACK, len(dates) - 1):
        today = dates[day_idx]
        tomorrow = dates[day_idx + 1]

        scores = []
        for asset, bars in bars_by_asset.items():
            if today not in date_index or asset not in date_index[today]:
                continue
            bar_i = date_index[today][asset]
            score = momentum(bars, bar_i, MOMENTUM_LOOKBACK)
            if score is not None:
                scores.append((asset, score, bar_i))

        if len(scores) < TOP_K:
            daily_returns.append(0.0)
            continue

        scores.sort(key=lambda item: item[1], reverse=True)
        top = scores[:TOP_K]

        slot_returns = []
        for asset, _score, bar_i in top:
            bars = bars_by_asset[asset]
            if tomorrow not in date_index or asset not in date_index[tomorrow]:
                continue
            next_bar_i = date_index[tomorrow][asset]
            entry_price = bars[bar_i].close
            exit_price = bars[next_bar_i].close
            if entry_price == Decimal("0"):
                continue
            gross_return = float((exit_price - entry_price) / entry_price)
            cost = float(COMMISSION_BPS / Decimal("10000")) * 2  # round trip
            slot_returns.append(gross_return - cost)
            total_trades += 1

        daily_returns.append(sum(slot_returns) / TOP_K if slot_returns else 0.0)

    cumulative = 1.0
    for r in daily_returns:
        cumulative *= (1 + r)
    total_return = cumulative - 1.0

    mean_daily = statistics.mean(daily_returns) if daily_returns else 0.0
    stdev_daily = statistics.pstdev(daily_returns) if len(daily_returns) > 1 else 0.0
    sharpe = (mean_daily / stdev_daily) * (365 ** 0.5) if stdev_daily else 0.0

    return {"total_return": total_return, "sharpe": sharpe, "days": len(daily_returns), "trades": total_trades}


def main() -> None:
    bars_by_asset = {}
    for asset in ASSETS:
        path = DATA_DIR / f"binance_{asset}_1d.csv"
        if not path.exists():
            continue
        bars_by_asset[asset] = read_market_bars(path)

    splits_by_asset = {asset: {s.name: s.bars for s in chronological_split(bars, train_pct=0.5, validation_pct=0.25)} for asset, bars in bars_by_asset.items()}

    print(f"Cross-sectional momentum: top-{TOP_K} of {len(bars_by_asset)} assets by {MOMENTUM_LOOKBACK}-day momentum, daily rebalance, long-only\n")
    print(f"{'phase':<12}{'return':>10}{'sharpe':>9}{'days':>7}{'trades':>8}")
    print("-" * 46)

    results = {}
    for phase in ("train", "validation", "test"):
        bars_by_phase = {asset: splits[phase] for asset, splits in splits_by_asset.items()}
        result = backtest_phase(bars_by_phase)
        results[phase] = result
        print(f"{phase:<12}{result['total_return']:>9.2%}{result['sharpe']:>9.2f}{result['days']:>7}{result['trades']:>8}")

    print("\n=== Acceptance check ===")
    val, test = results["validation"], results["test"]
    if val["sharpe"] > 0 and val["total_return"] > 0:
        print(f"Clears a minimal bar on VALIDATION (return={val['total_return']:.2%}, sharpe={val['sharpe']:.2f}).")
        print(f"TEST (single reserved check): return={test['total_return']:.2%}, sharpe={test['sharpe']:.2f}")
        if test["sharpe"] > 0 and test["total_return"] > 0:
            print("Holds up on TEST -- a genuine third candidate approach.")
        else:
            print("Does NOT hold up on TEST -- another VALIDATION-only mirage. Not adopting.")
    else:
        print(f"Does not clear even a minimal bar on VALIDATION (return={val['total_return']:.2%}, sharpe={val['sharpe']:.2f}). Not spending the TEST check.")


if __name__ == "__main__":
    main()
