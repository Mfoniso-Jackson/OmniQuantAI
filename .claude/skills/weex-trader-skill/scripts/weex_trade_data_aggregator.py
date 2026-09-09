#!/usr/bin/env python3
"""Collect contract-only WEEX trading data for AI Wars risk flows."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from weex_order_quantity import (
    BASE_ASSET,
    CONTRACTS,
    QuantitySemanticsError,
    normalize_order_for_api,
)
from weex_profile_language import resolve_language


DAY_MS = 24 * 60 * 60 * 1000
HOUR_MS = 60 * 60 * 1000
REPLAY_PERIODS = ("7d", "30d", "90d")
PROFILE_PERIODS = ("30d", "90d", "180d", "360d")
PROFILE_PERIOD_AUTO = "auto"
PROFILE_MIN_CLOSED_TRADES = 10
COLLECTION_PERIODS = REPLAY_PERIODS + ("180d", "360d")
DEFAULT_TRADING_MODE = "live"
TRADING_MODES = ("live",)
MAX_FUTURES_WINDOW_DAYS = 90
MAX_FUTURES_FILLS_WINDOW_DAYS = 7
MAX_BILLS_WINDOW_DAYS = 100
MIN_SPLIT_WINDOW_MS = HOUR_MS
FUTURES_ORDER_LIMIT = 1000
FUTURES_FILL_LIMIT = 100
FUTURES_BILL_LIMIT = 100
KLINE_LIMIT = 100
RECENT_ORDER_LOOKBACK_MS = 60 * 60 * 1000
RECENT_ORDER_HISTORY_UNAVAILABLE = "recent_order_history_unavailable"


class AggregationInputError(ValueError):
    """Raised when a requested data collection shape is outside AI Wars scope."""


@dataclass(frozen=True)
class TimeWindow:
    start_ms: int
    end_ms: int


def split_time_range(start_ms: int, end_ms: int, *, max_span_days: int) -> list[TimeWindow]:
    if start_ms < 0:
        raise AggregationInputError("start_ms must be non-negative.")
    if end_ms < start_ms:
        raise AggregationInputError("end_ms must be greater than or equal to start_ms.")
    if max_span_days <= 0:
        raise AggregationInputError("max_span_days must be positive.")

    max_span_ms = max_span_days * DAY_MS
    windows: list[TimeWindow] = []
    cursor = start_ms
    while cursor <= end_ms:
        next_end = min(end_ms, cursor + max_span_ms - 1)
        windows.append(TimeWindow(start_ms=cursor, end_ms=next_end))
        cursor = next_end + 1
    return windows


def _validate_replay_period(period: str) -> str:
    normalized = str(period).strip().lower()
    if normalized not in COLLECTION_PERIODS:
        raise AggregationInputError(
            f"Unsupported replay period: {period}. Expected one of {', '.join(COLLECTION_PERIODS)}."
        )
    return normalized


def _validate_profile_period(period: str) -> str:
    normalized = str(period).strip().lower()
    if normalized == PROFILE_PERIOD_AUTO:
        return normalized
    if normalized not in PROFILE_PERIODS:
        expected = ", ".join((PROFILE_PERIOD_AUTO, *PROFILE_PERIODS))
        raise AggregationInputError(f"Unsupported profile period: {period}. Expected one of {expected}.")
    return normalized


def _period_to_days(period: str) -> int:
    return int(period.removesuffix("d"))


def _validate_market(market: str) -> str:
    normalized = str(market).strip().lower()
    if normalized != "futures":
        raise AggregationInputError("market must be futures in AI Wars contract-only mode.")
    return normalized


def _normalize_trading_mode(raw: Any) -> str:
    mode = str(raw or DEFAULT_TRADING_MODE).strip().lower()
    if mode not in TRADING_MODES:
        raise AggregationInputError(f"invalid_trading_mode: expected one of {', '.join(TRADING_MODES)}")
    return mode


def _validate_trading_mode_market(trading_mode: str, market: str) -> str:
    _validate_market(market)
    return _normalize_trading_mode(trading_mode)


def _environment_for_trading_mode(trading_mode: str, market: str) -> dict[str, Any]:
    mode = _validate_trading_mode_market(trading_mode, market)
    return {
        "trading_mode": mode,
        "label": "live",
        "market": "futures",
        "uses_real_funds": True,
        "notice": "This operation targets real WEEX futures trading.",
    }


def _user_environment_prefix(environment: dict[str, Any], language: str | None = None) -> str:
    resolved_language = resolve_language(language)
    _normalize_trading_mode(environment.get("trading_mode"))
    if resolved_language == "zh":
        return "当前交易环境：真实盘"
    return "Current trading mode: real trading"


def _normalize_symbol(raw: Any) -> str:
    return str(raw or "UNKNOWN").strip().upper() or "UNKNOWN"


def _now_ms() -> int:
    return int(time.time() * 1000)


class WeexApiFetcher:
    def _contract_module(self) -> Any:
        import weex_contract_api as contract_api

        return contract_api

    def _build_contract_client(self, profile_name: str) -> tuple[Any, Any]:
        contract_api = self._contract_module()
        contract_api.refresh_agent_records(command="trade-aggregator.contract")
        contract_api.ensure_private_runtime_ready(
            command="trade-aggregator.contract",
            auto_setup=True,
            language=None,
        )
        profile = contract_api.resolve_runtime_profile(
            requested_profile=profile_name,
            allow_invalid_default=False,
        )
        contract_api.require_private_profile(profile)
        base_url = (
            os.getenv("WEEX_CONTRACT_API_BASE")
            or os.getenv("WEEX_API_BASE")
            or (profile.contract_base_url if profile else "")
            or contract_api.DEFAULT_BASE_URL
        )
        locale = os.getenv("WEEX_LOCALE") or contract_api.DEFAULT_LOCALE
        timeout = float(os.getenv("WEEX_API_TIMEOUT", contract_api.DEFAULT_TIMEOUT))
        client = contract_api.WeexContractClient(
            base_url=base_url,
            api_key=None,
            api_secret=None,
            api_passphrase=None,
            locale=locale,
            timeout=timeout,
            profile_name=profile.name if profile else None,
        )
        return contract_api, client

    def _send_contract_request(
        self,
        *,
        profile_name: str,
        endpoint_key: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        contract_api, client = self._build_contract_client(profile_name)
        endpoint = contract_api.ENDPOINTS[endpoint_key]
        contract_api.validate_endpoint_trading_mode(endpoint, "live")
        prepared = client.prepare_request(endpoint, query=query or {}, body=body)
        response = client.send(prepared)
        if not response.get("ok"):
            raise AggregationInputError(f"WEEX contract request failed for {endpoint_key}: {response.get('error')}")
        return response.get("data")

    def fetch_futures_balance(self, *, profile_name: str, trading_mode: str = DEFAULT_TRADING_MODE) -> Any:
        _normalize_trading_mode(trading_mode)
        return self._send_contract_request(
            profile_name=profile_name,
            endpoint_key="account.get_account_balance",
        )

    def fetch_futures_positions(
        self,
        *,
        profile_name: str,
        symbol: str | None = None,
        trading_mode: str = DEFAULT_TRADING_MODE,
    ) -> Any:
        _normalize_trading_mode(trading_mode)
        query = {"symbol": _normalize_symbol(symbol)} if symbol else {}
        return self._send_contract_request(
            profile_name=profile_name,
            endpoint_key="account.get_all_positions",
            query=query,
        )

    def fetch_futures_open_orders(
        self,
        *,
        profile_name: str,
        symbol: str | None = None,
        trading_mode: str = DEFAULT_TRADING_MODE,
    ) -> Any:
        _normalize_trading_mode(trading_mode)
        query = {"symbol": _normalize_symbol(symbol)} if symbol else {}
        return self._send_contract_request(
            profile_name=profile_name,
            endpoint_key="transaction.get_current_order_status",
            query=query,
        )

    def fetch_futures_pending_orders(
        self,
        *,
        profile_name: str,
        symbol: str | None = None,
        trading_mode: str = DEFAULT_TRADING_MODE,
    ) -> Any:
        _normalize_trading_mode(trading_mode)
        query = {"symbol": _normalize_symbol(symbol)} if symbol else {}
        return self._send_contract_request(
            profile_name=profile_name,
            endpoint_key="transaction.get_current_pending_orders",
            query=query,
        )

    def fetch_futures_symbol_facts(self, *, profile_name: str, symbol: str) -> Any:
        return self._send_contract_request(
            profile_name=profile_name,
            endpoint_key="market.get_contract_info",
            query={"symbol": _normalize_symbol(symbol)},
        )

    def fetch_futures_orders(
        self,
        *,
        profile_name: str,
        start_ms: int,
        end_ms: int,
        symbol: str | None = None,
        trading_mode: str = DEFAULT_TRADING_MODE,
    ) -> Any:
        _normalize_trading_mode(trading_mode)
        rows: list[dict[str, Any]] = []
        for window in split_time_range(start_ms, end_ms, max_span_days=MAX_FUTURES_WINDOW_DAYS):
            page = 0
            while True:
                query: dict[str, Any] = {
                    "startTime": window.start_ms,
                    "endTime": window.end_ms,
                    "limit": FUTURES_ORDER_LIMIT,
                    "page": page,
                }
                if symbol:
                    query["symbol"] = _normalize_symbol(symbol)
                page_rows = _payload_items(
                    self._send_contract_request(
                        profile_name=profile_name,
                        endpoint_key="transaction.get_order_history",
                        query=query,
                    )
                )
                _extend_unique_dict_rows(
                    rows,
                    page_rows,
                    identity_keys=("orderId", "clientOrderId", "time", "symbol"),
                )
                if len(page_rows) < FUTURES_ORDER_LIMIT:
                    break
                page += 1
        return rows

    def fetch_futures_historical_pending_orders(
        self,
        *,
        profile_name: str,
        start_ms: int,
        end_ms: int,
        symbol: str | None = None,
        trading_mode: str = DEFAULT_TRADING_MODE,
    ) -> Any:
        _normalize_trading_mode(trading_mode)
        rows: list[dict[str, Any]] = []
        degraded_reasons: list[str] = []
        partial = False

        def collect_window(window_start: int, window_end: int) -> None:
            nonlocal partial
            query: dict[str, Any] = {
                "startTime": window_start,
                "endTime": window_end,
                "limit": FUTURES_ORDER_LIMIT,
            }
            if symbol:
                query["symbol"] = _normalize_symbol(symbol)
            payload = self._send_contract_request(
                profile_name=profile_name,
                endpoint_key="transaction.get_historical_pending_orders",
                query=query,
            )
            _extend_unique_dict_rows(
                rows,
                _payload_items(payload),
                identity_keys=("algoId", "actualOrderId", "createTime", "symbol"),
            )
            if not (isinstance(payload, dict) and payload.get("hasMore")):
                return
            if (window_end - window_start) > MIN_SPLIT_WINDOW_MS:
                midpoint = window_start + ((window_end - window_start) // 2)
                collect_window(window_start, midpoint)
                collect_window(midpoint + 1, window_end)
                return
            partial = True
            _append_unique(
                degraded_reasons,
                "futures_historical_pending_orders_window_truncated",
            )

        for window in split_time_range(start_ms, end_ms, max_span_days=MAX_FUTURES_WINDOW_DAYS):
            collect_window(window.start_ms, window.end_ms)
        return _build_meta_payload(rows, partial=partial, degraded_reasons=degraded_reasons)

    def fetch_futures_fills(
        self,
        *,
        profile_name: str,
        start_ms: int,
        end_ms: int,
        symbol: str | None = None,
        trading_mode: str = DEFAULT_TRADING_MODE,
    ) -> Any:
        _normalize_trading_mode(trading_mode)
        rows: list[dict[str, Any]] = []
        degraded_reasons: list[str] = []
        partial = False

        def collect_window(window_start: int, window_end: int) -> None:
            nonlocal partial
            query: dict[str, Any] = {
                "startTime": window_start,
                "endTime": window_end,
                "limit": FUTURES_FILL_LIMIT,
            }
            if symbol:
                query["symbol"] = _normalize_symbol(symbol)
            page_rows = _payload_items(
                self._send_contract_request(
                    profile_name=profile_name,
                    endpoint_key="transaction.get_trade_details",
                    query=query,
                )
            )
            if len(page_rows) >= FUTURES_FILL_LIMIT and (window_end - window_start) > MIN_SPLIT_WINDOW_MS:
                midpoint = window_start + ((window_end - window_start) // 2)
                collect_window(window_start, midpoint)
                collect_window(midpoint + 1, window_end)
                return
            if len(page_rows) >= FUTURES_FILL_LIMIT:
                partial = True
                _append_unique(degraded_reasons, "futures_fills_limit_hit")
            _extend_unique_dict_rows(
                rows,
                page_rows,
                identity_keys=("id", "tradeId", "orderId", "time", "symbol"),
            )

        for window in split_time_range(start_ms, end_ms, max_span_days=MAX_FUTURES_FILLS_WINDOW_DAYS):
            collect_window(window.start_ms, window.end_ms)
        return _build_meta_payload(rows, partial=partial, degraded_reasons=degraded_reasons)

    def fetch_futures_bills(
        self,
        *,
        profile_name: str,
        start_ms: int,
        end_ms: int,
        symbol: str | None = None,
        trading_mode: str = DEFAULT_TRADING_MODE,
        confirm_live: bool = False,
    ) -> Any:
        _normalize_trading_mode(trading_mode)
        if not confirm_live:
            raise AggregationInputError(
                "collecting contract bills uses a read-only POST and requires --confirm-live"
            )
        rows: list[dict[str, Any]] = []
        degraded_reasons: list[str] = []
        partial = False

        def collect_window(window_start: int, window_end: int) -> None:
            nonlocal partial
            body: dict[str, Any] = {
                "startTime": window_start,
                "endTime": window_end,
                "limit": FUTURES_BILL_LIMIT,
            }
            if symbol:
                body["symbol"] = _normalize_symbol(symbol)
            seen_cursors: set[tuple[str, str]] = set()
            while True:
                payload = self._send_contract_request(
                        profile_name=profile_name,
                        endpoint_key="account.get_contract_bills",
                        body=body,
                    )
                _extend_unique_dict_rows(
                    rows,
                    _payload_items(payload),
                    identity_keys=("billId", "time", "symbol", "incomeType"),
                )
                if not (isinstance(payload, dict) and payload.get("hasNextPage")):
                    return
                next_key = payload.get("nextKey")
                next_key_id = next_key.get("nextKeyId") if isinstance(next_key, dict) else None
                next_key_time = next_key.get("nextKeyTime") if isinstance(next_key, dict) else None
                if next_key_id is not None and next_key_time is not None:
                    cursor = (str(next_key_id), str(next_key_time))
                    if cursor in seen_cursors:
                        partial = True
                        _append_unique(degraded_reasons, "futures_bills_cursor_stalled")
                        return
                    seen_cursors.add(cursor)
                    body["nextKeyId"] = next_key_id
                    body["nextKeyTime"] = next_key_time
                    continue
                if (window_end - window_start) > MIN_SPLIT_WINDOW_MS:
                    midpoint = window_start + ((window_end - window_start) // 2)
                    collect_window(window_start, midpoint)
                    collect_window(midpoint + 1, window_end)
                    return
                partial = True
                _append_unique(degraded_reasons, "futures_bills_window_truncated")
                return

        for window in split_time_range(start_ms, end_ms, max_span_days=MAX_BILLS_WINDOW_DAYS):
            collect_window(window.start_ms, window.end_ms)
        return _build_meta_payload(rows, partial=partial, degraded_reasons=degraded_reasons)

    def fetch_futures_klines(
        self,
        *,
        profile_name: str,
        symbol: str,
        start_ms: int,
        end_ms: int,
        interval: str = "1h",
        trading_mode: str = DEFAULT_TRADING_MODE,
    ) -> Any:
        _normalize_trading_mode(trading_mode)
        return self._send_contract_request(
            profile_name=profile_name,
            endpoint_key="market.get_klines",
            query={
                "symbol": _normalize_symbol(symbol),
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": KLINE_LIMIT,
            },
        )


def _payload_items(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in (
            "items",
            "list",
            "data",
            "rows",
            "positions",
            "orders",
            "balances",
            "symbols",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if key == "data" and isinstance(value, dict):
                nested = _payload_items(value)
                if nested:
                    return nested
        return [payload]
    return []


def _find_symbol_facts(payload: Any, symbol: str) -> dict[str, Any]:
    rows = _payload_items(payload)
    normalized_symbol = _normalize_symbol(symbol)
    matches = [
        item
        for item in rows
        if isinstance(item, dict)
        and _normalize_symbol(item.get("symbol")) == normalized_symbol
    ]
    if len(matches) != 1:
        raise AggregationInputError(
            "official futures symbol metadata is unavailable or ambiguous"
        )
    return dict(matches[0])


def _extend_unique_dict_rows(
    rows: list[dict[str, Any]],
    new_rows: list[Any],
    *,
    identity_keys: tuple[str, ...],
) -> None:
    seen = {
        tuple(str(row.get(key, "")) for key in identity_keys)
        for row in rows
        if isinstance(row, dict)
    }
    for row in new_rows:
        if not isinstance(row, dict):
            continue
        identity = tuple(str(row.get(key, "")) for key in identity_keys)
        if identity in seen:
            continue
        seen.add(identity)
        rows.append(row)


def _build_meta_payload(
    rows: list[dict[str, Any]],
    *,
    partial: bool,
    degraded_reasons: list[str],
) -> Any:
    if not partial and not degraded_reasons:
        return rows
    return {
        "items": rows,
        "_meta": {
            "partial": partial,
            "degraded_reasons": degraded_reasons,
        },
    }


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _pick(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _coerce_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _normalize_account_scope(mapping: dict[str, Any] | None = None) -> str:
    explicit = _pick(mapping or {}, "account_scope", "accountScope")
    return str(explicit) if explicit not in (None, "") else "personal_futures"


def _normalize_margin_type(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def _normalize_position_mode(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().upper()
    if normalized in {"ONE_WAY", "ONEWAY"}:
        return "COMBINED"
    if normalized == "HEDGE":
        return "SEPARATED"
    return normalized or None


def _normalize_balance_entries(rows: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in _payload_items(rows):
        if not isinstance(row, dict):
            continue
        normalized.append(
            {
                "account_scope": _normalize_account_scope(row),
                "asset": str(_pick(row, "asset", "marginAsset") or "USDT").upper(),
                "balance": _to_float(_pick(row, "balance", "walletBalance", "equity")),
                "available_balance": _to_float(_pick(row, "availableBalance", "available", "free")),
                "unrealized_pnl": _to_float(_pick(row, "unrealizePnl", "unrealizedPnl", "unrealizedProfit")),
                "raw": row,
            }
        )
    return normalized


def _account_snapshot_from_balances(balances: list[dict[str, Any]]) -> dict[str, Any]:
    if not balances:
        return {}
    selected = next((item for item in balances if item.get("asset") == "USDT"), balances[0])
    return {
        "account_scope": selected.get("account_scope"),
        "asset": selected.get("asset"),
        "balance": selected.get("balance"),
        "equity": selected.get("balance"),
        "available_balance": selected.get("available_balance"),
        "unrealized_pnl": selected.get("unrealized_pnl"),
        "raw": selected.get("raw"),
    }


def _normalize_positions(rows: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in _payload_items(rows):
        if not isinstance(row, dict):
            continue
        notional = _to_float(_pick(row, "notional", "openValue", "positionValue"))
        position_id = _pick(row, "positionId", "id")
        separated_open_order_id = _pick(row, "separatedOpenOrderId")
        normalized.append(
            {
                "account_scope": _normalize_account_scope(row),
                "position_id": None if position_id in (None, "") else str(position_id),
                "separated_open_order_id": (
                    None
                    if separated_open_order_id in (None, "")
                    else str(separated_open_order_id)
                ),
                "symbol": _normalize_symbol(_pick(row, "symbol")),
                "side": str(_pick(row, "side", "positionSide") or "").upper() or None,
                "position_side": str(_pick(row, "positionSide", "side") or "").upper() or None,
                "quantity": _to_float(_pick(row, "size", "positionAmt", "quantity")),
                "open_value": _to_float(_pick(row, "openValue", "notional")),
                "notional": notional,
                "entry_price": _to_float(_pick(row, "entryPrice", "avgOpenPrice")),
                "mark_price": _to_float(_pick(row, "markPrice", "currentPrice")),
                "unrealized_pnl": _to_float(_pick(row, "unrealizePnl", "unrealizedPnl", "unrealizedProfit")),
                "leverage": _to_float(_pick(row, "leverage")),
                "margin_type": _normalize_margin_type(_pick(row, "marginType")),
                "position_mode": _normalize_position_mode(_pick(row, "separatedMode", "positionMode")),
                "updated_time": _pick(row, "updatedTime", "updateTime"),
                "raw": row,
            }
        )
    return normalized


def _normalize_orders(rows: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in _payload_items(rows):
        if not isinstance(row, dict):
            continue
        actual_order_id = _pick(row, "actualOrderId", "orderId")
        algo_id = _pick(row, "algoId")
        order_id = actual_order_id if str(actual_order_id or "") not in {"", "0"} else algo_id
        order_type = str(_pick(row, "type", "orderType", "planType") or "").lower() or None
        trigger_price = _to_float(_pick(row, "triggerPrice", "tpTriggerPrice", "slTriggerPrice"))
        tp_trigger_price = _to_float(_pick(row, "tpTriggerPrice"))
        sl_trigger_price = _to_float(_pick(row, "slTriggerPrice"))
        if tp_trigger_price is None and order_type and "take_profit" in order_type:
            tp_trigger_price = trigger_price
        if sl_trigger_price is None and order_type and ("stop" in order_type or "stop_loss" in order_type):
            sl_trigger_price = trigger_price
        normalized.append(
            {
                "account_scope": _normalize_account_scope(row),
                "order_id": None if order_id in (None, "") else str(order_id),
                "client_order_id": _pick(row, "clientOrderId", "clientAlgoId", "newClientOrderId"),
                "symbol": _normalize_symbol(_pick(row, "symbol")),
                "side": str(_pick(row, "side") or "").upper() or None,
                "position_side": str(_pick(row, "positionSide") or "").upper() or None,
                "order_type": order_type,
                "status": str(_pick(row, "status", "algoStatus") or "").upper() or None,
                "quantity": _to_float(_pick(row, "origQty", "quantity")),
                "executed_quantity": _to_float(_pick(row, "executedQty", "executedQuantity")),
                "quote_quantity": _to_float(_pick(row, "cumQuote", "quoteQty")),
                "avg_price": _to_float(_pick(row, "avgPrice")),
                "price": _to_float(_pick(row, "price")),
                "trigger_price": trigger_price,
                "tp_trigger_price": tp_trigger_price,
                "sl_trigger_price": sl_trigger_price,
                "reduce_only": _coerce_bool(_pick(row, "reduceOnly")),
                "close_position": _coerce_bool(_pick(row, "closePosition")),
                "margin_type": _normalize_margin_type(_pick(row, "marginType")),
                "position_mode": _normalize_position_mode(_pick(row, "separatedMode", "positionMode")),
                "time": _pick(row, "time", "createTime"),
                "update_time": _pick(row, "updateTime"),
                "raw": row,
            }
        )
    return normalized


def _append_unique(values: list[Any], value: Any) -> None:
    if value not in values:
        values.append(value)


def _normalize_fills(rows: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in _payload_items(rows):
        if not isinstance(row, dict):
            continue
        normalized.append(
            {
                "account_scope": _normalize_account_scope(row),
                "fill_id": None if _pick(row, "id", "tradeId") in (None, "") else str(_pick(row, "id", "tradeId")),
                "order_id": None if _pick(row, "orderId") in (None, "") else str(_pick(row, "orderId")),
                "symbol": _normalize_symbol(_pick(row, "symbol")),
                "side": str(_pick(row, "side") or "").upper() or None,
                "position_side": str(_pick(row, "positionSide") or "").upper() or None,
                "price": _to_float(_pick(row, "price")),
                "quantity": _to_float(_pick(row, "qty", "quantity")),
                "quote_quantity": _to_float(_pick(row, "quoteQty", "cumQuote")),
                "realized_pnl": _to_float(_pick(row, "realizedPnl", "realizePnl")),
                "fee": _to_float(_pick(row, "commission", "fee")),
                "margin_type": _normalize_margin_type(_pick(row, "marginType")),
                "position_mode": _normalize_position_mode(_pick(row, "separatedMode", "positionMode")),
                "time": _pick(row, "time"),
                "raw": row,
            }
        )
    return normalized


def _normalize_bills(rows: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in _payload_items(rows):
        if not isinstance(row, dict):
            continue
        normalized.append(
            {
                "account_scope": _normalize_account_scope(row),
                "bill_id": None if _pick(row, "billId", "id") in (None, "") else str(_pick(row, "billId", "id")),
                "asset": str(_pick(row, "asset") or "USDT").upper(),
                "symbol": _normalize_symbol(_pick(row, "symbol")) if _pick(row, "symbol") else None,
                "income": _to_float(_pick(row, "income", "amount")),
                "type": str(_pick(row, "incomeType", "type") or "").lower() or None,
                "fill_fee": _to_float(_pick(row, "fillFee", "fee")),
                "time": _pick(row, "time"),
                "raw": row,
            }
        )
    return normalized


def _normalize_klines(rows: Any, symbol: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in _payload_items(rows):
        if isinstance(row, (list, tuple)) and len(row) >= 6:
            normalized.append(
                {
                    "symbol": _normalize_symbol(symbol),
                    "open_time": row[0],
                    "open": _to_float(row[1]),
                    "high": _to_float(row[2]),
                    "low": _to_float(row[3]),
                    "close": _to_float(row[4]),
                    "volume": _to_float(row[5]),
                    "close_time": row[6] if len(row) > 6 else None,
                    "raw": row,
                }
            )
        elif isinstance(row, dict):
            normalized.append(
                {
                    "symbol": _normalize_symbol(_pick(row, "symbol") or symbol),
                    "open_time": _pick(row, "openTime", "time"),
                    "open": _to_float(_pick(row, "open")),
                    "high": _to_float(_pick(row, "high")),
                    "low": _to_float(_pick(row, "low")),
                    "close": _to_float(_pick(row, "close")),
                    "volume": _to_float(_pick(row, "volume")),
                    "close_time": _pick(row, "closeTime"),
                    "raw": row,
                }
            )
    return normalized


def _count_closed_trades(orders: list[dict[str, Any]], fills: list[dict[str, Any]], bills: list[dict[str, Any]]) -> int:
    closed_from_bills = sum(1 for bill in bills if "position_close" in str(bill.get("type") or ""))
    if closed_from_bills:
        return closed_from_bills
    closed_from_fills = sum(1 for fill in fills if fill.get("realized_pnl") not in (None, 0))
    if closed_from_fills:
        return closed_from_fills
    return sum(1 for order in orders if str(order.get("status") or "").upper() == "FILLED")


class TradeDataAggregator:
    def __init__(self, fetcher: WeexApiFetcher | None = None) -> None:
        self.fetcher = fetcher or WeexApiFetcher()

    def _base_payload(
        self,
        *,
        profile_name: str,
        market: str,
        trading_mode: str,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        normalized_market = _validate_market(market)
        mode = _validate_trading_mode_market(trading_mode, normalized_market)
        environment = _environment_for_trading_mode(mode, normalized_market)
        return {
            "schema": "weex.ai_wars.contract_payload.v1",
            "profile": profile_name,
            "market": normalized_market,
            "trading_mode": mode,
            "environment": environment,
            "symbol": _normalize_symbol(symbol) if symbol else None,
            "generated_at": _now_ms(),
            "partial": False,
            "constraints": [],
            "degraded_reasons": [],
        }

    def collect_account_risk_payload(
        self,
        *,
        profile_name: str,
        market: str = "futures",
        trading_mode: str = DEFAULT_TRADING_MODE,
        symbol: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        payload = self._base_payload(
            profile_name=profile_name,
            market=market,
            trading_mode=trading_mode,
            symbol=symbol,
        )
        balance_payload = self.fetcher.fetch_futures_balance(profile_name=profile_name, trading_mode=trading_mode)
        position_payload = self.fetcher.fetch_futures_positions(
            profile_name=profile_name,
            symbol=symbol,
            trading_mode=trading_mode,
        )
        open_order_payload = self.fetcher.fetch_futures_open_orders(
            profile_name=profile_name,
            symbol=symbol,
            trading_mode=trading_mode,
        )
        pending_order_payload = self.fetcher.fetch_futures_pending_orders(
            profile_name=profile_name,
            symbol=symbol,
            trading_mode=trading_mode,
        )
        now_ms = _now_ms()
        recent_order_payload: Any = []
        try:
            recent_order_payload = self.fetcher.fetch_futures_orders(
                profile_name=profile_name,
                start_ms=max(0, now_ms - RECENT_ORDER_LOOKBACK_MS),
                end_ms=now_ms,
                symbol=symbol,
                trading_mode=trading_mode,
            )
        except Exception as exc:
            payload["partial"] = True
            _append_unique(payload["degraded_reasons"], RECENT_ORDER_HISTORY_UNAVAILABLE)
            payload["constraints"].append(
                {
                    "code": RECENT_ORDER_HISTORY_UNAVAILABLE,
                    "message": f"Recent order history could not be collected: {exc}",
                }
            )
        balances = _normalize_balance_entries(balance_payload)
        positions = _normalize_positions(position_payload)
        open_orders = _normalize_orders(open_order_payload)
        conditional_orders = _normalize_orders(pending_order_payload)
        recent_orders = _normalize_orders(recent_order_payload)
        orders = open_orders + conditional_orders
        payload.update(
            {
                "account_snapshot": _account_snapshot_from_balances(balances),
                "balances": balances,
                "positions": positions,
                "open_orders": open_orders,
                "conditional_orders": conditional_orders,
                "recent_orders": recent_orders,
                "orders": orders,
                "fills": [],
                "bills": [],
                "raw": {
                    "balance": balance_payload,
                    "positions": position_payload,
                    "open_orders": open_order_payload,
                    "pending_orders": pending_order_payload,
                    "recent_order_history": recent_order_payload,
                },
            }
        )
        return payload

    def collect_order_risk_payload(
        self,
        *,
        profile_name: str,
        market: str = "futures",
        trading_mode: str = DEFAULT_TRADING_MODE,
        raw_order: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        normalized_market = _validate_market(market)
        symbol = (raw_order or {}).get("symbol") or kwargs.get("symbol")
        symbol = _normalize_symbol(symbol) if symbol else None
        payload = self.collect_account_risk_payload(
            profile_name=profile_name,
            market=normalized_market,
            trading_mode=trading_mode,
            symbol=symbol,
        )
        raw_order_dict = dict(raw_order or {})
        normalized_raw_order = dict(raw_order_dict)
        quantity_semantics: dict[str, Any] | None = None
        raw_quantity_unit = _pick(raw_order_dict, "quantity_unit", "quantityUnit")
        normalized_quantity_unit = (
            str(raw_quantity_unit).strip().upper()
            if raw_quantity_unit not in (None, "")
            else BASE_ASSET
        )
        if normalized_quantity_unit == CONTRACTS:
            if not symbol:
                raise AggregationInputError(
                    "CONTRACT_VALUE_REQUIRED: futures contract quantity requires a symbol"
                )
            try:
                symbol_payload = self.fetcher.fetch_futures_symbol_facts(
                    profile_name=profile_name,
                    symbol=symbol,
                )
                symbol_facts = _find_symbol_facts(symbol_payload, symbol)
                normalized_raw_order, quantity_semantics = normalize_order_for_api(
                    market="FUTURES",
                    order=raw_order_dict,
                    symbol_facts=symbol_facts,
                )
            except QuantitySemanticsError as exc:
                raise AggregationInputError(f"{exc.code}: {exc}") from exc
            except Exception as exc:
                raise AggregationInputError(
                    f"CONTRACT_VALUE_REQUIRED: official futures contract metadata is unavailable: {exc}"
                ) from exc
        else:
            try:
                normalized_raw_order, quantity_semantics = normalize_order_for_api(
                    market="FUTURES",
                    order=raw_order_dict,
                )
            except QuantitySemanticsError as exc:
                raise AggregationInputError(f"{exc.code}: {exc}") from exc
        order_preview = dict(normalized_raw_order)
        if "symbol" in order_preview:
            order_preview["symbol"] = _normalize_symbol(order_preview["symbol"])
        order_preview.setdefault("market", normalized_market)
        order_preview.setdefault("trading_mode", trading_mode)
        if "positionSide" in order_preview and "position_side" not in order_preview:
            order_preview["position_side"] = order_preview["positionSide"]
        if "type" in order_preview and "order_type" not in order_preview:
            order_preview["order_type"] = order_preview["type"]
        order_preview["quantity_unit"] = (
            quantity_semantics["api_quantity_unit"] if quantity_semantics else BASE_ASSET
        )
        payload["order_preview"] = order_preview
        payload["normalized_order"] = normalized_raw_order
        payload["quantity_semantics"] = quantity_semantics
        return payload

    def collect_replay_payload(
        self,
        *,
        profile_name: str,
        market: str = "futures",
        trading_mode: str = DEFAULT_TRADING_MODE,
        symbol: str | None = None,
        period: str = "30d",
        confirm_live: bool = False,
        **_: Any,
    ) -> dict[str, Any]:
        if not confirm_live:
            raise AggregationInputError(
                "collect-replay and collect-profile use a read-only POST for contract bills and require --confirm-live"
            )
        normalized_period = _validate_replay_period(period)
        payload = self._base_payload(
            profile_name=profile_name,
            market=market,
            trading_mode=trading_mode,
            symbol=symbol,
        )
        end_ms = _now_ms()
        start_ms = end_ms - (_period_to_days(normalized_period) * DAY_MS)
        balance_payload = self.fetcher.fetch_futures_balance(profile_name=profile_name, trading_mode=trading_mode)
        position_payload = self.fetcher.fetch_futures_positions(
            profile_name=profile_name,
            symbol=symbol,
            trading_mode=trading_mode,
        )
        order_payload = self.fetcher.fetch_futures_orders(
            profile_name=profile_name,
            start_ms=start_ms,
            end_ms=end_ms,
            symbol=symbol,
            trading_mode=trading_mode,
        )
        pending_payload = self.fetcher.fetch_futures_historical_pending_orders(
            profile_name=profile_name,
            start_ms=start_ms,
            end_ms=end_ms,
            symbol=symbol,
            trading_mode=trading_mode,
        )
        fill_payload = self.fetcher.fetch_futures_fills(
            profile_name=profile_name,
            start_ms=start_ms,
            end_ms=end_ms,
            symbol=symbol,
            trading_mode=trading_mode,
        )
        bill_payload = self.fetcher.fetch_futures_bills(
            profile_name=profile_name,
            start_ms=start_ms,
            end_ms=end_ms,
            symbol=symbol,
            trading_mode=trading_mode,
            confirm_live=confirm_live,
        )
        kline_payload = []
        if symbol:
            kline_payload = self.fetcher.fetch_futures_klines(
                profile_name=profile_name,
                symbol=symbol,
                start_ms=start_ms,
                end_ms=end_ms,
                trading_mode=trading_mode,
            )

        balances = _normalize_balance_entries(balance_payload)
        positions = _normalize_positions(position_payload)
        orders = _normalize_orders(_payload_items(order_payload) + _payload_items(pending_payload))
        fills = _normalize_fills(fill_payload)
        bills = _normalize_bills(bill_payload)
        price_series = _normalize_klines(kline_payload, symbol or "UNKNOWN") if symbol else []
        payload.update(
            {
                "period": normalized_period,
                "balances": balances,
                "positions": positions,
                "orders": orders,
                "fills": fills,
                "bills": bills,
                "price_series": price_series,
                "closed_trade_count": _count_closed_trades(orders, fills, bills),
                "raw": {
                    "balance": balance_payload,
                    "positions": position_payload,
                    "order_history": order_payload,
                    "pending_order_history": pending_payload,
                    "fills": fill_payload,
                    "bills": bill_payload,
                    "klines": kline_payload,
                },
            }
        )
        return payload

    def collect_profile_payload(self, **kwargs: Any) -> dict[str, Any]:
        requested_period = _validate_profile_period(str(kwargs.pop("period", PROFILE_PERIOD_AUTO)))
        if requested_period != PROFILE_PERIOD_AUTO:
            payload = self.collect_replay_payload(period=requested_period, **kwargs)
            payload["selected_period"] = requested_period
            payload["fallback_applied"] = False
            payload["fallback_periods_considered"] = [
                {
                    "period": requested_period,
                    "closed_trade_count": int(payload.get("closed_trade_count") or 0),
                }
            ]
            return payload

        considered: list[dict[str, Any]] = []
        selected_payload: dict[str, Any] | None = None
        for period in PROFILE_PERIODS:
            payload = self.collect_replay_payload(period=period, **kwargs)
            closed_trade_count = int(payload.get("closed_trade_count") or 0)
            considered.append({"period": period, "closed_trade_count": closed_trade_count})
            selected_payload = payload
            if closed_trade_count >= PROFILE_MIN_CLOSED_TRADES:
                break

        if selected_payload is None:  # pragma: no cover
            raise AggregationInputError("No profile collection periods are configured.")

        selected_period = str(selected_payload.get("period") or PROFILE_PERIODS[-1])
        selected_payload["selected_period"] = selected_period
        selected_payload["fallback_applied"] = selected_period != PROFILE_PERIODS[0]
        selected_payload["fallback_periods_considered"] = considered
        selected_payload["minimum_closed_trade_count"] = PROFILE_MIN_CLOSED_TRADES
        return selected_payload


def _output_json(payload: dict[str, Any], *, pretty: bool = False) -> None:
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))
        return
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False))


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True)
    parser.add_argument("--market", choices=("futures",), default="futures")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--pretty", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect WEEX AI Wars real contract trading data",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay = subparsers.add_parser("collect-replay", help="Collect contract replay data")
    _add_common_arguments(replay)
    replay.add_argument("--period", choices=COLLECTION_PERIODS, default="30d")
    replay.add_argument(
        "--confirm-live",
        action="store_true",
        help="Confirm the read-only POST required to collect contract bills",
    )

    profile = subparsers.add_parser("collect-profile", help="Collect contract profile data")
    _add_common_arguments(profile)
    profile.add_argument("--period", choices=(PROFILE_PERIOD_AUTO, *PROFILE_PERIODS), default=PROFILE_PERIOD_AUTO)
    profile.add_argument(
        "--confirm-live",
        action="store_true",
        help="Confirm the read-only POST required to collect contract bills",
    )

    order_risk = subparsers.add_parser("collect-order-risk", help="Collect contract order-risk data")
    _add_common_arguments(order_risk)
    order_risk.add_argument("--order-json", required=True)

    account_risk = subparsers.add_parser("collect-account-risk", help="Collect contract account-risk data")
    _add_common_arguments(account_risk)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    aggregator = TradeDataAggregator()
    try:
        if args.command == "collect-replay":
            payload = aggregator.collect_replay_payload(
                profile_name=args.profile,
                market=args.market,
                trading_mode=DEFAULT_TRADING_MODE,
                symbol=args.symbol,
                period=args.period,
                confirm_live=args.confirm_live,
            )
        elif args.command == "collect-profile":
            payload = aggregator.collect_profile_payload(
                profile_name=args.profile,
                market=args.market,
                trading_mode=DEFAULT_TRADING_MODE,
                symbol=args.symbol,
                period=args.period,
                confirm_live=args.confirm_live,
            )
        elif args.command == "collect-order-risk":
            payload = aggregator.collect_order_risk_payload(
                profile_name=args.profile,
                market=args.market,
                trading_mode=DEFAULT_TRADING_MODE,
                raw_order=json.loads(args.order_json),
            )
        elif args.command == "collect-account-risk":
            payload = aggregator.collect_account_risk_payload(
                profile_name=args.profile,
                market=args.market,
                trading_mode=DEFAULT_TRADING_MODE,
                symbol=args.symbol,
            )
        else:  # pragma: no cover
            raise AggregationInputError(f"Unsupported command: {args.command}")
    except (AggregationInputError, json.JSONDecodeError) as exc:
        raise SystemExit(2) from exc

    _output_json(payload, pretty=args.pretty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
