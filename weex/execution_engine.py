"""
WEEX Execution Engine (OmniQuantAI)
----------------------------------
Purpose:
- Execute trades on WEEX futures (open + close)
- Manage exits intelligently (TP/SL, time-stop, regime flip)
- Upload AI logs immediately after execution (AI Wars compliance)

Endpoints used:
- POST /capi/v2/order/placeOrder
- GET  /capi/v2/order/history
- GET  /capi/v2/order/fills
- GET  /capi/v2/account/position/singlePosition
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

from weex.client import WEEXClient
from weex.ai_logger import build_ai_log_payload, upload_ai_log


# ============================================================
# Position State
# ============================================================

@dataclass
class PositionState:
    symbol: str
    side: str                 # "LONG" or "SHORT"
    size: float               # position size in BTC (or contract-size unit as API returns)
    entry_price: float
    opened_at_ms: int
    last_update_ms: int

    def age_seconds(self) -> float:
        return (int(time.time() * 1000) - self.opened_at_ms) / 1000.0


# ============================================================
# Execution Engine Config
# ============================================================

@dataclass
class ExecutionConfig:
    # execution
    symbol: str = "cmt_btcusdt"
    size: str = "0.0010"        # BTC size string
    leverage: int = 3

    # exits
    take_profit_pct: float = 0.25 / 100     # +0.25%
    stop_loss_pct: float = 0.20 / 100       # -0.20%
    max_hold_minutes: int = 45              # time-stop
    regime_flip_exit: bool = True           # close if regime changes against position

    # safety
    max_close_retries: int = 2
    max_open_retries: int = 2


# ============================================================
# Helpers
# ============================================================

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
    Handles position lifecycle:
    - open_position()
    - close_position()
    - manage_position() (exit logic)
    """

    def __init__(self, client: WEEXClient, cfg: ExecutionConfig):
        self.client = client
        self.cfg = cfg
        self.position: Optional[PositionState] = None

    # ----------------------------
    # Position Sync
    # ----------------------------

    def fetch_position(self) -> Optional[PositionState]:
        """
        Pull live position from WEEX (singlePosition endpoint).
        If none, return None.
        """
        # WEEX demo uses:
        # GET /capi/v2/account/position/singlePosition?symbol=cmt_btcusdt
        data = self.client.get_single_position(self.cfg.symbol)

        # The format can vary; we handle common cases safely.
        # Expect: {"symbol":..., "positionSide": "LONG", "positionAmt": "...", "avgPrice": "..."}
        if not data:
            return None

        # Some accounts return list; some return dict
        if isinstance(data, list) and len(data) > 0:
            pos = data[0]
        elif isinstance(data, dict):
            pos = data
        else:
            return None

        size = _safe_float(pos.get("positionAmt") or pos.get("size") or 0.0)
        if size == 0.0:
            return None

        side = str(pos.get("positionSide") or pos.get("side") or "").upper()
        if side not in ("LONG", "SHORT"):
            # some formats might use "BUY"/"SELL"
            if side == "BUY":
                side = "LONG"
            elif side == "SELL":
                side = "SHORT"
            else:
                side = "LONG"

        entry_price = _safe_float(pos.get("avgPrice") or pos.get("entryPrice") or 0.0)
        now = _now_ms()

        # If we already have a local position, keep its opened_at
        opened_at = self.position.opened_at_ms if self.position else now

        self.position = PositionState(
            symbol=self.cfg.symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            opened_at_ms=opened_at,
            last_update_ms=now,
        )
        return self.position

    # ----------------------------
    # Open/Close mapping
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
    # Open position
    # ----------------------------

    def open_position(
        self,
        *,
        direction: str,                 # "BUY" opens long, "SELL" opens short
        router: Dict[str, Any],
        decision: Dict[str, Any],
        ticker: Dict[str, Any],
        model_name: str,
    ) -> Tuple[bool, Optional[int]]:
        """
        Open a position and upload AI log.
        Returns (success, order_id)
        """
        order_id: Optional[int] = None

        for attempt in range(1, self.cfg.max_open_retries + 1):
            try:
                payload = {
                    "symbol": self.cfg.symbol,
                    "client_oid": str(_now_ms()),
                    "size": self.cfg.size,
                    "type": self._open_type(direction),
                    "order_type": "0",
                    "match_price": "1",
                    "price": "0",
                }

                resp = self.client.place_order(payload)
                order_id = int(resp.get("order_id")) if resp and resp.get("order_id") else None

                execution = {
                    "symbol": self.cfg.symbol,
                    "action": "OPEN",
                    "direction": direction,
                    "size": self.cfg.size,
                    "leverage": self.cfg.leverage,
                    "ticker_last": ticker.get("last"),
                    "order_payload": payload,
                    "order_response": resp,
                }

                ai_payload = build_ai_log_payload(
                    order_id=order_id,
                    stage="Decision Making",
                    model=model_name,
                    router=router,
                    decision=decision,
                    execution=execution,
                )
                upload_ai_log(ai_payload)

                # Refresh local position state
                self.fetch_position()

                print(f"✅ OPEN executed ({direction}) order_id={order_id}")
                return True, order_id

            except Exception as e:
                print(f"❌ OPEN failed attempt {attempt}: {e}")
                time.sleep(1.0)

        return False, order_id

    # ----------------------------
    # Close position
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
        Close current open position (if any) and upload AI log.
        Returns (success, close_order_id)
        """
        if not self.position:
            return False, None

        close_order_id: Optional[int] = None
        pos_side = self.position.side

        for attempt in range(1, self.cfg.max_close_retries + 1):
            try:
                payload = {
                    "symbol": self.cfg.symbol,
                    "client_oid": str(_now_ms()),
                    # close same size we opened
                    "size": self.cfg.size,
                    "type": self._close_type(pos_side),   # "3" close long, "4" close short
                    "order_type": "0",
                    "match_price": "1",
                    "price": "0",
                }

                resp = self.client.place_order(payload)
                close_order_id = int(resp.get("order_id")) if resp and resp.get("order_id") else None

                execution = {
                    "symbol": self.cfg.symbol,
                    "action": "CLOSE",
                    "position_side": pos_side,
                    "size": self.cfg.size,
                    "ticker_last": ticker.get("last"),
                    "reason": reason,
                    "order_payload": payload,
                    "order_response": resp,
                }

                ai_payload = build_ai_log_payload(
                    order_id=close_order_id,
                    stage="Risk / Exit",
                    model=model_name,
                    router=router,
                    decision=decision,
                    execution=execution,
                )
                upload_ai_log(ai_payload)

                print(f"✅ CLOSE executed ({pos_side}) order_id={close_order_id} reason={reason}")

                # Clear local state
                self.position = None
                return True, close_order_id

            except Exception as e:
                print(f"❌ CLOSE failed attempt {attempt}: {e}")
                time.sleep(1.0)

        return False, close_order_id

    # ----------------------------
    # Exit logic (intelligent)
    # ----------------------------

    def should_exit(
        self,
        *,
        router: Dict[str, Any],
        ticker: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """
        Decide if we should exit current position.
        Returns (exit?, reason)
        """
        if not self.position:
            return False, "no_position"

        last = _safe_float(ticker.get("last") or ticker.get("markPrice") or 0.0)
        entry = float(self.position.entry_price)

        # If entry price unknown, don't attempt logic exit
        if entry <= 0:
            return False, "unknown_entry_price"

        pnl_pct = _pct_change(last, entry)

        # pnl direction depends on long/short
        if self.position.side == "SHORT":
            pnl_pct = -pnl_pct

        # 1) Take Profit
        if pnl_pct >= self.cfg.take_profit_pct:
            return True, f"take_profit_hit ({pnl_pct*100:.3f}%)"

        # 2) Stop Loss
        if pnl_pct <= -self.cfg.stop_loss_pct:
            return True, f"stop_loss_hit ({pnl_pct*100:.3f}%)"

        # 3) Time stop
        if self.position.age_seconds() >= self.cfg.max_hold_minutes * 60:
            return True, "time_stop"

        # 4) Regime flip exit
        if self.cfg.regime_flip_exit:
            regime = router.get("regime", "")
            if self.position.side == "LONG" and regime in ("DOWNTREND", "CHOP"):
                return True, f"regime_flip_exit ({regime})"
            if self.position.side == "SHORT" and regime in ("UPTREND", "CHOP"):
                return True, f"regime_flip_exit ({regime})"

        return False, "hold"

    # ----------------------------
    # Main position manager hook
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
        High-level lifecycle:
        - If position open: check exits, close if needed
        - If no position: allow open based on decision
        """
        # keep position sync fresh
        self.fetch_position()

        # If position is open -> manage exit
        if self.position:
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
            return {"action": "HOLD_POSITION", "ok": True, "reason": "no_exit_signal"}

        # If no position -> open only if BUY/SELL
        d = decision.get("decision")
        if d not in ("BUY", "SELL"):
            return {"action": "NO_TRADE", "ok": True, "reason": "decision_hold"}

        ok, open_id = self.open_position(
            direction=d,
            router=router,
            decision=decision,
            ticker=ticker,
            model_name=model_name,
        )
        return {"action": "OPEN", "ok": ok, "order_id": open_id, "reason": "entry_signal"}
