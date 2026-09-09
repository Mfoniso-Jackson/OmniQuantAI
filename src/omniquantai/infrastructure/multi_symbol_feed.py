from __future__ import annotations

from collections.abc import Iterable

from omniquantai.domain.models import MarketBar


class MultiSymbolMarketDataFeed:
    """Merges several single-symbol feeds into one chronologically-ordered
    stream. PaperTradingEngine already keys history/marks/positions by
    bar.symbol -- it was portfolio-capable all along, it just never
    received more than one symbol's bars in practice. This is the only
    missing piece: interleave multiple assets' bars in true time order so
    a shared PositionManager and risk engine see the whole book evolve
    together, not one asset fully processed before the next starts."""

    def __init__(self, bars_by_symbol: dict[str, list[MarketBar]]) -> None:
        all_bars = [bar for bars in bars_by_symbol.values() for bar in bars]
        self.bars = sorted(all_bars, key=lambda bar: bar.timestamp)

    def stream(self) -> Iterable[MarketBar]:
        yield from self.bars
