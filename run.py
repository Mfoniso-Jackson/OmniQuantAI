"""
OmniQuantAI - WEEX AI Wars Runner (WEEX-ONLY)
--------------------------------------------
Live execution loop:
equity -> ticker -> decision_engine -> risk_engine -> execute -> AI log -> local backup

Requires:
- competition.yaml
- .env (WEEX_API_KEY, WEEX_API_SECRET, WEEX_API_PASSPHRASE)
- config_loader.py
- decision_engine.py
- decision_record.py
- risk_engine.py
- ai_logger.py
- local_backup.py
- weex/client.py

Run:
    python3 run.py
"""

import time
import json
import traceback
from typing import Dict, Any

from config_loader import load_config, cfg_get
from decision_engine import generate_decision

from decision_record import create_decision_record, attach_risk_outcome, to_dict
from risk_engine import approve_trade

from ai_logger import build_ai_log_from_decision_record, upload_ai_log
from local_backup import (
    backup_decision_record,
    backup_risk_result,
    backup_order_execution,
    backup_ai_log,
    backup_error,
)

from weex.client import WeexClient


# ============================================================
# Helpers
# ============================================================

def parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def safe_sleep(seconds: int):
    for _ in range(seconds):
        time.sleep(1)


# ============================================================
# WEEX Actions
# ============================================================

def fetch_equity_usdt(client: WeexClient) -> float:
    """
    Private:
    GET /capi/v2/account/assets
    Returns USDT equity as float.
    """
    status, text = client.private_get("/capi/v2/account/assets")
    if status != 200:
        raise RuntimeError(f"Failed to fetch assets: {status} {text}")

    data = parse_json(text)

    usdt_row = None
    if isinstance(data, list):
        for row in data:
            if str(row.get("coinName", "")).upper() == "USDT":
                usdt_row = row
                break

    if not usdt_row:
        raise RuntimeError(f"USDT row not found in assets response: {data}")

    return float(usdt_row.get("equity", "0"))


def fetch_ticker(client: WeexClient, symbol: str) -> Dict[str, Any]:
    """
    Market:
    GET /capi/v2/market/ticker?symbol=...
    """
    status, text = client.private_get("/capi/v2/market/ticker", params={"symbol": symbol})
    if status != 200:
        raise RuntimeError(f"Failed to fetch ticker: {status} {text}")
    return parse_json(text)


def set_leverage(client: WeexClient, symbol: str, leverage: int) -> Dict[str, Any]:
    """
    Private:
    POST /capi/v2/account/leverage
    """
    body = {"symbol": symbol, "leverage": leverage}
    status, text = client.private_post("/capi/v2/account/leverage", body=body)
    if status != 200:
        raise RuntimeError(f"Failed to set leverage: {status} {text}")
    return parse_json(text)


def place_order_ioc(
    client: WeexClient,
    symbol: str,
    side: str,
    size: str,
) -> Dict[str, Any]:
    """
    Private:
    POST /capi/v2/order/placeOrder
    IOC market-style order:
    - order_type = "0" (IOC)
    - match_price = "1"
    - price = "0"
    - type: BUY=1, SELL=2
    """
    client_oid = str(int(time.time() * 1000))

    body = {
        "symbol": symbol,
        "client_oid": client_oid,
        "size": str(size),
        "type": "1" if side.upper() == "BUY" else "2",
        "order_type": "0",
        "match_price": "1",
        "price": "0"
    }

    status, text = client.private_post("/capi/v2/order/placeOrder", body=body)
    if status != 200:
        raise RuntimeError(f"Failed to place order: {status} {text}")

    return parse_json(text)


def get_position_single(client: WeexClient, symbol: str) -> Dict[str, Any]:
    """
    Optional evidence:
    GET /capi/v2/account/position/singlePosition?symbol=...
    """
    status, text = client.private_get(
        "/capi/v2/account/position/singlePosition",
        params={"symbol": symbol}
    )
    if status != 200:
        return {"status": status, "raw": text}
    return parse_json(text)


# ============================================================
# Main Loop
# ============================================================

