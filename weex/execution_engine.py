"""
WEEX Execution Engine (OmniQuantAI) - PositionManager Edition
------------------------------------------------------------
Purpose:
- Execute trades on WEEX futures (open + close)
- Manage exits intelligently (TP/SL, time-stop, regime flip)
- Upload AI logs immediately after execution (AI Wars compliance)
- Use PositionManager for restart-safe position state

Requires:
- weex/client.py
- weex/position_manager.py
- ai_logging/ai_logger.py

Endpoints used:
- POST /capi/v2/order/placeOrder
- GET  /capi/v2/order/history
- GET  /capi/v2/order/fills
- GET  /capi/v2/account/position/singlePosition
- POST /capi/v2/order/uploadAiLog
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple, TYPE_CHECKING

from weex.position_manager import PositionManager
from ai_logging.ai_logger import AILogger

if TYPE_CHECKING:
    from weex.client import WEEXClient


# ============================================================
# Config
# ============================================================

@dataclass
class ExecutionConfig:
    symbol: str = "cmt_btcusdt"
    size: str = "0.0010"     # BTC size
    leverage: int = 3
    dry_run: bool = True
    min_confidence: float = 0.20
    leverage_cap: int = 20
    allow_short: bool = True

    # exits
    take_profit_pct: float = 0.25 / 100     # +0.25%
    stop_loss_pct: float = 0.20 / 100       # -0.20%
    max_hold_minutes: int = 45              # time stop
    regime_flip_exit: bool = True

    # retries
    max_open_retries: int = 2
    max_close_retries: int = 2


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _pct_change(current: float, entry: float) -> float:
    if entry == 0:
        return 0.0
    return (current - entry) / entry


# ============================================================
# Execution Engine
# ============================================================

class ExecutionEngine:
    """
    Position lifecycle engine:
    - sync position from WEEX
    - open/close
    - exit management rules
    - AI log upload after each execution

    Uses PositionManager as state layer.
    """

    def __init__(self, client: "WEEXClient", pm: PositionManager, cfg: ExecutionConfig):
        self.client = client
        self.pm = pm
        self.cfg = cfg

        self.ai_logger = AILogger(model_name="OmniQuantAI-v0.1")

    @staticmethod
    def _log_event(event: str, **fields: Any) -> None:
        payload = {"event": event, **fields}
        print("OMNIQUANT_EVENT", payload)

    def _validate_entry(self, decision: Dict[str, Any]) -> Tuple[bool, str]:
        direction = str(decision.get("decision") or "")
        confidence = _safe_float(decision.get("confidence"), 0.0)

        if self.cfg.leverage > self.cfg.leverage_cap:
            return False, "leverage_cap_exceeded"
        if confidence < self.cfg.min_confidence:
            return False, "confidence_below_minimum"
        if direction == "SELL" and not self.cfg.allow_short:
            return False, "short_entries_disabled"
        return True, "entry_risk_approved"

    # ----------------------------
    # WEEX type mapping
    # ----------------------------

    @staticmethod
    def _open_type(direction: str) -> str:
        """
        WEEX placeOrder type mapping:
        "1" = Open long
        "2" = Open short
        """
        if direction == "BUY":
            return "1"
        if direction == "SELL":
            return "2"
        raise ValueError("direction must be BUY or SELL")

    @staticmethod
    def _close_type(position_side: str) -> str:
        """
        WEEX placeOrder type mapping:
        "3" = Close long
        "4" = Close short
        """
        if position_side == "LONG":
            return "3"
        if position_side == "SHORT":
            return "4"
        raise ValueError("position_side must be LONG or SHORT")

    # ----------------------------
    # OPEN
    # ----------------------------

    def open_position(
        self,
        *,
        direction: str,          # "BUY" or "SELL"
        router: Dict[str, Any],
        decision: Dict[str, Any],
        ticker: Dict[str, Any],
        model_name: str,
    ) -> Tuple[bool, Optional[int]]:
        """
        Open new position ONLY if none exists.
        """
        if self.cfg.dry_run:
            self._log_event("dry_run_open_blocked", direction=direction, symbol=self.cfg.symbol)
            return True, None

        self.pm.sync_from_exchange()
        if self.pm.has_position():
            return False, None

        order_id: Optional[int] = None

        for attempt in range(1, self.cfg.max_open_retries + 1):
            try:
                payload = {
                    "symbol": self.cfg.symbol,
                    "client_oid": str(_now_ms()),
                    "size": self.cfg.size,
                    "type": self._open_type(direction),
                    "order_type": "0",
                    "match_price": "1",   # market (IOC-like behavior)
                    "price": "0",
                }

                resp = self.client.place_order(payload)
                order_id = int(resp.get("order_id")) if resp and resp.get("order_id") else None

                # sync again to capture entry price & size
                pos = self.pm.sync_from_exchange()

                opened_side = "LONG" if direction == "BUY" else "SHORT"

                # If WEEX didn't return entry price, fallback to ticker last
                entry_price = self.pm.get_entry_price()
                if entry_price <= 0:
                    entry_price = _safe_float(ticker.get("last"), 0.0)

                # if exchange position endpoint is delayed, still store local state
                if pos is None:
                    self.pm.set_open(
                        side=opened_side,
                        size=_safe_float(self.cfg.size, 0.0),
                        entry_price=entry_price,
                        order_id=order_id,
                    )

                # ✅ Upload AI Log immediately (router + decision transparency)
                try:
                    self.ai_logger.model_name = model_name  # keep model name consistent
                    ai_payload = self.ai_logger.build_payload(
                        order_id=order_id,
                        router=router,
                        decision=decision,
                        execution={
                            "symbol": self.cfg.symbol,
                            "ticker": ticker,
                            "side": direction,
                            "size": self.cfg.size,
                            "leverage": self.cfg.leverage,
                            "order_response": resp,
                            "order_payload": payload,
                        },
                        stage="Decision Making",
                    )
                    self.ai_logger.upload(client=self.client, payload=ai_payload)
                except Exception as log_err:
                    print("⚠️ AI log upload failed (open):", log_err)

                print(f"✅ OPEN {opened_side} executed order_id={order_id}")
                return True, order_id

            except Exception as e:
                print(f"❌ OPEN attempt {attempt} failed: {e}")
                time.sleep(1.0)

        return False, order_id

    # ----------------------------
    # CLOSE
    # ----------------------------

    def close_position(
        self,
        *,
        reason: str,
        router: Dict[str, Any],
        decision: Dict[str, Any],
        ticker: Dict[str, Any],
        model_name: str,
    ) -> Tuple[bool, Optional[int]]:
        """
        Close existing position ONLY if one exists.
        """
        if self.cfg.dry_run:
            self._log_event("dry_run_close_blocked", reason=reason, symbol=self.cfg.symbol)
            return True, None

        self.pm.sync_from_exchange()
        if not self.pm.has_position():
            return False, None

        pos_side = self.pm.get_side()
        close_order_id: Optional[int] = None

        for attempt in range(1, self.cfg.max_close_retries + 1):
            try:
                payload = {
                    "symbol": self.cfg.symbol,
                    "client_oid": str(_now_ms()),
                    "size": self.cfg.size,
                    "type": self._close_type(pos_side),
                    "order_type": "0",
                    "match_price": "1",
                    "price": "0",
                }

                resp = self.client.place_order(payload)
                close_order_id = int(resp.get("order_id")) if resp and resp.get("order_id") else None

                # ✅ Upload AI Log immediately (router + decision transparency)
                try:
                    self.ai_logger.model_name = model_name
                    ai_payload = self.ai_logger.build_payload(
                        order_id=close_order_id,
                        router=router,
                        decision=decision,
                        execution={
                            "symbol": self.cfg.symbol,
                            "ticker": ticker,
                            "side": f"CLOSE_{pos_side}",
                            "size": self.cfg.size,
                            "leverage": self.cfg.leverage,
                            "order_response": resp,
                            "order_payload": payload,
                            "reason": reason,
                        },
                        stage="Risk / Exit",
                    )
                    self.ai_logger.upload(client=self.client, payload=ai_payload)
                except Exception as log_err:
                    print("⚠️ AI log upload failed (close):", log_err)

                # Sync to confirm close
                self.pm.sync_from_exchange()
                if self.pm.has_position():
                    print("⚠️ Close sent but position still exists. Retrying...")
                    time.sleep(1.0)
                    continue

                self.pm.set_closed(close_order_id=close_order_id)

                print(f"✅ CLOSE executed order_id={close_order_id} reason={reason}")
                return True, close_order_id

            except Exception as e:
                print(f"❌ CLOSE attempt {attempt} failed: {e}")
                time.sleep(1.0)

        return False, close_order_id

    # ----------------------------
    # Exit Logic
    # ----------------------------

    def should_exit(self, router: Dict[str, Any], ticker: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Decide if we should exit current position.
        Returns (exit_now?, reason)
        """
        if not self.pm.has_position():
            return False, "no_position"

        last = _safe_float(ticker.get("last") or ticker.get("markPrice") or 0.0)
        entry = self.pm.get_entry_price()
        if entry <= 0 or last <= 0:
            return False, "unknown_prices"

        pnl_pct = _pct_change(last, entry)
        side = self.pm.get_side()

        # short pnl is inverted
        if side == "SHORT":
            pnl_pct = -pnl_pct

        # TP / SL
        if pnl_pct >= self.cfg.take_profit_pct:
            return True, f"take_profit_hit ({pnl_pct*100:.3f}%)"

        if pnl_pct <= -self.cfg.stop_loss_pct:
            return True, f"stop_loss_hit ({pnl_pct*100:.3f}%)"

        # Time stop
        if self.pm.get_age_seconds() >= self.cfg.max_hold_minutes * 60:
            return True, "time_stop"

        # Regime flip exit
        if self.cfg.regime_flip_exit:
            regime = str(router.get("regime") or "")
            if side == "LONG" and regime in ("DOWNTREND", "CHOP"):
                return True, f"regime_flip_exit ({regime})"
            if side == "SHORT" and regime in ("UPTREND", "CHOP"):
                return True, f"regime_flip_exit ({regime})"

        return False, "hold"

    # ----------------------------
    # Main Manage Hook
    # ----------------------------

    def manage(
        self,
        *,
        router: Dict[str, Any],
        decision: Dict[str, Any],
        ticker: Dict[str, Any],
        model_name: str,
    ) -> Dict[str, Any]:
        """
        Lifecycle:
        - If position open: exit management
        - Else: open if decision says BUY/SELL
        """
        if not self.cfg.dry_run:
            self.pm.sync_from_exchange()

        # 1) If holding position -> manage exits
        if self.pm.has_position():
            exit_now, reason = self.should_exit(router=router, ticker=ticker)
            if exit_now:
                ok, close_id = self.close_position(
                    reason=reason,
                    router=router,
                    decision=decision,
                    ticker=ticker,
                    model_name=model_name,
                )
                return {"action": "CLOSE", "ok": ok, "order_id": close_id, "reason": reason}

            return {
                "action": "HOLD_POSITION",
                "ok": True,
                "reason": "no_exit_signal",
                "position": self.pm.summary(),
            }

        # 2) No position -> open if BUY/SELL
        d = decision.get("decision")
        if d not in ("BUY", "SELL"):
            self._log_event("trade_blocked", action="NO_TRADE", reason="decision_hold", decision=d)
            return {"action": "NO_TRADE", "ok": True, "reason": "decision_hold"}

        approved, risk_reason = self._validate_entry(decision)
        if not approved:
            self._log_event("trade_blocked", action="ENTRY", reason=risk_reason, decision=d)
            return {"action": "BLOCKED", "ok": False, "reason": risk_reason}

        if self.cfg.dry_run:
            self._log_event("dry_run_entry", action="OPEN", direction=d, reason=risk_reason)
            return {"action": "DRY_RUN_OPEN", "ok": True, "order_id": None, "reason": risk_reason}

        ok, open_id = self.open_position(
            direction=d,
            router=router,
            decision=decision,
            ticker=ticker,
            model_name=model_name,
        )
        return {"action": "OPEN", "ok": ok, "order_id": open_id, "reason": "entry_signal"}
