"""
OmniQuantAI - WEEX AI Logger
===========================

Uploads AI decision logs to WEEX:
POST /capi/v2/order/uploadAiLog

Required fields:
- model version
- input + output
- order execution details
- natural language explanation (<= 1000 chars)

This logger is designed to make judges see:
✅ regime routing (transparency)
✅ decision scoring + explanation
✅ execution payload + returned orderId
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from weex.client import WEEXClient


# ============================================================
# Helpers
# ============================================================

def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_str(x: Any, max_len: int = 350) -> str:
    """
    Convert to string and truncate for safe logging.
    """
    s = str(x)
    if len(s) > max_len:
        return s[:max_len] + "…"
    return s


def _truncate_explanation(text: str, max_len: int = 1000) -> str:
    """
    WEEX says explanation max length is 1000 chars.
    """
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# ============================================================
# AI Logger
# ============================================================

class AILogger:
    def __init__(self, client: WEEXClient, model_name: str = "OmniQuantAI-v0.1"):
        self.client = client
        self.model_name = model_name

    def build_payload(
        self,
        *,
        stage: str,
        symbol: str,
        router: Dict[str, Any],
        decision: Dict[str, Any],
        ticker: Dict[str, Any],
        order_id: Optional[str] = None,
        order_payload: Optional[Dict[str, Any]] = None,
        extra_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Builds a WEEX-compliant ai_log JSON.
        """

        # ---- Router summary (for judges) ----
        router_summary = {
            "regime": router.get("regime"),
            "trend_score": router.get("trend_score"),
            "chop_score": router.get("chop_score"),
            "confidence": router.get("confidence"),
            "reason": router.get("reason"),
            "thresholds": router.get("thresholds"),
        }

        # ---- Decision summary (for judges) ----
        decision_summary = {
            "decision": decision.get("decision"),
            "score": decision.get("score"),
            "confidence": decision.get("confidence"),
            "signals": decision.get("signals"),
            "explanation": decision.get("explanation"),  # per-signal contributions
            "reason": decision.get("reason"),
        }

        # ---- Ticker (inputs) ----
        # keep only key fields judges care about
        ticker_min = {
            "symbol": ticker.get("symbol", symbol),
            "last": ticker.get("last"),
            "best_bid": ticker.get("best_bid"),
            "best_ask": ticker.get("best_ask"),
            "markPrice": ticker.get("markPrice"),
            "indexPrice": ticker.get("indexPrice"),
            "volume_24h": ticker.get("volume_24h"),
            "priceChangePercent": ticker.get("priceChangePercent"),
            "timestamp": ticker.get("timestamp"),
        }

        # ---- Human explanation (<=1000 chars) ----
        human_explanation = (
            f"RegimeRouter classified {symbol} as '{router.get('regime')}' "
            f"(trend_score={router.get('trend_score')}, chop_score={router.get('chop_score')}). "
            f"DecisionEngine output decision={decision.get('decision')} "
            f"with score={decision.get('score')} and confidence={decision.get('confidence')}. "
            f"Signal contributions={_safe_str(decision.get('explanation'), 350)}. "
        )

        if order_id:
            human_explanation += f"Trade executed on WEEX. orderId={order_id}. "
        else:
            human_explanation += "No order executed (HOLD / blocked / exit-only). "

        if extra_notes:
            human_explanation += _safe_str(extra_notes, 250)

        human_explanation = _truncate_explanation(human_explanation, 1000)

        # ---- WEEX payload ----
        payload: Dict[str, Any] = {
            # orderId is "Long No" -> optional
            "orderId": int(order_id) if order_id else None,
            "stage": stage,
            "model": self.model_name,
            "input": {
                "prompt": (
                    "Analyze WEEX futures market regime and decide trade action "
                    "(BUY/SELL/HOLD)."
                ),
                "symbol": symbol,
                "router": router_summary,
                "ticker": ticker_min,
            },
            "output": {
                "decision": decision_summary,
                "order_execution": {
                    "executed": bool(order_id),
                    "order_id": order_id,
                    "order_payload": order_payload,
                },
            },
            "explanation": human_explanation,
        }

        return payload

    def upload(
        self,
        *,
        stage: str,
        symbol: str,
        router: Dict[str, Any],
        decision: Dict[str, Any],
        ticker: Dict[str, Any],
        order_id: Optional[str] = None,
        order_payload: Optional[Dict[str, Any]] = None,
        extra_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Uploads the AI log to WEEX.
        """

        payload = self.build_payload(
            stage=stage,
            symbol=symbol,
            router=router,
            decision=decision,
            ticker=ticker,
            order_id=order_id,
            order_payload=order_payload,
            extra_notes=extra_notes,
        )

        print("\n🧾 Uploading AI Log...")
        print("➡️ stage:", stage)
        print("➡️ symbol:", symbol)
        print("➡️ order_id:", order_id)

        # This is signed by WEEXClient internally
        resp = self.client.private_post("/capi/v2/order/uploadAiLog", payload)

        print("✅ AI log uploaded:", resp)
        return resp
