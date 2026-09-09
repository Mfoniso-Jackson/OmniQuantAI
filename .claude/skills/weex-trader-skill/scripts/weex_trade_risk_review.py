#!/usr/bin/env python3
"""Trader-local wrappers around the vendored WEEX risk review core."""

from __future__ import annotations

from typing import Any

from weex_risk_review_core import analyze_account_risk as _analyze_account_risk
from weex_risk_review_core import analyze_order_risk as _analyze_order_risk


STANDARD_ANALYSIS_DISCLAIMER = (
    "Disclaimer: This result is generated solely from the current input data and is for reference only. "
    "It does not constitute any investment or trading advice. Please make your own independent judgment "
    "based on real-time data, official rules, and your own risk tolerance. Responsibility for related "
    "decisions and execution rests solely with the user."
)


def _attach_standard_disclaimer(result: dict[str, Any]) -> dict[str, Any]:
    updated = dict(result)
    updated["disclaimer"] = STANDARD_ANALYSIS_DISCLAIMER
    return updated


def analyze_order_risk(payload: Any) -> dict[str, Any]:
    return _attach_standard_disclaimer(_analyze_order_risk(payload))


def analyze_account_risk(payload: Any) -> dict[str, Any]:
    return _attach_standard_disclaimer(_analyze_account_risk(payload))


__all__ = ["analyze_order_risk", "analyze_account_risk"]
