#!/usr/bin/env python3
"""Generate genuine round-trip trading volume on WEEX to help clear the
AI Wars II 50,000 USDT-per-round volume threshold for individual rewards.

This is a deliberate volume-generation exercise, not a directional trading
strategy. No baseline validated today (buy_and_hold, momentum, ma_trend,
mean_reversion, volatility_regime, plus two regime-gated variants) had a
walk-forward-validated edge, so this opens and closes a position back to
back each round trip with no directional intent -- the goal is exactly
50,000 USDT of real notional traded, not profit.

Cost is real and close to deterministic: at the taker fee rate (0.08%
each leg), reaching 50,000 USDT of volume costs approximately
50,000 * 0.0008 * 2 = $80 in fees regardless of how it's chunked into
round trips (fee cost scales with total notional traded, not trade count
or size). The user explicitly chose to accept this cost against the
uncertain payout of the participation-reward pool share.

Hard safety stop: halts immediately if account equity falls below
--equity-floor-pct of the balance measured at the start of the run,
regardless of remaining target volume -- capital preservation takes
priority over hitting the volume target (Section 12 of the project
brief: if the system enters a dangerous state, stop trading).

This script only ever calls the already-verified weex_contract_api.py
wrapper (same signing path validated for the single buy-and-hold trade),
never mutates the API directly itself.

Usage (dry-run -- always do this first, sends nothing):
    source scripts/activate_weex_skill_env.sh
    python3 scripts/generate_competition_volume.py --dry-run

Usage (live -- run this yourself; the assistant does not run this):
    python3 scripts/generate_competition_volume.py --confirm-live
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_API = REPO_ROOT / ".claude" / "skills" / "weex-trader-skill" / "scripts" / "weex_contract_api.py"
AI_LOG_DIR = REPO_ROOT / "artifacts" / "ai_logs" / "volume_generation"
PROFILE = "ai-wars"
SYMBOL = "BTCUSDT"
MODEL_ID = "claude-sonnet-5"


def run_cli(args: list[str]) -> dict:
    result = subprocess.run(
        ["python3", str(CONTRACT_API), "--profile", PROFILE, *args],
        capture_output=True,
        text=True,
    )
    # exitCode 2 is the skill's documented graceful-degradation path: the
    # trade itself succeeded but the (not actually required -- see below)
    # AI-log upload to WEEX failed. That's still valid JSON on stdout and
    # must be parsed, not treated as a fatal script error.
    if result.returncode not in (0, 1, 2):
        raise RuntimeError(f"weex_contract_api.py exited {result.returncode}: {result.stderr}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse response: {result.stdout}\n{result.stderr}") from exc


def get_balance() -> float:
    response = run_cli(["call", "--endpoint", "account.get_account_balance"])
    if not response.get("ok"):
        raise RuntimeError(f"Balance check failed: {response}")
    data = response["normalizedResult"]["data"]
    row = next(item for item in data if item["asset"] == "USDT")
    return float(row["availableBalance"])


def get_price() -> float:
    response = run_cli(["ticker", "--symbol", SYMBOL])
    if not response.get("ok"):
        raise RuntimeError(f"Price check failed: {response}")
    return float(response["normalizedResult"]["data"]["price"])


def write_ai_log(round_trip: int, leg: str, side: str, quantity: str, cumulative_volume: float, target_volume: float) -> Path:
    AI_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = AI_LOG_DIR / f"round_trip_{round_trip:03d}_{leg}.json"
    payload = {
        "stage": "Execution",
        "model": MODEL_ID,
        "input": {
            "task": "competition_volume_generation",
            "symbol": SYMBOL,
            "round_trip_index": round_trip,
            "leg": leg,
            "cumulative_volume_usdt_before_this_leg": round(cumulative_volume, 2),
            "target_volume_usdt": target_volume,
            "context": (
                "WEEX AI Wars II Round 1 individual rewards require >=50,000 USDT "
                "trading volume this round; no strategy tested today had a "
                "walk-forward-validated edge, so the user explicitly chose to "
                "generate the required volume via flat (no net directional "
                "exposure) round-trip trades rather than risk capital on an "
                "unvalidated directional strategy."
            ),
        },
        "output": {
            "symbol": SYMBOL,
            "side": side,
            "positionSide": "LONG",
            "type": "MARKET",
            "quantity": quantity,
        },
        "explanation": (
            f"Round-trip {round_trip}, {leg} leg: {side} {quantity} {SYMBOL} at market to "
            "generate genuine trading volume toward the competition's 50,000 USDT "
            "eligibility threshold. Not a directional bet -- opened and closed "
            "back-to-back by design since no tested strategy has a validated edge."
        ),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def place_leg(side: str, quantity: str, ai_log_path: Path, confirm_live: bool, dry_run: bool) -> dict:
    # --ai-log is required by weex_contract_api.py itself to attempt the
    # order at all (a client-side check, separate from WEEX's own server).
    # The upload to WEEX will fail with 403 (confirmed against the current
    # official ai2 docs -- only intro/guide/trading-pairs exist, no
    # uploadAiLog endpoint -- so this upload isn't actually required by AI
    # Wars II), but the trade itself still executes; run_cli() accepts the
    # resulting exitCode 2 as non-fatal.
    args = [
        "place-order",
        "--symbol", SYMBOL,
        "--side", side,
        "--position-side", "LONG",
        "--type", "MARKET",
        "--quantity", quantity,
        "--ai-log", f"@{ai_log_path}",
    ]
    if dry_run:
        args.append("--dry-run")
    if confirm_live:
        args.append("--confirm-live")
    return run_cli(args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target-volume", type=float, default=50_000.0, help="Total USDT notional to reach (default: 50000)")
    parser.add_argument("--quantity-btc", type=float, default=0.02, help="BTC quantity per leg (default: 0.02, ~$1,590 notional at $79.5k)")
    parser.add_argument("--equity-floor-pct", type=float, default=0.6, help="Halt if equity falls below this fraction of starting balance (default: 0.6)")
    parser.add_argument("--max-round-trips", type=int, default=40, help="Hard cap on round trips regardless of target (default: 40)")
    parser.add_argument("--sleep-seconds", type=float, default=1.5, help="Pause between legs (default: 1.5s)")
    parser.add_argument("--dry-run", action="store_true", help="Preview every leg without sending anything")
    parser.add_argument("--confirm-live", action="store_true", help="Actually place live orders (required for a real run)")
    args = parser.parse_args()

    if not args.dry_run and not args.confirm_live:
        print("Refusing to run: pass --dry-run to preview, or --confirm-live to actually trade.", file=sys.stderr)
        return 2

    starting_balance = get_balance()
    equity_floor = starting_balance * args.equity_floor_pct
    price = get_price()
    quantity_str = f"{args.quantity_btc:.4f}"
    leg_notional = args.quantity_btc * price

    print(f"Starting balance: {starting_balance:.2f} USDT | equity floor: {equity_floor:.2f} USDT")
    print(f"BTCUSDT price: {price:.2f} | quantity/leg: {quantity_str} BTC (~{leg_notional:.2f} USDT notional)")
    print(f"Target volume: {args.target_volume:.2f} USDT | max round trips: {args.max_round_trips}")
    print(f"Mode: {'DRY RUN (nothing sent)' if args.dry_run else 'LIVE -- real orders'}\n")

    cumulative_volume = 0.0
    round_trip = 0

    while cumulative_volume < args.target_volume and round_trip < args.max_round_trips:
        round_trip += 1

        if not args.dry_run:
            current_balance = get_balance()
            if current_balance < equity_floor:
                print(f"HALT: equity {current_balance:.2f} fell below floor {equity_floor:.2f}. Stopping.")
                break

        open_log = write_ai_log(round_trip, "open", "BUY", quantity_str, cumulative_volume, args.target_volume)
        open_result = place_leg("BUY", quantity_str, open_log, args.confirm_live, args.dry_run)
        if not open_result.get("ok") and not args.dry_run:
            print(f"HALT: open leg failed on round trip {round_trip}: {open_result}")
            break
        cumulative_volume += leg_notional
        print(f"[{round_trip}] OPEN  BUY {quantity_str} BTC -- cumulative volume: {cumulative_volume:.2f} USDT")

        time.sleep(args.sleep_seconds)

        close_log = write_ai_log(round_trip, "close", "SELL", quantity_str, cumulative_volume, args.target_volume)
        close_result = place_leg("SELL", quantity_str, close_log, args.confirm_live, args.dry_run)
        if not close_result.get("ok") and not args.dry_run:
            print(f"HALT: close leg failed on round trip {round_trip} -- POSITION MAY BE OPEN, check manually: {close_result}")
            break
        cumulative_volume += leg_notional
        print(f"[{round_trip}] CLOSE SELL {quantity_str} BTC -- cumulative volume: {cumulative_volume:.2f} USDT")

        time.sleep(args.sleep_seconds)

    print(f"\nDone. {round_trip} round trip(s), {cumulative_volume:.2f} / {args.target_volume:.2f} USDT volume.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
