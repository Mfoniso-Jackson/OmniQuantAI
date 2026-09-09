"""Fetch real BTCUSDT historical klines from WEEX's public contract API.

Endpoint: GET /capi/v3/market/klines (public, no auth required; limit up to 1000).
Reference: https://www.weex.com/api-doc/contract/Market_API/GetKlines

Note: the sibling `/capi/v3/market/historyKlines` endpoint is capped at limit=100
and its `endTime` pagination parameter is not honored by the server (repeated
calls with an earlier endTime return the same latest window) -- use this
endpoint instead, which returns up to 1000 real bars per call.

Writes output in the column layout CsvMarketDataFeed expects:
symbol,timestamp,open,high,low,close,volume
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import csv

import requests

BASE_URL = "https://api-contract.weex.com"
SYMBOL = "BTCUSDT"
LIMIT = 1000
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def fetch_klines(interval: str) -> list[list]:
    response = requests.get(
        f"{BASE_URL}/capi/v3/market/klines",
        params={"symbol": SYMBOL, "interval": interval, "limit": LIMIT},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        raise RuntimeError(f"WEEX error: {data}")
    return sorted(data, key=lambda row: row[0])


def write_csv(rows: list[list], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "timestamp", "open", "high", "low", "close", "volume"])
        for row in rows:
            open_time_ms, open_, high, low, close, volume = row[0], row[1], row[2], row[3], row[4], row[5]
            timestamp = datetime.fromtimestamp(open_time_ms / 1000, tz=UTC).isoformat()
            writer.writerow([SYMBOL, timestamp, open_, high, low, close, volume])


def main() -> None:
    for interval, filename in (("1d", "btcusdt_1d.csv"), ("1h", "btcusdt_1h.csv")):
        rows = fetch_klines(interval)
        output_path = DATA_DIR / filename
        write_csv(rows, output_path)
        span = (rows[-1][0] - rows[0][0]) / 86400000
        print(f"Wrote {len(rows)} {interval} bars for {SYMBOL} to {output_path} (span: {span:.1f} days)")


if __name__ == "__main__":
    main()
