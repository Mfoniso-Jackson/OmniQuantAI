"""
WEEX Position Manager (OmniQuantAI)
----------------------------------
Purpose:
- Maintain a reliable view of current position state
- Sync from WEEX API (source of truth)
- Persist locally to survive restarts (JSON file)

Used by:
- execution_engine.py
- run.py (main loop)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

from weex.client import WEEXClient


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


# ============================================================
# Canonical Position Schema
# ============================================================

@dataclass
class PositionState:
    symbol: str
    side: str                  # "LONG" or "SHORT"
    size: float                # numeric
    entry_price: float
    opened_at_ms: int
    last_update_ms: int
    last_order_id: Optional[int] = None
    last_close_order_id: Optional[int] = None

    def age_seconds(self) -> float:
        return (_now_ms() - self.opened_at_ms) / 1000.0


# ============================================================
# Position Manager
# ============================================================

class PositionManager:
    """
    Keeps local position state in sync with WEEX.

    Key features:
    - Sync from exchange (singlePosition)
    - Save/load local state (JSON)
    - Provide safe helpers for execution layer
    """

    def __init__(
        self,
        client: WEEXClient,
        symbol: str = "cmt_btcusdt",
        state_file: str = "weex/position_state.json",
    ):
        self.client = client
        self.symbol = symbol
        self.state_file = state_file
        self.position: Optional[PositionState] = None

        # load from disk on boot (restart-safe)
        self.load()

    # ----------------------------
    # Persistence
    # ----------------------------

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)

        payload = {
            "saved_at_ms": _now_ms(),
            "symbol": self.symbol,
            "position": asdict(self.position) if self.position else None,
        }

        with open(self.state_file, "w") as f:
            json.dump(payload, f, indent=2)

    def load(self) -> None:
        if not os.path.exists(self.state_file):
            return

        try:
            with open(self.state_file, "r") as f:
                raw = json.load(f)

            p = raw.get("position")
            if not p:
                self.position = None
                return

            self.position = PositionState(
                symbol=p["symbol"],
                side=p["side"],
                size=float(p["size"]),
                entry_price=float(p["entry_price"]),
                opened_at_ms=int(p["opened_at_ms"]),
                last_update_ms=int(p["last_update_ms"]),
                last_order_id=p.get("last_order_id"),
                last_close_order_id=p.get("last_close_order_id"),
            )

        except Exception:
            # if file corrupted, ignore
            self.position = None

    # ----------------------------
    # Core Queries
    # ----------------------------

    def has_position(self) -> bool:
        return self.position is not None and self.position.size > 0

    def get_side(self) -> Optional[str]:
        return self.position.side if self.position else None

    def get_size(self) -> float:
        return float(self.position.size) if self.position else 0.0

    def get_entry_price(self) -> float:
        return float(self.position.entry_price) if self.position else 0.0

    def get_age_seconds(self) -> float:
        return self.position.age_seconds() if self.position else 0.0

    # ----------------------------
    # State Updates (Local)
    # ----------------------------

    def set_open(
        self,
        side: str,
        size: float,
        entry_price: float,
        order_id: Optional[int] = None,
    ) -> None:
        now = _now_ms()
        self.position = PositionState(
            symbol=self.symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            opened_at_ms=now,
            last_update_ms=now,
            last_order_id=order_id,
            last_close_order_id=None,
        )
        self.save()

    def set_closed(self, close_order_id: Optional[int] = None) -> None:
        if self.position:
            self.position.last_close_order_id = close_order_id
        self.position = None
        self.save()

    def touch(self) -> None:
        """Update timestamp only."""
        if self.position:
            self.position.last_update_ms = _now_ms()
            self.save()

    # ----------------------------
    # Sync from WEEX (Source of Truth)
    # ----------------------------

    def sync_from_exchange(self) -> Optional[PositionState]:
        """
        Sync local position with what WEEX reports.
        This prevents:
        - double-entries after restart
        - phantom positions
        - wrong exit sizing

        WEEX endpoint:
        GET /capi/v2/account/position/singlePosition?symbol=...
        """
        data = self.client.get_single_position(self.symbol)

        # If WEEX says "no position"
        if not data:
            if self.position is not None:
                self.position = None
                self.save()
            return None

        # Some accounts return list; some return dict
        if isinstance(data, list) and len(data) > 0:
            pos = data[0]
        elif isinstance(data, dict):
            pos = data
        else:
            return self.position

        # Try to parse size
        size = _safe_float(pos.get("positionAmt") or pos.get("size") or 0.0)
        if size == 0.0:
            # no open position
            if self.position is not None:
                self.position = None
                self.save()
            return None

        side = str(pos.get("positionSide") or pos.get("side") or "").upper()
        if side not in ("LONG", "SHORT"):
            if side == "BUY":
                side = "LONG"
            elif side == "SELL":
                side = "SHORT"
            else:
                side = "LONG"

        entry_price = _safe_float(pos.get("avgPrice") or pos.get("entryPrice") or 0.0)

        now = _now_ms()

        # If local position exists, keep its opened_at_ms (more accurate for time-stop)
        opened_at = self.position.opened_at_ms if self.position else now

        self.position = PositionState(
            symbol=self.symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            opened_at_ms=opened_at,
            last_update_ms=now,
            last_order_id=self.position.last_order_id if self.position else None,
            last_close_order_id=self.position.last_close_order_id if self.position else None,
        )

        self.save()
        return self.position

    # ----------------------------
    # Convenience summary
    # ----------------------------

    def summary(self) -> Dict[str, Any]:
        if not self.position:
            return {"symbol": self.symbol, "position": None}

        return {
            "symbol": self.symbol,
            "position": {
                "side": self.position.side,
                "size": self.position.size,
                "entry_price": self.position.entry_price,
                "age_seconds": round(self.position.age_seconds(), 2),
                "last_order_id": self.position.last_order_id,
                "last_close_order_id": self.position.last_close_order_id,
            },
        }
