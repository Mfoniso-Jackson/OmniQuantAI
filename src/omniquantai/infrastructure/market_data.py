from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from omniquantai.domain.models import MarketBar


def read_market_bars(path: Path) -> list[MarketBar]:
    bars: list[MarketBar] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            bars.append(
                MarketBar(
                    symbol=row["symbol"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                    volume=Decimal(row["volume"]),
                )
            )
    return sorted(bars, key=lambda bar: bar.timestamp)


class InMemoryMarketDataFeed:
    def __init__(self, bars: list[MarketBar]) -> None:
        self.bars = sorted(bars, key=lambda item: item.timestamp)

    def stream(self) -> Iterable[MarketBar]:
        yield from self.bars


class CsvMarketDataFeed:
    def __init__(self, path: Path) -> None:
        self.path = path

    def stream(self) -> Iterable[MarketBar]:
        yield from read_market_bars(self.path)
