"""Fetch deep historical klines from Binance's public USDT-M futures API.

WEEX's own /capi/v3/market/klines endpoint caps at 1000 bars per request
with no working pagination -- fine for a quick look, not enough for a
real walk-forward study at hourly resolution (41.6 days total, meaning
~10-day TRAIN/VALIDATION/TEST splits). Binance's equivalent contracts
(same assets, same USDT-margined perpetual structure) publish the same
kind of price action and support genuine startTime/endTime pagination,
so this pulls years of history instead of weeks.

This is a basis bet: Binance price action is a proxy for what would
execute on WEEX, not the venue itself. Reasonable for liquid majors
(tight cross-exchange arbitrage keeps them close); worth sanity-checking
before trusting it for anything thin.

Endpoint: GET /fapi/v1/klines (public, no auth; limit up to 1500 per call).
Output written as data/binance_{symbol}_{interval}.csv -- a separate,
clearly-labeled prefix from the WEEX-sourced data/{symbol}_{interval}.csv
files, so nothing here silently overwrites what's aligned to the actual
execution venue.

Usage:
    python3 scripts/fetch_binance_klines.py BTCUSDT ETHUSDT ... [--days 730] [--interval 1h]
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

BASE_URL = "https://fapi.binance.com"
LIMIT = 1500
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def fetch_batch(symbol: str, interval: str, end_time_ms: int | None) -> list[list]:
    params: dict[str, object] = {"symbol": symbol, "interval": interval, "limit": LIMIT}
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    response = requests.get(f"{BASE_URL}/fapi/v1/klines", params=params, timeout=15)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        raise RuntimeError(f"Binance error for {symbol}: {data}")
    return data


def fetch_history(symbol: str, interval: str, target_bars: int) -> list[list]:
    all_rows: list[list] = []
    end_time_ms: int | None = None
    seen_open_times: set[int] = set()

    while len(all_rows) < target_bars:
        batch = fetch_batch(symbol, interval, end_time_ms)
        if not batch:
            break
        new_rows = [row for row in batch if row[0] not in seen_open_times]
        if not new_rows:
            break
        all_rows.extend(new_rows)
        seen_open_times.update(row[0] for row in new_rows)
        oldest_open_time = min(row[0] for row in batch)
        end_time_ms = oldest_open_time - 1
        time.sleep(0.25)

    return sorted(all_rows, key=lambda row: row[0])[-target_bars:] if len(all_rows) > target_bars else sorted(all_rows, key=lambda row: row[0])


def write_csv(symbol: str, rows: list[list], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "timestamp", "open", "high", "low", "close", "volume"])
        for row in rows:
            open_time_ms, open_, high, low, close, volume = row[0], row[1], row[2], row[3], row[4], row[5]
            timestamp = datetime.fromtimestamp(open_time_ms / 1000, tz=UTC).isoformat()
            writer.writerow([symbol, timestamp, open_, high, low, close, volume])


def bars_for_days(days: int, interval: str) -> int:
    per_day = {"1h": 24, "1d": 1, "15m": 96, "5m": 288}.get(interval)
    if per_day is None:
        raise ValueError(f"Unsupported interval: {interval}")
    return days * per_day


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--interval", default="1h", choices=["1h", "1d", "15m", "5m"])
    parser.add_argument("--days", type=int, default=730, help="Target calendar days of history (default: 730, ~2 years)")
    args = parser.parse_args()

    target_bars = bars_for_days(args.days, args.interval)
    for symbol in args.symbols:
        rows = fetch_history(symbol.upper(), args.interval, target_bars)
        if not rows:
            print(f"{symbol}: no data returned")
            continue
        output_path = DATA_DIR / f"binance_{symbol.lower()}_{args.interval}.csv"
        write_csv(symbol.upper(), rows, output_path)
        span_days = (rows[-1][0] - rows[0][0]) / 86400000
        print(f"Wrote {len(rows)} {args.interval} bars for {symbol.upper()} to {output_path} (span: {span_days:.1f} days)")


if __name__ == "__main__":
    main()