def main():
    cfg = load_config("competition.yaml")

    symbol = cfg_get(cfg, "weex.symbol")
    leverage = int(cfg_get(cfg, "weex.leverage"))
    loop_seconds = int(cfg_get(cfg, "bot.loop_seconds"))
    max_failures = int(cfg_get(cfg, "bot.kill_switch.max_consecutive_failures"))
    pause_on_failure = int(cfg_get(cfg, "bot.kill_switch.pause_seconds_after_failure"))

    fixed_size = str(cfg_get(cfg, "execution.fixed_size"))
    ai_log_enabled = bool(cfg_get(cfg, "ai_log.enabled"))
    model_name = str(cfg_get(cfg, "ai_log.model_name", "OmniQuantAI-v0.1"))
    ai_log_stage = str(cfg_get(cfg, "ai_log.stage", "Decision Making"))

    print("\n===============================")
    print("🚀 OmniQuantAI - LIVE RUN START")
    print("===============================")
    print("Symbol:", symbol)
    print("Leverage:", leverage)
    print("Loop:", loop_seconds, "seconds")
    print("Order size:", fixed_size)
    print("AI Log enabled:", ai_log_enabled)
    print("===============================\n")

    client = WeexClient()
    failures = 0

    # Startup leverage
    try:
        print("⚙️ Setting leverage...")
        resp = set_leverage(client, symbol, leverage)
        print("✅ Leverage response:", resp)
    except Exception as e:
        print("⚠️ Leverage set failed (continuing):", str(e))
        backup_error({"where": "startup_set_leverage", "error": str(e)})

    while True:
        try:
            # 1) Equity + Ticker
            equity = fetch_equity_usdt(client)
            ticker = fetch_ticker(client, symbol)
            last_price = float(ticker.get("last", 0))

            print("\n📡 Market Snapshot")
            print("Equity(USDT):", equity)
            print("Symbol:", symbol)
            print("Last Price:", last_price)
            print("24h Change:", ticker.get("priceChangePercent"))

            # 2) Decision Engine
            decision_out = generate_decision(ticker)

            # 3) Decision Record
            record = create_decision_record(
                symbol=symbol,
                timeframe=str(cfg_get(cfg, "strategy.timeframe", "1m")),
                price=last_price,
                decision=str(decision_out.get("decision", "HOLD")),
                confidence=float(decision_out.get("confidence", 0.0)),
                signals=dict(decision_out.get("signals", {})),
                model_version=model_name,
            )

            record_dict = to_dict(record)

            if "score" in decision_out:
                record_dict["score"] = decision_out["score"]
            if "explanation" in decision_out:
                record_dict["explanation"] = decision_out["explanation"]

            backup_decision_record(record_dict)

            print("\n🧠 Decision")
            print("Decision:", record_dict["decision"])
            print("Confidence:", record_dict["confidence"])
            if "score" in record_dict:
                print("Score:", record_dict["score"])

            # 4) Risk Engine
            risk_result = approve_trade(
                decision_payload={
                    "decision": record_dict["decision"],
                    "confidence": record_dict["confidence"],
                },
                equity=equity
            )
            backup_risk_result(risk_result)

            record = attach_risk_outcome(
                record,
                approved=risk_result["approved"],
                position_size=risk_result.get("position_size"),
                rejection_reason=risk_result.get("reason"),
            )

            record_dict = to_dict(record)

            if not risk_result["approved"]:
                print("🛑 Trade blocked by risk engine:", risk_result.get("reason"))
                failures = 0
                safe_sleep(loop_seconds)
                continue

            # 5) Execute order only if BUY/SELL
            if record_dict["decision"] not in ("BUY", "SELL"):
                print("⏸ HOLD decision. No order placed.")
                failures = 0
                safe_sleep(loop_seconds)
                continue

            side = "BUY" if record_dict["decision"] == "BUY" else "SELL"

            order_payload = {
                "symbol": symbol,
                "side": side,
                "size": fixed_size,
                "order_type": "IOC",
                "leverage": leverage,
            }

            print("\n⚡ Executing Order:", order_payload)

            order_resp = place_order_ioc(
                client=client,
                symbol=symbol,
                side=side,
                size=fixed_size,
            )

            backup_order_execution(order_payload, order_resp)

            order_id = order_resp.get("order_id") or order_resp.get("orderId")
            print("✅ Order Response:", order_resp)
            print("✅ order_id:", order_id)

            pos = get_position_single(client, symbol)
            print("📌 Position snapshot:", pos)

            # 6) Upload AI Log immediately
            if ai_log_enabled:
                ai_payload = build_ai_log_from_decision_record(
                    order_id=int(order_id) if order_id else None,
                    decision_record=record_dict,
                    stage=ai_log_stage,
                    model=model_name,
                )

                ai_upload_resp = upload_ai_log(client, ai_payload)
                backup_ai_log(ai_payload, ai_upload_resp)

                print("🧠 AI log uploaded:", ai_upload_resp)

            failures = 0
            safe_sleep(loop_seconds)

        except KeyboardInterrupt:
            print("\n🛑 Stopped by user.")
            break

        except Exception as e:
            failures += 1

            print("\n❌ ERROR in main loop")
            print(str(e))
            print(traceback.format_exc())

            backup_error({
                "where": "main_loop",
                "error": str(e),
                "traceback": traceback.format_exc()
            })

            if failures >= max_failures:
                print(f"\n🧨 Kill-switch triggered after {failures} failures. Exiting.")
                break

            print(f"⏳ Pausing {pause_on_failure}s then retrying... (failures={failures}/{max_failures})")
            safe_sleep(pause_on_failure)


if __name__ == "__main__":
    main()
