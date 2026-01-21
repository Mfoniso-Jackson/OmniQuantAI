"""
OmniQuantAI - WEEX AI Wars Live Runner
-------------------------------------
Loop:
market ticker -> regime_router -> decision_engine -> execution_engine -> ai_logger

This version is:
✅ Long/Short capable (competitive)
✅ Conservative in chop (router blocks noise)
✅ Restart-safe via PositionManager
✅ Uploads AI logs on every OPEN/CLOSE

Run:
    python3 run.py
"""

from __future__ import annotations

import time
import traceback
from typing import Dict, Any

# --- core strategy ---
from core.regime_router import route_regime
from core.decision_engine import make_decision

# --- weex infra ---
from weex.client import WEEXClient
from weex.position_manager import PositionManager
from weex.execution_engine import ExecutionEngine, ExecutionConfig

# --- logging ---
from logging.ai_logger import AILogger

# --- config ---
from config.config_loader import load_config, cfg_get


# ============================================================
# Helpers
# ============================================================

def safe_sleep(seconds: int):
    for _ in range(int(seconds)):
        time.sleep(1)


def _safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _ticker_min(ticker: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only important market fields for logs."""
    return {
        "symbol": ticker.get("symbol"),
        "last": ticker.get("last"),
        "best_bid": ticker.get("best_bid"),
        "best_ask": ticker.get("best_ask"),
        "markPrice": ticker.get("markPrice"),
        "indexPrice": ticker.get("indexPrice"),
        "volume_24h": ticker.get("volume_24h"),
        "priceChangePercent": ticker.get("priceChangePercent"),
        "timestamp": ticker.get("timestamp"),
    }


# ============================================================
# Main
# ============================================================

def main():
    cfg = load_config("competition.yaml")

    # --- WEEX settings ---
    symbol = str(cfg_get(cfg, "weex.symbol", "cmt_btcusdt"))
    leverage = int(cfg_get(cfg, "weex.leverage", 3))
    fixed_size = str(cfg_get(cfg, "execution.fixed_size", "0.0010"))

    # --- bot loop settings ---
    loop_seconds = int(cfg_get(cfg, "bot.loop_seconds", 60))
    max_failures = int(cfg_get(cfg, "bot.kill_switch.max_consecutive_failures", 8))
    pause_seconds = int(cfg_get(cfg, "bot.kill_switch.pause_seconds_after_failure", 20))

    # --- AI log settings ---
    ai_log_enabled = bool(cfg_get(cfg, "ai_log.enabled", True))
    ai_model_name = str(cfg_get(cfg, "ai_log.model_name", "OmniQuantAI-v0.1"))
    ai_stage = str(cfg_get(cfg, "ai_log.stage", "Decision Making"))

    print("\n===============================")
    print("🚀 OmniQuantAI - WEEX LIVE START")
    print("===============================")
    print("Symbol:", symbol)
    print("Leverage:", leverage)
    print("Fixed Size:", fixed_size)
    print("Loop Seconds:", loop_seconds)
    print("AI Log Enabled:", ai_log_enabled)
    print("===============================\n")

    # --- init clients ---
    client = WEEXClient(debug=True)

    # set leverage once at startup
    try:
        print("⚙️ Setting WEEX leverage...")
        lev_resp = client.set_leverage(symbol, leverage)
        print("✅ Leverage response:", lev_resp)
    except Exception as e:
        print("⚠️ Failed to set leverage (continuing):", str(e))

    # state + execution engine
    pm = PositionManager(client=client, symbol=symbol)
    exec_cfg = ExecutionConfig(symbol=symbol, size=fixed_size, leverage=leverage)
    engine = ExecutionEngine(client=client, pm=pm, cfg=exec_cfg)

    # AI logger
    ai_logger = AILogger(
        model_name=ai_model_name,
        default_stage=ai_stage,
        enabled=ai_log_enabled,
    )

    failures = 0

    while True:
        try:
            # ------------------------------------------------
            # 1) Market fetch
            # ------------------------------------------------
            ticker = client.get_ticker(symbol)
            last = _safe_float(ticker.get("last"), 0.0)

            print("\n📡 Market Snapshot")
            print("Symbol:", symbol)
            print("Last:", last)
            print("24h Change:", ticker.get("priceChangePercent"))
            print("Volume 24h:", ticker.get("volume_24h"))

            # ------------------------------------------------
            # 2) Regime router
            # ------------------------------------------------
            router = route_regime(ticker=ticker)

            print("\n🧭 Regime Router")
            print("Regime:", router.get("regime"))
            print("Confidence:", router.get("confidence"))
            print("Trend score:", router.get("trend_score"))
            print("Chop score:", router.get("chop_score"))
            print("Vol score:", router.get("vol_score"))

            # ------------------------------------------------
            # 3) Decision engine
            # ------------------------------------------------
            decision = make_decision(
                raw_signals=router.get("signals", {})
            )

            # attach router regime into decision for full trace
            decision["regime"] = router.get("regime")
            decision["router_confidence"] = router.get("confidence")

            print("\n🧠 Decision Engine")
            print("Decision:", decision.get("decision"))
            print("Score:", decision.get("score"))
            print("Confidence:", decision.get("confidence"))

            # ------------------------------------------------
            # 4) Manage lifecycle (open/close/hold)
            # ------------------------------------------------
            # prepare execution context (used in AI logs)
            execution_ctx = {
                "symbol": symbol,
                "ticker": _ticker_min(ticker),
                "leverage": leverage,
                "size": fixed_size,
                "side": decision.get("decision"),
                "order_response": None,
            }

            # execution_engine handles:
            # - if holding position -> exits (TP/SL/time/regime flip)
            # - if no position -> open if BUY/SELL
            action_result = engine.manage(
                router=router,
                decision=decision,
                ticker=ticker,
                model_name=ai_model_name,
            )

            print("\n⚙️ Engine Result:", action_result)

            # ------------------------------------------------
            # 5) Optional AI log upload for HOLD events too
            # (For judges: makes transparency obvious)
            # ------------------------------------------------
            if ai_log_enabled:
                # only upload non-trade logs occasionally (avoid spam)
                # upload when HOLD or NO_TRADE every N loops
                upload_hold_logs = bool(cfg_get(cfg, "ai_log.upload_hold_logs", False))

                if upload_hold_logs and action_result.get("action") in ("NO_TRADE", "HOLD_POSITION"):
                    payload = ai_logger.build_payload(
                        order_id=None,
                        router=router,
                        decision=decision,
                        execution=execution_ctx,
                        stage="Decision Making",
                    )
                    ai_logger.upload(client=client, payload=payload)

            failures = 0
            safe_sleep(loop_seconds)

        except KeyboardInterrupt:
            print("\n🛑 Stopped by user.")
            break

        except Exception as e:
            failures += 1
            print("\n❌ ERROR in run loop:", str(e))
            print(traceback.format_exc())

            if failures >= max_failures:
                print(f"\n🧨 Kill-switch triggered after {failures} consecutive failures. Exiting.")
                break

            print(f"⏳ Waiting {pause_seconds}s then retrying... (failures={failures}/{max_failures})")
            safe_sleep(pause_seconds)


if __name__ == "__main__":
    main()
