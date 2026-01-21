"""
OmniQuantAI - WEEX AI Logger
===========================

Uploads AI decision logs to WEEX:
POST /capi/v2/order/uploadAiLog

WEEX requires:
- model
- input (JSON)
- output (JSON)
- explanation (<= 1000 chars)
- orderId (optional)

This logger is judge-friendly:
✅ regime routing transparency
✅ decision score + explanation
✅ order execution details
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from weex.client import WEEXClient


# ============================================================
# Helpers
# ============================================================

def _safe_str(x: Any, max_len: int = 350) -> str:
    s = str(x)
    if len(s) > max_len:
        return s[:max_len] + "…"
    return s


def _truncate(text: str, max_len: int = 1000) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# ============================================================
# AI Logger
# ============================================================

class AILogger:
    """
    Build + Upload WEEX AI logs.

    Use pattern:
        logger = AILogger(model_name="OmniQuantAI-v0.1", default_stage="Decision Making")
        payload = logger.build_payload(...)
        logger.upload(client, payload)
    """

    def __init__(
        self,
        model_name: str = "OmniQuantAI-v0.1",
        default_stage: str = "Decision Making",
        enabled: bool = True,
    ):
        self.model_name = model_name
        self.default_stage = default_stage
        self.enabled = enabled

    def build_payload(
        self,
        *,
        order_id: Optional[int],
        router: Dict[str, Any],
        decision: Dict[str, Any],
        execution: Dict[str, Any],
        stage: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Returns WEEX-compliant JSON payload.
        """

        stage = stage or self.default_stage
        symbol = str(execution.get("symbol") or router.get("symbol") or "UNKNOWN")

        # ----------------------------
        # Inputs (what AI saw)
        # ----------------------------
        ai_input = {
            "prompt": "Classify regime (trend/chop/vol) and output a BUY/SELL/HOLD decision for WEEX futures execution.",
            "symbol": symbol,
            "router": {
                "regime": router.get("regime"),
                "confidence": router.get("confidence"),
                "trend_score": router.get("trend_score"),
                "chop_score": router.get("chop_score"),
                "vol_score": router.get("vol_score"),
                "thresholds": router.get("thresholds"),
                "why": router.get("why") or router.get("reason"),
            },
            "market": execution.get("ticker", {}),
        }

        # ----------------------------
        # Outputs (what AI decided)
        # ----------------------------
        ai_output = {
            "signal": decision.get("decision"),  # BUY / SELL / HOLD
            "confidence": decision.get("confidence"),
            "score": decision.get("score"),
            "signal_contributions": decision.get("explanation"),
            "signals_raw": decision.get("signals"),
            "execution": {
                "executed": bool(order_id),
                "orderId": order_id,
                "side": execution.get("side"),
                "size": execution.get("size"),
                "leverage": execution.get("leverage"),
                "order_response": execution.get("order_response"),
            },
        }

        # ----------------------------
        # Judge-facing explanation (<= 1000 chars)
        # ----------------------------
        explanation = (
            f"RegimeRouter={ai_input['router'].get('regime')} "
            f"(trend={ai_input['router'].get('trend_score')}, chop={ai_input['router'].get('chop_score')}, "
            f"vol={ai_input['router'].get('vol_score')}, conf={ai_input['router'].get('confidence')}). "
            f"Decision={ai_output.get('signal')} score={ai_output.get('score')} conf={ai_output.get('confidence')}. "
            f"Contrib={_safe_str(ai_output.get('signal_contributions'), 300)}. "
        )

        if order_id:
            explanation += f"Order executed on WEEX. orderId={order_id}."
        else:
            explanation += "No order executed."

        explanation = _truncate(explanation, 1000)

        payload: Dict[str, Any] = {
            "orderId": order_id,  # optional
            "stage": stage,
            "model": self.model_name,
            "input": ai_input,
            "output": ai_output,
            "explanation": explanation,
        }

        return payload

    def upload(self, *, client: WEEXClient, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upload payload to WEEX endpoint.
        """
        if not self.enabled:
            return {"code": "SKIPPED", "msg": "ai_log disabled", "data": None}

        print("\n🧾 Uploading AI Log...")
        print("➡️ stage:", payload.get("stage"))
        print("➡️ orderId:", payload.get("orderId"))
        print("➡️ model:", payload.get("model"))

        resp = client.private_post("/capi/v2/order/uploadAiLog", payload)

        print("✅ AI Log Uploaded:", resp)
        return resp
