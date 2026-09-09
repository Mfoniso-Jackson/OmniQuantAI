#!/usr/bin/env python3
"""Daily forward-test check for the three candidate edges found during
Round 1 prep, ahead of Round 2 (starts 2026-09-13):

- BNBUSDT / volatility_regime (lookback=21, vol_ceiling=0.05), daily bars
  -- this cadence is a genuine 1:1 match for a once-a-day check.
- DOGEUSDT / mean_reversion (lookback=48, threshold=0.003), hourly bars
- XRPUSDT / mean_reversion (lookback=72, threshold=0.003), hourly bars
  -- these are hourly strategies; a once-a-day check is a SNAPSHOT of the
  current signal plus price action since the last check, not a true
  intraday forward-test (it would miss any intra-day entries/exits the
  real strategy would have taken). Reported as such, not overstated.

This is pure paper/observation -- it reads market data and appends to a
local log, it never places any order. Uses the exact same validated
strategy classes as the backtests, not a re-derived approximation, so
there's no drift between what was tested and what's being watched.

Usage:
    source .venv/bin/activate
    PYTHONPATH=src python3 scripts/daily_signal_check.py
"""

from __future__ import annotations

import csv
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from omniquantai.application.position_manager import PositionManager  # noqa: E402
from omniquantai.application.regime import SimpleRegimeDetector  # noqa: E402
from omniquantai.application.strategies import MeanReversionStrategy, VolatilityRegimeStrategy  # noqa: E402
from omniquantai.domain.models import MarketBar  # noqa: E402
from omniquantai.infrastructure.market_data import read_market_bars  # noqa: E402

DATA_DIR = REPO_ROOT / "data"
LOG_DIR = REPO_ROOT / "artifacts" / "forward_test"
FETCH_SCRIPT = REPO_ROOT / "scripts" / "fetch_weex_klines.py"


@dataclass(frozen=True)
class Candidate:
    name: str
    symbol: str
    interval: str  # "1d" or "1h"
    build_strategy: callable
    cadence_note: str


CANDIDATES = [
    Candidate(
        name="bnbusdt_volatility_regime",
        symbol="BNBUSDT",
        interval="1d",
        build_strategy=lambda: VolatilityRegimeStrategy(lookback=21, vol_ceiling=Decimal("0.05")),
        cadence_note="daily strategy -- this check is a genuine 1:1 forward-test",
    ),
    Candidate(
        name="dogeusdt_mean_reversion",
        symbol="DOGEUSDT",
        interval="1h",
        build_strategy=lambda: MeanReversionStrategy(lookback=48, threshold=Decimal("0.003")),
        cadence_note="hourly strategy -- daily check is a SNAPSHOT, not a full intraday forward-test",
    ),
    Candidate(
        name="xrpusdt_mean_reversion",
        symbol="XRPUSDT",
        interval="1h",
        build_strategy=lambda: MeanReversionStrategy(lookback=72, threshold=Decimal("0.003")),
        cadence_note="hourly strategy -- daily check is a SNAPSHOT, not a full intraday forward-test",
    ),
]


def refresh_data() -> None:
    symbols = sorted({c.symbol for c in CANDIDATES})
    subprocess.run(["python3", str(FETCH_SCRIPT), *symbols], check=True, capture_output=True, text=True)


def load_bars(symbol: str, interval: str) -> list[MarketBar]:
    return read_market_bars(DATA_DIR / f"{symbol.lower()}_{interval}.csv")


def compute_signal(candidate: Candidate) -> dict:
    bars = load_bars(candidate.symbol, candidate.interval)
    latest_complete = bars[-1]
    history = bars[:-1]  # treat the most recent stored bar as "current" reference point

    regime_detector = SimpleRegimeDetector(lookback=14 if candidate.interval == "1d" else 24)
    regime = regime_detector.detect(history[-40:] + [latest_complete])

    portfolio = PositionManager(Decimal("100000")).snapshot({candidate.symbol: latest_complete.close})
    strategy = candidate.build_strategy()
    signal = strategy.on_bar(latest_complete, history[-100:], regime, portfolio)

    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "candidate": candidate.name,
        "symbol": candidate.symbol,
        "interval": candidate.interval,
        "bar_timestamp": latest_complete.timestamp.isoformat(),
        "price": str(latest_complete.close),
        "regime": regime.value,
        "action": signal.action.value,
        "confidence": str(signal.confidence),
        "target_weight": str(signal.target_weight),
        "reason": signal.reason,
    }


def append_log(candidate: Candidate, row: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{candidate.name}.csv"
    is_new = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        if is_new:
            writer.writeheader()
        writer.writerow(row)
    return log_path


def summarize_history(candidate: Candidate) -> str:
    log_path = LOG_DIR / f"{candidate.name}.csv"
    if not log_path.exists():
        return "first check -- no history yet"
    with log_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) < 2:
        return "first check -- no history yet"
    first_price = Decimal(rows[0]["price"])
    last_price = Decimal(rows[-1]["price"])
    price_change = (last_price - first_price) / first_price
    actions = [r["action"] for r in rows]
    return f"{len(rows)} checks logged since {rows[0]['bar_timestamp'][:10]}, price change over window: {price_change:.2%}, actions seen: {', '.join(dict.fromkeys(actions))}"


def main() -> None:
    print(f"=== Daily signal check -- {date.today().isoformat()} ===\n")
    refresh_data()

    for candidate in CANDIDATES:
        row = compute_signal(candidate)
        log_path = append_log(candidate, row)
        history_summary = summarize_history(candidate)
        print(f"{candidate.name} ({candidate.cadence_note})")
        print(f"  price={row['price']} regime={row['regime']} action={row['action']} confidence={row['confidence']} target_weight={row['target_weight']}")
        print(f"  reason: {row['reason']}")
        print(f"  forward-test history: {history_summary}")
        print(f"  log: {log_path}\n")


if __name__ == "__main__":
    main()
