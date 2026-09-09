"""Fetch deep funding-rate history from Binance's public USDT-M futures API.

WEEX's own funding-rate endpoint (GET /capi/v3/market/fundingRate) hard-caps
at 365 days server-side regardless of pagination -- too thin to test as a
feature against the multi-year price history already pulled from Binance.
Binance's equivalent endpoint supports real startTime/endTime pagination
(confirmed empirically), so this pulls matching depth.

Same basis-bet caveat as scripts/fetch_binance_klines.py: this is Binance's
own funding rate, not WEEX's -- a reasonable proxy since funding rates
converge across venues via arbitrage, not identical to what WEEX itself
would have charged on any given day.

Endpoint: GET /fapi/v1/fundingRate (public, no auth; limit up to 1000).
Output: data/binance_{symbol}_funding.csv (timestamp, funding_rate, mark_price)

Usage:
    python3 scripts/fetch_binance_funding_rate.py BNBUSDT [--days 1460]
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

BASE_URL = "https://fapi.binance.com"
LIMIT = 1000
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def fetch_batch(symbol: str, end_time_ms: int | None) -> list[dict]:
    params: dict[str, object] = {"symbol": symbol, "limit": LIMIT}
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    response = requests.get(f"{BASE_URL}/fapi/v1/fundingRate", params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def fetch_history(symbol: str, target_days: int) -> list[dict]:
    all_rows: list[dict] = []
    end_time_ms: int | None = None
    seen: set[int] = set()
    target_ms = target_days * 86400000

    while True:
        batch = fetch_batch(symbol, end_time_ms)
        if not batch:
            break
        new_rows = [row for row in batch if row["fundingTime"] not in seen]
        if not new_rows:
            break
        all_rows.extend(new_rows)
        seen.update(row["fundingTime"] for row in new_rows)
        oldest = min(row["fundingTime"] for row in batch)
        end_time_ms = oldest - 1
        span = max(row["fundingTime"] for row in all_rows) - oldest
        if span >= target_ms:
            break
        time.sleep(0.2)

    return sorted(all_rows, key=lambda row: row["fundingTime"])


def write_csv(symbol: str, rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "timestamp", "funding_rate", "mark_price"])
        for row in rows:
            timestamp = datetime.fromtimestamp(row["fundingTime"] / 1000, tz=UTC).isoformat()
            writer.writerow([symbol, timestamp, row["fundingRate"], row.get("markPrice", "")])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--days", type=int, default=1460)
    args = parser.parse_args()

    for symbol in args.symbols:
        rows = fetch_history(symbol.upper(), args.days)
        if not rows:
            print(f"{symbol}: no data returned")
            continue
        output_path = DATA_DIR / f"binance_{symbol.lower()}_funding.csv"
        write_csv(symbol.upper(), rows, output_path)
        span_days = (rows[-1]["fundingTime"] - rows[0]["fundingTime"]) / 86400000
        print(f"Wrote {len(rows)} funding records for {symbol.upper()} to {output_path} (span: {span_days:.1f} days)")


if __name__ == "__main__":
    main()
