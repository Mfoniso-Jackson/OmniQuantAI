"""
OmniQuantAI - WEEX AI Wars Runner (Aligned With Repo)
----------------------------------------------------
Live loop:
assets -> ticker -> router -> decision_engine -> risk_engine -> execute -> upload AI log

Requires:
- competition.yaml
- config/config_loader.py
- core/regime_router.py
- core/decision_engine.py
- core/risk_engine.py
- logging/ai_logger.py
- weex/client.py

Run:
    PYTHONPATH=. python3 run.py
"""

import time
import traceback
from typing import Dict, Any

from config.config_loader import load_config, cfg_get

# core intelligence
from core.regime_router import route_regime
from core.decision_engine import make_decision
from core.risk_engine import approve_trade

# weex api
from weex.client import WEEXClient

# ai log
from logging.ai_logger import AILogger


# ============================================================
# Helpers
# ============================================================

def safe_sleep(seconds: int):
    for _ in range(seconds):
        time.sleep(1)


def now_ms() -> int:
    return int(time.time() * 1000)


def safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def extract_usdt_equity(assets: Any) -> float:
    """
    assets example:
    [{"coinName":"USDT","available":"1000.0","equity":"1000.0",...}]
    """
    if not isinstance(assets, list):
        raise RuntimeError(f"Unexpected assets response shape: {assets}")

    for row in assets:
        if str(row.get("coinName", "")).upper() == "USDT":
            return safe_float(row.get("equity", "0"), 0.0)

    raise RuntimeError(f"USDT not found in assets response: {assets}")


# ============================================================
# WEEX Execution
# ============================================================

def place_order_ioc(client: WEEXClient, symbol: str, side: str, size: str) -> Dict[str, Any]:
    """
    WEEX placeOrder mapping:
      type:
        "1" open long (BUY)
        "2" open short (SELL)
      order_type = "0" (IOC)
      match_price = "1" (market)
      price = "0"
    """
    body = {
        "symbol": symbol,
        "client_oid": str(now_ms()),
        "size": str(size),
        "type": "1" if side.upper() == "BUY" else "2",
        "order_type": "0",
        "match_price": "1",
        "price": "0",
    }
    return client.place_order(body)


# ============================================================
# Main
# ============================================================

def main():
    cfg = load_config("competition.yaml")

    symbol = str(cfg_get(cfg, "weex.symbol", "cmt_btcusdt"))
    leverage = int(cfg_get(cfg, "weex.leverage", 3))
    loop_seconds = int(cfg_get(cfg, "bot.loop_seconds", 60))

    fixed_size = str(cfg_get(cfg, "execution.fixed_size", "0.0010"))

    # kill switch
    max_failures = int(cfg_get(cfg, "bot.kill_switch.max_consecutive_failures", 5))
    pause_on_failure = int(cfg_get(cfg, "bot.kill_switch.pause_seconds_after_failure", 15))

    # AI log
    ai_log_enabled = bool(cfg_get(cfg, "ai_log.enabled", True))
    ai_stage = str(cfg_get(cfg, "ai_log.stage", "Decision Making"))
    model_name = str(cfg_get(cfg, "ai_log.model_name", "OmniQuantAI-v0.1"))

    print("\n===============================")
    print("🚀 OmniQuantAI - LIVE RUN START")
    print("===============================")
    print("Symbol:", symbol)
    print("Leverage:", leverage)
    print("Loop seconds:", loop_seconds)
    print("Order size:", fixed_size)
    print("AI Log enabled:", ai_log_enabled)
    print("===============================\n")

    client = WEEXClient(debug=True)
    ai_logger = AILogger(model_name=model_name, default_stage=ai_stage, enabled=ai_log_enabled)

    # Set leverage once at startup
    try:
        print("⚙️ Setting leverage...")
        resp = client.set_leverage(symbol, leverage)
        print("✅ Leverage response:", resp)
    except Exception as e:
        print("⚠️ Leverage set failed (continuing):", str(e))

    failures = 0

    while True:
        try:
            # 1) Fetch equity + ticker
            assets = client.get_assets()
            equity = extract_usdt_equity(assets)

            ticker = client.get_ticker(symbol)
            last_price = safe_float(ticker.get("last"), 0.0)

            print("\n📡 Snapshot")
            print("Equity(USDT):", equity)
            print("Last:", last_price)
            print("24h Change:", ticker.get("priceChangePercent"))

            # 2) Regime Router
            router = route_regime(symbol=symbol, ticker=ticker, config=cfg)

            print("\n🧭 Router")
            print("Regime:", router.get("regime"))
            if router.get("why"):
                print("Why:", router.get("why"))

            # 3) Decision Engine
            decision = make_decision(router=router, ticker=ticker, config=cfg)

            print("\n🧠 Decision")
            print("Decision:", decision.get("decision"))
            print("Confidence:", decision.get("confidence"))
            if decision.get("score") is not None:
                print("Score:", decision.get("score"))

            # 4) Risk Engine
            risk = approve_trade(
                decision_payload=decision,
                equity=equity,
                config=cfg,
            )

            print("\n🛡 Risk")
            print("Approved:", risk.get("approved"))
            print("Reason:", risk.get("reason"))

            if not risk.get("approved", False):
                failures = 0
                safe_sleep(loop_seconds)
                continue

            # 5) Execute only BUY/SELL
            side = str(decision.get("decision", "HOLD")).upper()
            if side not in ("BUY", "SELL"):
                print("⏸ HOLD. No order placed.")
                failures = 0
                safe_sleep(loop_seconds)
                continue

            print("\n⚡ Executing Order:", side)
            order_resp = place_order_ioc(client, symbol, side, fixed_size)

            order_id = order_resp.get("order_id") or order_resp.get("orderId")
            print("✅ Order Response:", order_resp)
            print("✅ order_id:", order_id)

            # 6) Upload AI Log immediately
            if ai_log_enabled:
                payload = ai_logger.build_payload(
                    order_id=int(order_id) if order_id else None,
                    router=router,
                    decision=decision,
                    execution={
                        "symbol": symbol,
                        "side": side,
                        "size": fixed_size,
                        "leverage": leverage,
                        "ticker": {
                            "last": ticker.get("last"),
                            "best_bid": ticker.get("best_bid"),
                            "best_ask": ticker.get("best_ask"),
                            "markPrice": ticker.get("markPrice"),
                            "indexPrice": ticker.get("indexPrice"),
                            "volume_24h": ticker.get("volume_24h"),
                            "priceChangePercent": ticker.get("priceChangePercent"),
                        },
                        "order_response": order_resp,
                    },
                    stage=ai_stage,
                )

                upload_resp = ai_logger.upload(client=client, payload=payload)
                print("🧠 AI log uploaded:", upload_resp)

            failures = 0
            safe_sleep(loop_seconds)

        except KeyboardInterrupt:
            print("\n🛑 Stopped by user.")
            break

        except Exception as e:
            failures += 1
            print("\n❌ ERROR:", str(e))
            print(traceback.format_exc())

            if failures >= max_failures:
                print(f"\n🧨 Kill-switch triggered after {failures} failures. Exiting.")
                break

            print(f"⏳ Sleeping {pause_on_failure}s (failures={failures}/{max_failures})")
            safe_sleep(pause_on_failure)


if __name__ == "__main__":
    main()
