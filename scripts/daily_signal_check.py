#!/usr/bin/env python3
"""Daily forward-test check for the confirmed BNBUSDT edge, ahead of
Round 2 (starts 2026-09-13):

- BNBUSDT / volatility_regime (lookback=21, vol_ceiling=0.05), daily bars
  -- this cadence is a genuine 1:1 match for a once-a-day check.
  Confirmed independently on two datasets (WEEX 999-day, Binance 4-year)
  with the same winning parameters -- the only candidate that survived
  6 strategy families x 8 assets x 2 data sources of testing.

This is pure paper/observation for the signal itself -- it reads market
data and appends to a local log, it never places any order. Uses the
exact same validated strategy class as the backtests, not a re-derived
approximation, so there's no drift between what was tested and what's
being watched.

M6 hardening over the original version:
- Detects and prominently flags when today's signal differs from the
  last logged one (the actionable moment, easy to miss buried in a
  wall of daily output).
- Best-effort, read-only reconciliation against the actual live WEEX
  position for this symbol, so a flip is reported against what's really
  on the account, not just in the abstract. Never fatal if this check
  fails (network issue, locked vault, etc.) -- degrades to a clear
  "could not verify" note rather than crashing the whole report.
- refresh_data() failure (WEEX unreachable, etc.) is caught and reported
  clearly instead of crashing with a raw traceback.

Usage:
    source .venv/bin/activate
    PYTHONPATH=src python3 scripts/daily_signal_check.py
"""

from __future__ import annotations

import csv
import json
import os
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
from omniquantai.application.strategies import VolatilityRegimeStrategy  # noqa: E402
from omniquantai.domain.models import MarketBar  # noqa: E402
from omniquantai.infrastructure.market_data import read_market_bars  # noqa: E402

DATA_DIR = REPO_ROOT / "data"
LOG_DIR = REPO_ROOT / "artifacts" / "forward_test"
FETCH_SCRIPT = REPO_ROOT / "scripts" / "fetch_weex_klines.py"
CONTRACT_API = REPO_ROOT / ".claude" / "skills" / "weex-trader-skill" / "scripts" / "weex_contract_api.py"
IPV4FIX_DIR = REPO_ROOT / "scripts" / "ipv4fix"
PROFILE = "ai-wars"


@dataclass(frozen=True)
class Candidate:
    name: str
    symbol: str
    interval: str  # "1d" or "1h"
    build_strategy: callable
    cadence_note: str


# DOGEUSDT and XRPUSDT hourly mean_reversion (found on WEEX's 41-day
# window) were REFUTED by a deep 2-year Binance re-validation -- both
# looked strong on TRAIN+VALIDATION but the reserved TEST check came back
# negative, the signature of riding one historical trend that later
# reversed. Removed rather than kept "for reference": monitoring a
# refuted signal alongside a confirmed one invites confusing the two.
CANDIDATES = [
    Candidate(
        name="bnbusdt_volatility_regime",
        symbol="BNBUSDT",
        interval="1d",
        build_strategy=lambda: VolatilityRegimeStrategy(lookback=21, vol_ceiling=Decimal("0.05")),
        cadence_note="daily strategy -- this check is a genuine 1:1 forward-test. Confirmed on two "
        "independent datasets (WEEX 999-day, Binance 4-year) with the same winning parameters.",
    ),
]


class DataRefreshError(RuntimeError):
    pass


def refresh_data() -> None:
    symbols = sorted({c.symbol for c in CANDIDATES})
    result = subprocess.run(["python3", str(FETCH_SCRIPT), *symbols], capture_output=True, text=True)
    if result.returncode != 0:
        raise DataRefreshError(f"fetch_weex_klines.py exited {result.returncode}: {result.stderr.strip()}")


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


