#!/usr/bin/env python3
"""Daily forward-test check for both confirmed edges, ahead of Round 2
(starts 2026-09-13):

- BNBUSDT / volatility_regime (lookback=21, vol_ceiling=0.05), daily bars.
  Confirmed independently on two datasets (WEEX 999-day, Binance 4-year)
  with the same winning parameters.
- 11 other assets / pooled ML classifier (14 engineered features, trained
  on data pooled across 12 assets, refit on full history for deployment
  -- see experiments/ml_signal_pipeline.py). 10 of 12 assets positive on
  the reserved TEST check, the broadest evidence found in the project.
  BNBUSDT is routed to its own dedicated strategy above, not this model,
  matching the portfolio design in experiments/portfolio_backtest.py.

This is pure paper/observation -- it reads market data and appends to a
local log, it never places any order. Uses the exact same validated
strategy/model objects as the backtests, not a re-derived approximation.

M6 hardening carried over:
- Detects and prominently flags any signal that differs from the last
  logged one.
- Best-effort, read-only reconciliation against actual live WEEX
  positions (ONE shared API call for all symbols, not one per asset).
  Never fatal if this check fails.
- refresh_data() failure is caught and reported clearly instead of
  crashing with a raw traceback.

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
import warnings
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from omniquantai.application.position_manager import PositionManager  # noqa: E402
from omniquantai.application.regime import SimpleRegimeDetector  # noqa: E402
from omniquantai.application.strategies import VolatilityRegimeStrategy  # noqa: E402
from omniquantai.domain.models import MarketBar  # noqa: E402
from omniquantai.infrastructure.features import FEATURE_NAMES, compute_features  # noqa: E402
from omniquantai.infrastructure.market_data import read_market_bars  # noqa: E402

DATA_DIR = REPO_ROOT / "data"
LOG_DIR = REPO_ROOT / "artifacts" / "forward_test"
MODEL_PATH = REPO_ROOT / "artifacts" / "models" / "ml_signal_logistic.joblib"
FETCH_SCRIPT = REPO_ROOT / "scripts" / "fetch_weex_klines.py"
CONTRACT_API = REPO_ROOT / ".claude" / "skills" / "weex-trader-skill" / "scripts" / "weex_contract_api.py"
IPV4FIX_DIR = REPO_ROOT / "scripts" / "ipv4fix"
PROFILE = "ai-wars"

BNB_SYMBOL = "BNBUSDT"
ML_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT", "LINKUSDT", "ADAUSDT", "SUIUSDT", "TRXUSDT", "1000PEPEUSDT", "1000SHIBUSDT"]


@dataclass(frozen=True)
class Candidate:
    name: str
    symbol: str
    build_strategy: callable
    cadence_note: str


CANDIDATES = [
    Candidate(
        name="bnbusdt_volatility_regime",
        symbol=BNB_SYMBOL,
        build_strategy=lambda: VolatilityRegimeStrategy(lookback=21, vol_ceiling=Decimal("0.05")),
        cadence_note="hand-coded, daily -- confirmed on two independent datasets with the same winning parameters",
    ),
]


class DataRefreshError(RuntimeError):
    pass


def refresh_data(symbols: list[str]) -> None:
    result = subprocess.run(["python3", str(FETCH_SCRIPT), *symbols], capture_output=True, text=True)
    if result.returncode != 0:
        raise DataRefreshError(f"fetch_weex_klines.py exited {result.returncode}: {result.stderr.strip()}")


def load_bars(symbol: str) -> list[MarketBar]:
    return read_market_bars(DATA_DIR / f"{symbol.lower()}_1d.csv")


def compute_signal(candidate: Candidate) -> dict:
    bars = load_bars(candidate.symbol)
    latest_complete = bars[-1]
    history = bars[:-1]

    regime_detector = SimpleRegimeDetector(lookback=14)
    regime = regime_detector.detect(history[-40:] + [latest_complete])

    portfolio = PositionManager(Decimal("100000")).snapshot({candidate.symbol: latest_complete.close})
    strategy = candidate.build_strategy()
    signal = strategy.on_bar(latest_complete, history[-100:], regime, portfolio)

    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "candidate": candidate.name,
        "symbol": candidate.symbol,
        "bar_timestamp": latest_complete.timestamp.isoformat(),
        "price": str(latest_complete.close),
        "regime": regime.value,
        "action": signal.action.value,
        "confidence": str(signal.confidence),
        "target_weight": str(signal.target_weight),
        "reason": signal.reason,
    }


def compute_ml_signal(symbol: str, model, scaler) -> dict | None:
    import numpy as np

    try:
        bars = load_bars(symbol)
    except FileNotFoundError:
        return None
    features = compute_features(bars)
    if features is None:
        return None
    vector = np.array([[features[name] for name in FEATURE_NAMES]])
    if scaler is not None:
        vector = scaler.transform(vector)
    prediction = int(model.predict(vector)[0])
    confidence = float(max(model.predict_proba(vector)[0]))
    action = {1: "buy", -1: "sell", 0: "hold"}[prediction]

    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "candidate": f"ml_{symbol.lower()}",
        "symbol": symbol,
        "bar_timestamp": bars[-1].timestamp.isoformat(),
        "price": str(bars[-1].close),
        "regime": "n/a",
        "action": action,
        "confidence": str(round(confidence, 4)),
        "target_weight": str(Decimal("0.03") if prediction != 0 else Decimal("0")),
        "reason": "ML model prediction (pooled 12-asset logistic regression)",
    }


def read_log_rows(name: str) -> list[dict]:
    log_path = LOG_DIR / f"{name}.csv"
    if not log_path.exists():
        return []
    with log_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def append_log(name: str, row: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{name}.csv"
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
    if not prior_rows:
        return None
    previous_action = prior_rows[-1]["action"]
    if previous_action != new_row["action"]:
        return f"{previous_action.upper()} -> {new_row['action'].upper()}"
    return None


def fetch_all_positions() -> dict:
    """Best-effort, read-only, ONE call for every symbol's position --
    never raises. Returns {"checked": False, "reason": ...} on any
    failure, or {"checked": True, "positions": {symbol: {...}}}."""
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
    except Exception as exc:  # noqa: BLE001 -- must never crash the report
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
    return {"checked": True, "positions": {p["symbol"]: p for p in positions if p.get("symbol")}}


def position_for(all_positions: dict, symbol: str) -> dict:
    if not all_positions.get("checked"):
        return {"checked": False, "reason": all_positions.get("reason")}
    position = all_positions["positions"].get(symbol)
    if position is None:
        return {"checked": True, "has_position": False}
    return {
        "checked": True,
        "has_position": True,
        "side": position.get("side"),
        "size": position.get("size"),
        "unrealized_pnl": position.get("unrealizePnl"),
        "liquidate_price": position.get("liquidatePrice"),
    }


def report_one(name: str, symbol: str, row: dict, all_positions: dict, detail: str) -> None:
    prior_rows = read_log_rows(name)
    flip = detect_flip(prior_rows, row)
    history_summary = summarize_history(prior_rows, row)
    append_log(name, row)

    print(f"{name} ({detail})")
    print(f"  price={row['price']} action={row['action']} confidence={row['confidence']} target_weight={row['target_weight']}")
    print(f"  reason: {row['reason']}")
    print(f"  forward-test history: {history_summary}")
    if flip:
        print(f"  *** SIGNAL FLIP: {flip} *** -- this is the actionable moment, not just another data point")
    else:
        print("  no change from the last check")

    position = position_for(all_positions, symbol)
    if not position.get("checked"):
        print(f"  live position: could not verify ({position.get('reason')})")
    elif not position.get("has_position"):
        print("  live position: none open")
    else:
        print(f"  live position: {position['side']} {position['size']} {symbol}, unrealized PnL {position['unrealized_pnl']}")
        if flip:
            print("  >>> a live position exists AND the signal just flipped -- review whether it still matches the strategy's current view")
    print()


def main() -> None:
    print(f"=== Daily signal check -- {date.today().isoformat()} ===\n")

    all_symbols = [BNB_SYMBOL, *ML_SYMBOLS]
    try:
        refresh_data(all_symbols)
    except DataRefreshError as exc:
        print(f"FAILED to refresh market data: {exc}")
        print("Not proceeding with signal computation -- stale data would be worse than no report.")
        return

    all_positions = fetch_all_positions()

    for candidate in CANDIDATES:
        row = compute_signal(candidate)
        report_one(candidate.name, candidate.symbol, row, all_positions, candidate.cadence_note)

    if not MODEL_PATH.exists():
        print(f"ML model not found at {MODEL_PATH} -- run experiments/ml_signal_pipeline.py first. Skipping ML signals.")
        return

    import joblib

    bundle = joblib.load(MODEL_PATH)
    model, scaler = bundle["model"], bundle["scaler"]

    print(f"ML signals (pooled 12-asset logistic regression, {len(ML_SYMBOLS)} symbols, daily)")
    print(f"{'symbol':<16}{'action':<8}{'confidence':>12}{'flip':>8}{'position':>14}")
    print("-" * 58)
    for symbol in ML_SYMBOLS:
        row = compute_ml_signal(symbol, model, scaler)
        if row is None:
            print(f"{symbol:<16}{'no data':<8}")
            continue
        name = row["candidate"]
        prior_rows = read_log_rows(name)
        flip = detect_flip(prior_rows, row)
        append_log(name, row)
        position = position_for(all_positions, symbol)
        if not position.get("checked"):
            position_display = "unverified"
        elif position.get("has_position"):
            position_display = f"{position['side']} {position['size']}"
        else:
            position_display = "none"
        flip_display = f"{flip}" if flip else ""
        print(f"{symbol:<16}{row['action']:<8}{row['confidence']:>12}{flip_display:>8}{position_display:>14}")
        if flip and position.get("has_position"):
            print(f"  >>> {symbol}: live position open AND signal just flipped -- review")

    print(f"\nLogs: {LOG_DIR}")


if __name__ == "__main__":
    main()
