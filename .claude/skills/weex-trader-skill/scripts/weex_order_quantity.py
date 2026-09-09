#!/usr/bin/env python3
"""Normalize WEEX Futures order quantity semantics before risk or REST writes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


BASE_ASSET = "BASE_ASSET"
CONTRACTS = "CONTRACTS"
SUPPORTED_QUANTITY_UNITS = frozenset({BASE_ASSET, CONTRACTS})


class QuantitySemanticsError(ValueError):
    """Raised when an order quantity cannot be mapped unambiguously."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_order_quantity(
    *,
    market: str,
    order: dict[str, Any],
    symbol_facts: dict[str, Any] | None = None,
    require_explicit_unit: bool = False,
) -> dict[str, Any]:
    """Return one explicit Futures quantity mapping.

    The current WEEX contract endpoints use base-asset quantity. Contract counts
    are converted with the official symbol ``contractVal`` exactly once.
    """
    if not isinstance(order, dict):
        raise QuantitySemanticsError("ORDER_REQUIRED", "order must be an object")
    normalized_market = _enum(market, "market", {"FUTURES"}, error_code="MARKET_UNSUPPORTED")
    input_quantity = _positive_decimal(order.get("quantity"), "quantity")
    raw_unit = _pick(order, "quantity_unit", "quantityUnit")
    if raw_unit in (None, ""):
        if require_explicit_unit:
            raise QuantitySemanticsError(
                "QUANTITY_UNIT_REQUIRED",
                "quantity_unit is required for a structured order",
            )
        input_unit = BASE_ASSET
    else:
        input_unit = _enum(
            raw_unit,
            "quantity_unit",
            SUPPORTED_QUANTITY_UNITS,
            error_code="QUANTITY_UNIT_UNSUPPORTED",
        )

    facts = symbol_facts if isinstance(symbol_facts, dict) else {}
    contract_val: Decimal | None = None
    if input_unit == CONTRACTS:
        contract_val = _positive_decimal(
            _pick(facts, "contractVal", "contract_value"),
            "contractVal",
            error_code="CONTRACT_VALUE_REQUIRED",
        )
        api_quantity = _multiply(input_quantity, contract_val)
    else:
        api_quantity = input_quantity
        raw_contract_val = _pick(facts, "contractVal", "contract_value")
        if raw_contract_val not in (None, ""):
            contract_val = _positive_decimal(
                raw_contract_val,
                "contractVal",
                error_code="CONTRACT_VALUE_INVALID",
            )

    return {
        "input_quantity": _decimal_text(input_quantity),
        "input_unit": input_unit,
        "api_quantity": _decimal_text(api_quantity),
        "api_quantity_unit": BASE_ASSET,
        "contract_val": None if contract_val is None else _decimal_text(contract_val),
    }


def normalize_order_for_api(
    *,
    market: str,
    order: dict[str, Any],
    symbol_facts: dict[str, Any] | None = None,
    require_explicit_unit: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a copy of ``order`` with normalized API quantity and semantics."""
    semantics = normalize_order_quantity(
        market=market,
        order=order,
        symbol_facts=symbol_facts,
        require_explicit_unit=require_explicit_unit,
    )
    normalized_order = dict(order)
    normalized_order["quantity"] = semantics["api_quantity"]
    normalized_order.pop("quantity_unit", None)
    normalized_order.pop("quantityUnit", None)
    return normalized_order, semantics


def _pick(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _enum(
    value: Any,
    field: str,
    allowed: set[str] | frozenset[str],
    *,
    error_code: str | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QuantitySemanticsError(
            error_code or f"{field.upper()}_INVALID",
            f"{field} must be a non-empty string",
        )
    normalized = value.strip().upper()
    if normalized not in allowed:
        raise QuantitySemanticsError(
            error_code or f"{field.upper()}_UNSUPPORTED",
            f"{field} is unsupported",
        )
    return normalized


def _positive_decimal(
    value: Any,
    field: str,
    *,
    error_code: str | None = None,
) -> Decimal:
    if isinstance(value, bool) or value in (None, ""):
        raise QuantitySemanticsError(
            error_code or f"{field.upper()}_INVALID",
            f"{field} must be greater than zero",
        )
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise QuantitySemanticsError(
            error_code or f"{field.upper()}_INVALID",
            f"{field} must be a valid Decimal value",
        ) from exc
    if not decimal_value.is_finite() or decimal_value <= 0:
        raise QuantitySemanticsError(
            error_code or f"{field.upper()}_INVALID",
            f"{field} must be greater than zero",
        )
    return decimal_value


def _multiply(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(28, len(left.as_tuple().digits) + len(right.as_tuple().digits) + 8)
        return left * right


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


__all__ = [
    "BASE_ASSET",
    "CONTRACTS",
    "QuantitySemanticsError",
    "SUPPORTED_QUANTITY_UNITS",
    "normalize_order_for_api",
    "normalize_order_quantity",
]
