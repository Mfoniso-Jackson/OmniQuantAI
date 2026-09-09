"""Run the disciplined parameter search (parameter_search.py) across every
asset available for the competition, to check whether the "nothing survives
out-of-sample" result found on BTCUSDT is asset-specific or systemic.

Per-asset detail is suppressed (verbose=False); only the final robust/not
result per asset is shown here, plus a consolidated leaderboard of anything
that actually survived VALIDATION.

Usage:
    PYTHONPATH=src python3 experiments/multi_asset_search.py [1d|1h]
"""

from __future__ import annotations

import sys

from parameter_search import search_symbol

SYMBOLS = ["btcusdt", "ethusdt", "solusdt", "dogeusdt", "xrpusdt", "bnbusdt", "linkusdt", "adausdt"]


def main() -> None:
    args = sys.argv[1:]
    data_prefix = ""
    if args and args[0] == "--binance":
        data_prefix = "binance_"
        args = args[1:]
    interval = args[0] if args else "1d"
    summaries = []
    for symbol in SYMBOLS:
        print(f"Searching {symbol} ({interval}{', Binance deep data' if data_prefix else ''})...")
        summary = search_symbol(symbol, interval, verbose=False, data_prefix=data_prefix)
        summaries.append(summary)
        status = (
            f"ROBUST -> {summary['best_name']} {summary['best_params']}, "
            f"val_sharpe={summary['validation_sharpe']:.2f}"
            if summary["families_robust"]
            else "nothing survived VALIDATION"
        )
        print(f"  {symbol}: {summary['families_robust']}/{summary['families_tested']} families robust -- {status}")

    print("\n=== Consolidated results ===")
    header = f"{'symbol':<12}{'robust_families':>16}{'best_strategy':<20}{'val_sharpe':>12}{'test_sharpe':>12}{'test_return':>12}"
    print(header)
    print("-" * len(header))
    for summary in summaries:
        test_sharpe = summary["test_result"]["sharpe_ratio"] if summary["test_result"] else None
        test_return = summary["test_result"]["total_return"] if summary["test_result"] else None
        print(
            f"{summary['symbol']:<12}{summary['families_robust']:>16}"
            f"{(summary['best_name'] or '-'):<20}"
            f"{(summary['validation_sharpe'] if summary['validation_sharpe'] is not None else float('nan')):>12.2f}"
            f"{(test_sharpe if test_sharpe is not None else float('nan')):>12.2f}"
            f"{(f'{test_return:.2%}' if test_return is not None else '-'):>12}"
        )

    any_robust = [s for s in summaries if s["families_robust"] > 0]
    print(f"\n{len(any_robust)} of {len(summaries)} assets had any strategy family survive VALIDATION.")


if __name__ == "__main__":
    main()
