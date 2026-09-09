from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from omniquantai.domain.models import MarketBar


@dataclass(frozen=True, slots=True)
class DataSplit:
    name: str
    bars: list[MarketBar]


def chronological_split(
    bars: Sequence[MarketBar],
    train_pct: float = 0.5,
    validation_pct: float = 0.25,
) -> list[DataSplit]:
    """Split bars into non-overlapping TRAIN / VALIDATION / TEST segments in
    chronological order, per Section 10: no segment may see data from a later
    segment, so each is run through a fresh engine with no shared state."""
    if not 0 < train_pct < 1 or not 0 < validation_pct < 1 or train_pct + validation_pct >= 1:
        raise ValueError("train_pct and validation_pct must each be in (0, 1) and sum to less than 1")
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    total = len(ordered)
    train_end = int(total * train_pct)
    validation_end = train_end + int(total * validation_pct)
    return [
        DataSplit("train", ordered[:train_end]),
        DataSplit("validation", ordered[train_end:validation_end]),
        DataSplit("test", ordered[validation_end:]),
    ]


def rolling_folds(bars: Sequence[MarketBar], folds: int = 5) -> list[DataSplit]:
    """Split bars into `folds` equal, non-overlapping, chronologically ordered
    windows -- used to check whether a strategy's edge is consistent across
    time or concentrated in one lucky period (Section 11: prefer robust
    mediocre performance over a spectacular fragile backtest)."""
    if folds < 2:
        raise ValueError("folds must be at least 2")
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    total = len(ordered)
    fold_size = total // folds
    if fold_size == 0:
        raise ValueError("not enough bars to build the requested number of folds")
    result: list[DataSplit] = []
    for index in range(folds):
        start = index * fold_size
        end = total if index == folds - 1 else start + fold_size
        result.append(DataSplit(f"fold_{index + 1}", ordered[start:end]))
    return result