def read_log_rows(candidate: Candidate) -> list[dict]:
    log_path = LOG_DIR / f"{candidate.name}.csv"
    if not log_path.exists():
        return []
    with log_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def summarize_history(prior_rows: list[dict], new_row: dict) -> str:
    all_rows = prior_rows + [new_row]
    if len(all_rows) < 2:
        return "first check -- no history yet"
    first_price = Decimal(all_rows[0]["price"])
    last_price = Decimal(all_rows[-1]["price"])
    price_change = (last_price - first_price) / first_price
    actions = [r["action"] for r in all_rows]
    return f"{len(all_rows)} checks logged since {all_rows[0]['bar_timestamp'][:10]}, price change over window: {price_change:.2%}, actions seen: {', '.join(dict.fromkeys(actions))}"


def detect_flip(prior_rows: list[dict], new_row: dict) -> str | None:
    """Returns a description of the flip if today's action differs from
    the last logged one, else None. First-ever check is never a flip."""
    if not prior_rows:
        return None
    previous_action = prior_rows[-1]["action"]
    if previous_action != new_row["action"]:
        return f"{previous_action.upper()} -> {new_row['action'].upper()}"
    return None


def check_live_position(symbol: str) -> dict:
    """Best-effort, read-only check of the actual live position for this
    symbol. Never raises -- returns a dict describing success or the
    specific reason it couldn't be checked, so a monitoring failure here
    never takes down the rest of the report."""
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{IPV4FIX_DIR}{os.pathsep}{env.get('PYTHONPATH', '')}"
    try:
        import certifi

        env["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass

    try:
        result = subprocess.run(
            ["python3", str(CONTRACT_API), "--profile", PROFILE, "call", "--endpoint", "account.get_all_positions"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, this check must never crash the report
        return {"checked": False, "reason": f"subprocess error: {exc}"}

    if result.returncode not in (0, 1, 2):
        return {"checked": False, "reason": f"weex_contract_api.py exited {result.returncode}: {result.stderr.strip()[:300]}"}

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"checked": False, "reason": f"non-JSON response: {result.stdout.strip()[:300]}"}

    if not payload.get("ok"):
        return {"checked": False, "reason": payload.get("failureReason") or "unknown API error"}

    positions = payload.get("normalizedResult", {}).get("data", []) or []
    matching = [p for p in positions if p.get("symbol") == symbol]
    if not matching:
        return {"checked": True, "has_position": False}
    position = matching[0]
    return {
        "checked": True,
        "has_position": True,
        "side": position.get("side"),
        "size": position.get("size"),
        "unrealized_pnl": position.get("unrealizePnl"),
        "liquidate_price": position.get("liquidatePrice"),
    }


def main() -> None:
    print(f"=== Daily signal check -- {date.today().isoformat()} ===\n")

    try:
        refresh_data()
    except DataRefreshError as exc:
        print(f"FAILED to refresh market data: {exc}")
        print("Not proceeding with signal computation -- stale data would be worse than no report.")
        return

    for candidate in CANDIDATES:
        prior_rows = read_log_rows(candidate)
        row = compute_signal(candidate)
        flip = detect_flip(prior_rows, row)
        history_summary = summarize_history(prior_rows, row)
        log_path = append_log(candidate, row)

        print(f"{candidate.name} ({candidate.cadence_note})")
        print(f"  price={row['price']} regime={row['regime']} action={row['action']} confidence={row['confidence']} target_weight={row['target_weight']}")
        print(f"  reason: {row['reason']}")
        print(f"  forward-test history: {history_summary}")

        if flip:
            print(f"  *** SIGNAL FLIP: {flip} *** -- this is the actionable moment, not just another data point")
        else:
            print("  no change from the last check")

        position = check_live_position(candidate.symbol)
        if not position.get("checked"):
            print(f"  live position: could not verify ({position.get('reason')}) -- signal above is still valid, just unreconciled against the account")
        elif not position.get("has_position"):
            print("  live position: none open for this symbol")
        else:
            print(
                f"  live position: {position['side']} {position['size']} {candidate.symbol}, "
                f"unrealized PnL {position['unrealized_pnl']}, liquidation price {position['liquidate_price']}"
            )
            if flip:
                print("  >>> a live position exists AND the signal just flipped -- review whether this position still matches the strategy's current view")

        print(f"  log: {log_path}\n")


if __name__ == "__main__":
    main()
