#!/usr/bin/env python3
"""WEEX Contract REST API helper.

- Endpoint definitions loaded from references/contract-api-definitions.json
- Private auth from a secure saved profile
- Supports generic endpoint calls and deterministic convenience commands
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, parse, request

import weex_ai_api
from weex_agent_state import RuntimePreflightError, ensure_private_runtime_ready, refresh_agent_records
from weex_profile_language import resolve_language
from weex_url_policy import BaseUrlPolicyError, open_weex_request, validate_weex_base_url

ProfileError = RuntimeError
load_profile_credentials = None
resolve_profile = None


DEFAULT_BASE_URL = "https://api-contract.weex.com"
DEFAULT_LOCALE = "en-US"
DEFAULT_TIMEOUT = 15.0
DEFAULT_TRADING_MODE = "live"
TRADING_MODES = ("live",)
GET_BODY_UNSUPPORTED_MESSAGE = (
    "GET requests do not accept --body. Pass request fields with --query instead."
)
PRIVATE_PROFILE_REQUIRED_MESSAGE = (
    "Private commands require a saved profile. Configure a default profile with "
    "scripts/weex_profile_manager.py or scripts/weex_profiles.py, or pass --profile <name>."
)
PROFILE_RUNTIME_DEPENDENCY_MISSING = (
    "Unable to enable saved-profile support for the WEEX Contract REST API helper "
    "because Python dependency '{module_name}' is missing. Run scripts/weex_runtime_setup.py --pretty "
    "or install requirements.lock with --require-hashes using this interpreter and retry."
)
PROFILE_RUNTIME_UNAVAILABLE = (
    "Unable to enable saved-profile support for the WEEX Contract REST API helper "
    "because its runtime dependencies are unavailable."
)


@dataclass(frozen=True)
class Endpoint:
    key: str
    group: str
    title: str
    method: str
    path: str
    auth: bool
    mutating: bool
    doc_url: str
    permission: str = ""


def load_endpoint_map() -> Dict[str, Endpoint]:
    refs = Path(__file__).resolve().parent.parent / "references" / "contract-api-definitions.json"
    obj = json.loads(refs.read_text(encoding="utf-8"))
    endpoint_map: Dict[str, Endpoint] = {}
    for d in obj.get("definitions", []):
        method = d.get("method", "GET").upper()
        auth = bool(d.get("requires_auth", False))
        ep = Endpoint(
            key=d["key"],
            group=d.get("category", ""),
            title=d.get("title", ""),
            method=method,
            path=d.get("path", ""),
            auth=auth,
            mutating=auth and method in {"POST", "PUT", "DELETE"},
            doc_url=d.get("doc_url", ""),
            permission=d.get("permission", ""),
        )
        endpoint_map[ep.key] = ep
    return endpoint_map


ENDPOINTS = load_endpoint_map()
AUTO_AI_LOG_ENDPOINTS = {
    "transaction.place_order",
    "transaction.close_positions",
    "transaction.place_pending_order",
    "transaction.place_tp_sl_order",
}
EXIT_CODE_AI_LOG_FAILED = 2
CLIENT_ORDER_ID_PATTERN = re.compile(r"^[\.A-Z:/a-z0-9_-]{1,36}$")
VALID_SIDES = {"BUY", "SELL"}
VALID_POSITION_SIDES = {"LONG", "SHORT"}
VALID_ORDER_TYPES = {"LIMIT", "MARKET"}
VALID_TIME_IN_FORCE = {"GTC", "IOC", "FOK"}
VALID_WORKING_TYPES = {"CONTRACT_PRICE", "MARK_PRICE"}
VALID_PENDING_ORDER_TYPES = {"STOP", "TAKE_PROFIT", "STOP_MARKET", "TAKE_PROFIT_MARKET"}
VALID_PLAN_TYPES = {"TAKE_PROFIT", "STOP_LOSS"}
EMPTY_ERROR_CODES = {"", "0", "00000"}
CLOSE_ACTION_HINTS = ("close", "exit", "flatten")


def _load_profile_runtime_dependencies() -> None:
    global ProfileError, load_profile_credentials, resolve_profile

    if load_profile_credentials is not None and resolve_profile is not None:
        return

    try:
        from weex_profile_store import (
            ProfileError as profile_error_type,
            load_profile_credentials as load_profile_credentials_fn,
            resolve_profile as resolve_profile_fn,
        )
    except ModuleNotFoundError as exc:
        module_name = exc.name or "unknown"
        raise SystemExit(PROFILE_RUNTIME_DEPENDENCY_MISSING.format(module_name=module_name)) from exc
    except ImportError as exc:
        raise SystemExit(PROFILE_RUNTIME_UNAVAILABLE) from exc

    ProfileError = profile_error_type
    load_profile_credentials = load_profile_credentials_fn
    resolve_profile = resolve_profile_fn


def parse_json_arg(raw: str, arg_name: str) -> Dict[str, Any]:
    raw = raw.strip()
    if not raw:
        return {}
    if raw.startswith("@"):
        raise SystemExit(
            f"{arg_name} no longer accepts @file input. Pass a JSON object string directly."
        )
    payload = raw
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for {arg_name}: {exc}") from exc
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise SystemExit(f"{arg_name} must be a JSON object")
    return parsed


def parse_ai_log_context_arg(raw: Optional[str], arg_name: str) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    parsed = weex_ai_api.parse_json_file_value_arg(raw, arg_name)
    if not isinstance(parsed, dict):
        raise SystemExit(f"{arg_name} must be a JSON object")
    return weex_ai_api.validate_ai_log_payload(parsed, arg_name)


def compact_json(value: Optional[Dict[str, Any]]) -> str:
    if not value:
        return ""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


class WeexContractClient:
    def __init__(
        self,
        base_url: str,
        timeout: float,
        locale: str,
        api_key: Optional[str],
        api_secret: Optional[str],
        api_passphrase: Optional[str],
        profile_name: Optional[str] = None,
        user_agent: str = "weex-trader-skill-contract/1.0",
    ) -> None:
        try:
            self.base_url = validate_weex_base_url(base_url, label="contract base URL")
        except BaseUrlPolicyError as exc:
            raise SystemExit(str(exc)) from exc
        self.timeout = timeout
        self.locale = locale
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.profile_name = profile_name
        self.user_agent = user_agent

    def _require_auth(self) -> None:
        _load_profile_runtime_dependencies()
        if self.profile_name and (not self.api_key or not self.api_secret or not self.api_passphrase):
            try:
                creds = load_profile_credentials(self.profile_name)
            except ProfileError as exc:
                raise SystemExit(str(exc)) from exc
            self.api_key = creds.api_key
            self.api_secret = creds.api_secret
            self.api_passphrase = creds.api_passphrase
        missing = []
        if not self.api_key:
            missing.append("API Key")
        if not self.api_secret:
            missing.append("Secret Key")
        if not self.api_passphrase:
            missing.append("Passphrase")
        if missing:
            if self.profile_name:
                raise SystemExit(
                    f"Missing private API credentials in profile '{self.profile_name}'. "
                    "Update the saved profile with scripts/weex_profile_manager.py "
                    "or scripts/weex_profiles.py and retry: "
                    + ", ".join(missing)
                )
            raise SystemExit(PRIVATE_PROFILE_REQUIRED_MESSAGE)

    def _sign(self, timestamp_ms: str, method: str, path: str, query_string: str, body_str: str) -> str:
        # Per WEEX docs, message = timestamp + method + requestPath + (?queryString) + body
        message = f"{timestamp_ms}{method}{path}"
        if query_string:
            message += f"?{query_string}"
        message += body_str
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def prepare_request(
        self,
        endpoint: Endpoint,
        query: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        method = endpoint.method.upper()
        q = query or {}
        b = body or {}
        if method == "GET" and b:
            raise SystemExit(GET_BODY_UNSUPPORTED_MESSAGE)
        query_string = parse.urlencode(q, doseq=True)
        body_str = compact_json(b)

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "locale": self.locale,
            "User-Agent": self.user_agent,
        }

        if endpoint.auth:
            self._require_auth()
            timestamp_ms = str(int(time.time() * 1000))
            sign = self._sign(timestamp_ms, method, endpoint.path, query_string, body_str)
            headers.update(
                {
                    "ACCESS-KEY": self.api_key,
                    "ACCESS-PASSPHRASE": self.api_passphrase,
                    "ACCESS-TIMESTAMP": timestamp_ms,
                    "ACCESS-SIGN": sign,
                }
            )

        url = f"{self.base_url}{endpoint.path}"
        if query_string:
            url = f"{url}?{query_string}"

        data = body_str.encode("utf-8") if body_str and method != "GET" else None

        return {
            "method": method,
            "url": url,
            "headers": headers,
            "data": data,
            "query": q,
            "body": b,
        }

    def send(self, prepared: Dict[str, Any]) -> Dict[str, Any]:
        req = request.Request(
            url=prepared["url"],
            method=prepared["method"],
            data=prepared["data"],
            headers=prepared["headers"],
        )
        try:
            with open_weex_request(req, timeout=self.timeout, headers=prepared["headers"]) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"raw": raw}
                return {"ok": True, "status": resp.status, "data": payload}
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw}
            return {
                "ok": False,
                "status": exc.code,
                "error": payload,
            }
        except error.URLError as exc:
            return {
                "ok": False,
                "status": None,
                "error": {"message": str(exc)},
            }


def sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
    result = dict(headers)
    if "ACCESS-KEY" in result:
        result["ACCESS-KEY"] = "***"
    if "ACCESS-PASSPHRASE" in result:
        result["ACCESS-PASSPHRASE"] = "***"
    if "ACCESS-SIGN" in result:
        result["ACCESS-SIGN"] = "***"
    return result


def output_json(payload: Dict[str, Any], pretty: bool) -> None:
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_lookup_key(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def lookup_payload_value(payload: Dict[str, Any], *aliases: str) -> Any:
    lookup = {
        normalize_lookup_key(str(key)): value
        for key, value in payload.items()
        if isinstance(key, str)
    }
    for alias in aliases:
        alias_key = normalize_lookup_key(alias)
        if alias_key in lookup:
            return lookup[alias_key]
    return None


def normalize_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


def require_text_field(value: Any, field_name: str) -> str:
    text = normalize_text(value)
    if not text:
        raise SystemExit(f"{field_name} must be a non-empty string")
    return text


def require_choice_field(value: Any, field_name: str, allowed: set[str]) -> str:
    text = require_text_field(value, field_name).upper()
    if text not in allowed:
        raise SystemExit(f"{field_name} must be one of: {', '.join(sorted(allowed))}")
    return text


def require_decimal_field(value: Any, field_name: str, allow_zero: bool = False) -> str:
    text = require_text_field(value, field_name)
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise SystemExit(f"{field_name} must be a valid number") from exc
    if allow_zero:
        if number < 0:
            raise SystemExit(f"{field_name} must be greater than or equal to 0")
    elif number <= 0:
        raise SystemExit(f"{field_name} must be greater than 0")
    return text


def validate_client_identifier(value: Any, field_name: str) -> str:
    text = require_text_field(value, field_name)
    if not CLIENT_ORDER_ID_PATTERN.fullmatch(text):
        raise SystemExit(
            f"{field_name} must match ^[\\.A-Z:/a-z0-9_-]{{1,36}}$ and be 1-36 characters long"
        )
    return text


def add_consistency_mismatch(
    mismatches: List[Dict[str, Any]],
    field: str,
    request_value: Any,
    ai_value: Any,
    message: str,
) -> None:
    mismatches.append(
        {
            "field": field,
            "requestValue": request_value,
            "aiOutputValue": ai_value,
            "message": message,
        }
    )


def drop_empty_optional_fields(body: Dict[str, Any], *keys: str) -> None:
    for key in keys:
        if key in body and (body[key] is None or (isinstance(body[key], str) and not body[key].strip())):
            body.pop(key)


def parse_int_like(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def extract_order_id(value: Any) -> Optional[int]:
    if isinstance(value, dict):
        for key in ("orderId", "successOrderId", "actualOrderId"):
            parsed = parse_int_like(value.get(key))
            if parsed is not None:
                return parsed
        for nested in value.values():
            parsed = extract_order_id(nested)
            if parsed is not None:
                return parsed
    if isinstance(value, list):
        for item in value:
            parsed = extract_order_id(item)
            if parsed is not None:
                return parsed
    return None


def unwrap_trade_payload(payload: Any) -> tuple[Any, str, str]:
    if isinstance(payload, dict):
        code = normalize_text(payload.get("code"))
        message = normalize_text(payload.get("msg") or payload.get("message"))
        if "data" in payload:
            return payload.get("data"), code, message
        return payload, code, message
    return payload, "", ""


def build_transport_failure_reason(status: Any, raw_payload: Any) -> str:
    if isinstance(raw_payload, dict):
        message = normalize_text(raw_payload.get("msg") or raw_payload.get("message") or raw_payload.get("raw"))
        if message:
            return message
    return f"HTTP request failed with status {status}"


def normalize_single_trade_result(
    endpoint_key: str,
    business_payload: Any,
    envelope_code: str,
    envelope_message: str,
) -> Dict[str, Any]:
    normalized_result: Dict[str, Any] = {
        "envelopeCode": envelope_code or None,
        "envelopeMessage": envelope_message or None,
        "data": business_payload,
    }
    if envelope_code and envelope_code != "00000":
        return {
            "businessOk": False,
            "normalizedResult": normalized_result,
            "failureReason": f"WEEX {endpoint_key} returned code {envelope_code}: {envelope_message or 'unknown error'}",
            "orderId": extract_order_id(business_payload),
        }
    if not isinstance(business_payload, dict):
        return {
            "businessOk": False,
            "normalizedResult": normalized_result,
            "failureReason": f"WEEX {endpoint_key} returned an unexpected business payload",
            "orderId": extract_order_id(business_payload),
        }

    success = normalize_bool(business_payload.get("success"))
    error_code = normalize_text(business_payload.get("errorCode"))
    error_message = normalize_text(business_payload.get("errorMessage"))
    order_id = extract_order_id(business_payload)
    normalized_result["success"] = success
    normalized_result["errorCode"] = error_code or None
    normalized_result["errorMessage"] = error_message or None
    normalized_result["orderId"] = order_id
    business_ok = success is True and error_code in EMPTY_ERROR_CODES
    failure_reason = None
    if not business_ok:
        failure_reason = (
            error_message
            or (f"WEEX {endpoint_key} returned errorCode {error_code}" if error_code else "")
            or f"WEEX {endpoint_key} did not return success=true"
        )
    return {
        "businessOk": business_ok,
        "normalizedResult": normalized_result,
        "failureReason": failure_reason,
        "orderId": order_id,
    }


def normalize_multi_trade_result(
    endpoint_key: str,
    business_payload: Any,
    envelope_code: str,
    envelope_message: str,
) -> Dict[str, Any]:
    normalized_result: Dict[str, Any] = {
        "envelopeCode": envelope_code or None,
        "envelopeMessage": envelope_message or None,
        "items": [],
    }
    if envelope_code and envelope_code != "00000":
        return {
            "businessOk": False,
            "normalizedResult": normalized_result,
            "failureReason": f"WEEX {endpoint_key} returned code {envelope_code}: {envelope_message or 'unknown error'}",
            "orderId": extract_order_id(business_payload),
        }

    if isinstance(business_payload, dict):
        items = [business_payload]
    elif isinstance(business_payload, list):
        items = business_payload
    else:
        items = []

    if not items:
        normalized_result["items"] = business_payload
        return {
            "businessOk": False,
            "normalizedResult": normalized_result,
            "failureReason": f"WEEX {endpoint_key} returned no business result rows",
            "orderId": extract_order_id(business_payload),
        }

    success_count = 0
    first_failure_reason: Optional[str] = None
    for item in items:
        if not isinstance(item, dict):
            normalized_result["items"].append(item)
            if first_failure_reason is None:
                first_failure_reason = f"WEEX {endpoint_key} returned a non-object row"
            continue

        success = normalize_bool(item.get("success"))
        error_code = normalize_text(item.get("errorCode"))
        error_message = normalize_text(item.get("errorMessage"))
        normalized_item = dict(item)
        normalized_item["success"] = success
        normalized_result["items"].append(normalized_item)
        item_ok = success is True and error_code in EMPTY_ERROR_CODES
        if item_ok:
            success_count += 1
        elif first_failure_reason is None:
            first_failure_reason = (
                error_message
                or (f"WEEX {endpoint_key} returned errorCode {error_code}" if error_code else "")
                or f"WEEX {endpoint_key} did not return success=true for every row"
            )

    business_ok = success_count > 0 and success_count == len(items)
    return {
        "businessOk": business_ok,
        "normalizedResult": normalized_result,
        "failureReason": None if business_ok else first_failure_reason or f"WEEX {endpoint_key} returned partial failure",
        "orderId": extract_order_id(business_payload),
    }


def normalize_trade_result(endpoint_key: str, response: Dict[str, Any]) -> Dict[str, Any]:
    raw_payload = response.get("data") if response.get("ok") else response.get("error")
    normalized: Dict[str, Any] = {
        "httpStatus": response.get("status"),
        "transportOk": bool(response.get("ok")),
        "businessOk": False,
        "response": raw_payload,
        "normalizedResult": None,
        "failureReason": None,
        "orderId": None,
    }
    if not response.get("ok"):
        normalized["failureReason"] = build_transport_failure_reason(response.get("status"), raw_payload)
        return normalized

    business_payload, envelope_code, envelope_message = unwrap_trade_payload(raw_payload)
    if endpoint_key in {"transaction.place_order", "transaction.place_pending_order"}:
        endpoint_result = normalize_single_trade_result(
            endpoint_key, business_payload, envelope_code, envelope_message
        )
    elif endpoint_key in {"transaction.close_positions", "transaction.place_tp_sl_order"}:
        endpoint_result = normalize_multi_trade_result(
            endpoint_key, business_payload, envelope_code, envelope_message
        )
    else:
        business_ok = not envelope_code or envelope_code == "00000"
        endpoint_result = {
            "businessOk": business_ok,
            "normalizedResult": {
                "envelopeCode": envelope_code or None,
                "envelopeMessage": envelope_message or None,
                "data": business_payload,
            },
            "failureReason": (
                None
                if business_ok
                else f"WEEX {endpoint_key} returned code {envelope_code}: {envelope_message or 'unknown error'}"
            ),
            "orderId": extract_order_id(business_payload),
        }
    normalized.update(endpoint_result)
    return normalized


def normalize_trading_mode(raw: str) -> str:
    mode = (raw or "").strip().lower()
    if mode not in TRADING_MODES:
        raise SystemExit(f"invalid_trading_mode: expected one of {', '.join(TRADING_MODES)}")
    return mode


def environment_for_mode(trading_mode: str) -> Dict[str, Any]:
    normalize_trading_mode(trading_mode)
    return {
        "trading_mode": "live",
        "label": "live",
        "market": "futures",
        "uses_real_funds": True,
        "notice": "This operation targets real WEEX futures trading.",
    }


def user_environment_prefix(environment: Dict[str, Any], language: Optional[str] = None) -> str:
    resolved_language = resolve_language(language)
    normalize_trading_mode(str(environment.get("trading_mode") or DEFAULT_TRADING_MODE))
    if resolved_language == "zh":
        return "当前交易环境：真实盘"
    return "Current trading mode: real trading"


def add_environment_context(payload: Dict[str, Any], environment: Dict[str, Any]) -> None:
    payload["environment"] = environment
    payload["user_environment_prefix"] = user_environment_prefix(environment)


def validate_endpoint_trading_mode(endpoint: Endpoint, trading_mode: str) -> str:
    mode = normalize_trading_mode(trading_mode)
    return mode


def validate_confirm_flags(
    endpoint: Endpoint,
    trading_mode: str,
    dry_run: bool,
    confirm_live: bool,
) -> None:
    if not endpoint.mutating or dry_run:
        return
    if not confirm_live:
        raise SystemExit(
            f"confirm_flag_mode_mismatch: live mutating request for {endpoint.key} requires --confirm-live"
        )


def _upper_body_value(body: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = body.get(key)
        if value is not None:
            return str(value).strip().upper()
    return ""


def _is_directional_close_like_order(body: Dict[str, Any]) -> bool:
    side = _upper_body_value(body, "side")
    position_side = _upper_body_value(body, "positionSide", "position_side")
    return (position_side == "LONG" and side == "SELL") or (
        position_side == "SHORT" and side == "BUY"
    )


def validate_pending_order_routing(endpoint: Endpoint, body: Dict[str, Any]) -> None:
    if endpoint.key != "transaction.place_pending_order":
        return
    if _is_directional_close_like_order(body):
        raise SystemExit(
            "pending_close_requires_tp_sl: price-threshold close requests must use "
            "preview-tp-sl/confirm-tp-sl (placeTpSlOrder) because generic "
            "place_pending_order is not guaranteed reduce-only"
        )


def build_auto_ai_log_body(
    endpoint: Endpoint,
    query: Dict[str, Any],
    body: Dict[str, Any],
    primary_trade_result: Optional[Dict[str, Any]],
    ai_log_context: Dict[str, Any],
    dry_run: bool,
) -> Dict[str, Any]:
    if dry_run or primary_trade_result is None:
        order_id = None
    else:
        order_id = primary_trade_result.get("orderId")
    ai_body: Dict[str, Any] = {
        "stage": ai_log_context["stage"],
        "model": ai_log_context["model"],
        "input": ai_log_context["input"],
        "output": ai_log_context["output"],
        "explanation": ai_log_context["explanation"],
    }
    if order_id is not None:
        ai_body["orderId"] = order_id
    return ai_body


def build_missing_ai_log_preview(endpoint: Endpoint) -> Dict[str, Any]:
    return {
        "enabled": True,
        "required": True,
        "configured": False,
        "triggeredBy": endpoint.key,
        "error": {
            "message": (
                "Real AI log context is required for this endpoint. "
                "Provide --ai-log as @file.json containing stage, model, input, output, explanation. "
                "input must contain the full original prompt, raw source materials, and context payload. "
                "output must contain the concrete AI action parameters. model must be the exact "
                "provider-returned raw model identifier."
            )
        },
    }


def build_ai_log_retry_warning(endpoint_key: str, ai_log_result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tradeExecuted": True,
        "aiLogUploadFailed": True,
        "retryTradeSafe": False,
        "nextAction": (
            "Inspect aiLog failure details before any retry. The trade request already succeeded, "
            "so blindly retrying the trade may duplicate execution."
        ),
        "failedAiLogTrigger": endpoint_key,
        "aiLogFailureReason": ai_log_result.get("failureReason")
        or ai_log_result.get("error", {}).get("message")
        or "Automatic AI log upload failed after a successful trade.",
    }


def maybe_execute_auto_ai_log(
    client: WeexContractClient,
    endpoint: Endpoint,
    query: Dict[str, Any],
    body: Dict[str, Any],
    primary_trade_result: Optional[Dict[str, Any]],
    ai_log_context: Optional[Dict[str, Any]],
    dry_run: bool,
) -> Optional[Dict[str, Any]]:
    if endpoint.key not in AUTO_AI_LOG_ENDPOINTS:
        return None
    if ai_log_context is None:
        if dry_run:
            return build_missing_ai_log_preview(endpoint)
        raise SystemExit(
            "Real AI log context is required for this endpoint. "
            "Provide --ai-log as @file.json containing stage, model, input, output, explanation. "
            "input must contain the full original prompt, raw source materials, and context payload. "
            "output must contain the concrete AI action parameters. model must be the exact "
            "provider-returned raw model identifier."
        )

    try:
        if not dry_run and primary_trade_result is not None and not primary_trade_result.get("businessOk"):
            return {
                "enabled": True,
                "attempted": False,
                "skipped": True,
                "triggeredBy": endpoint.key,
                "reason": (
                    "Automatic AI log upload only runs after a business-successful trade response. "
                    "Primary trade failed, so no AI log was sent."
                ),
                "primaryTrade": {
                    "transportOk": primary_trade_result.get("transportOk"),
                    "businessOk": primary_trade_result.get("businessOk"),
                    "failureReason": primary_trade_result.get("failureReason"),
                },
            }

        ai_body = build_auto_ai_log_body(endpoint, query, body, primary_trade_result, ai_log_context, dry_run)
        ai_endpoint_key = weex_ai_api.find_endpoint_key_by_doc_suffix("UploadAiLog")
        ai_endpoint = weex_ai_api.ENDPOINTS[ai_endpoint_key]
        ai_client = weex_ai_api.WeexAiClient(
            base_url=os.getenv("WEEX_AI_API_BASE", os.getenv("WEEX_API_BASE", client.base_url)),
            timeout=client.timeout,
            locale=client.locale,
            api_key=client.api_key,
            api_secret=client.api_secret,
            api_passphrase=client.api_passphrase,
            user_agent="weex-trader-skill-ai-auto/1.0",
        )
        prepared = ai_client.prepare_request(ai_endpoint, query={}, body=ai_body)
        capture = weex_ai_api.maybe_dump_ai_log_request(
            ai_endpoint.key,
            prepared,
            ai_body,
            extra={
                "triggeredBy": endpoint.key,
                "dryRun": dry_run,
                "primaryTradeOrderId": primary_trade_result.get("orderId") if primary_trade_result else None,
            },
        )

        if dry_run:
            preview = {
                "enabled": True,
                "dry_run": True,
                "triggeredBy": endpoint.key,
                "endpoint": ai_endpoint.key,
                "method": prepared["method"],
                "url": prepared["url"],
                "headers": weex_ai_api.sanitize_headers(prepared["headers"]),
                "body": ai_body,
            }
            if capture is not None:
                preview["capture"] = capture
            return preview

        ai_response = ai_client.send(prepared)
        normalized_ai = weex_ai_api.normalize_ai_endpoint_result(ai_endpoint.key, ai_response)
        result = {
            "enabled": True,
            "attempted": True,
            "triggeredBy": endpoint.key,
            "endpoint": ai_endpoint.key,
            "method": ai_endpoint.method,
            "path": ai_endpoint.path,
            "status": ai_response.get("status"),
            "ok": normalized_ai.get("businessOk"),
            "transportOk": normalized_ai.get("transportOk"),
            "businessOk": normalized_ai.get("businessOk"),
            "failureReason": normalized_ai.get("failureReason"),
            "normalizedResult": normalized_ai.get("normalizedResult"),
            "result": normalized_ai.get("response"),
        }
        if capture is not None:
            result["capture"] = capture
        if "orderId" in ai_body:
            result["orderId"] = ai_body["orderId"]
        return result
    except SystemExit as exc:
        return {
            "enabled": True,
            "attempted": False,
            "triggeredBy": endpoint.key,
            "ok": False,
            "error": {"message": str(exc)},
        }
    except Exception as exc:
        return {
            "enabled": True,
            "attempted": False,
            "triggeredBy": endpoint.key,
            "ok": False,
            "error": {"message": f"{type(exc).__name__}: {exc}"},
        }


def execute_endpoint_payload(
    client: WeexContractClient,
    endpoint_key: str,
    query: Dict[str, Any],
    body: Dict[str, Any],
    dry_run: bool,
    confirm_live: bool,
    trading_mode: str = DEFAULT_TRADING_MODE,
    pretty: bool = False,
    ai_log_context: Optional[Dict[str, Any]] = None,
) -> tuple[int, Dict[str, Any]]:
    endpoint = ENDPOINTS[endpoint_key]
    mode = validate_endpoint_trading_mode(endpoint, trading_mode)
    validate_confirm_flags(endpoint, mode, dry_run, confirm_live)
    body = validate_endpoint_body(endpoint.key, dict(body))
    validate_pending_order_routing(endpoint, body)
    ai_log_consistency = build_ai_log_consistency_report(endpoint.key, body, ai_log_context)

    if endpoint.key in AUTO_AI_LOG_ENDPOINTS and not dry_run and ai_log_context is None:
        raise SystemExit(
            "Real AI log context is required for this endpoint. "
            "Provide --ai-log as @file.json containing stage, model, input, output, explanation. "
            "input must contain the full original prompt, raw source materials, and context payload. "
            "output must contain the concrete AI action parameters. model must be the exact "
            "provider-returned raw model identifier."
        )
    if ai_log_consistency is not None and not ai_log_consistency["ok"]:
        mismatch_summary = "; ".join(item["message"] for item in ai_log_consistency["mismatches"])
        raise SystemExit(f"ai-log.output does not match the trade request: {mismatch_summary}")

    prepared = client.prepare_request(
        endpoint,
        query=query,
        body=body,
    )
    environment = environment_for_mode(mode) if endpoint.auth else None
    if dry_run:
        preview = {
            "dry_run": True,
            "endpoint": endpoint.key,
            "method": prepared["method"],
            "url": prepared["url"],
            "headers": sanitize_headers(prepared["headers"]),
            "query": query,
            "body": body,
        }
        if environment is not None:
            add_environment_context(preview, environment)
        ai_log_preview = maybe_execute_auto_ai_log(
            client=client,
            endpoint=endpoint,
            query=query,
            body=body,
            primary_trade_result=None,
            ai_log_context=ai_log_context,
            dry_run=True,
        )
        if ai_log_preview is not None:
            preview["aiLog"] = ai_log_preview
        if ai_log_consistency is not None:
            preview["aiLogConsistency"] = ai_log_consistency
        return 0, preview

    response = client.send(prepared)
    normalized_trade = normalize_trade_result(endpoint.key, response)
    exit_code = 0 if normalized_trade["businessOk"] else 1
    payload = {
        "endpoint": endpoint.key,
        "method": endpoint.method,
        "path": endpoint.path,
        "status": response.get("status"),
        "ok": response.get("ok"),
        "transportOk": normalized_trade["transportOk"],
        "businessOk": normalized_trade["businessOk"],
        "failureReason": normalized_trade["failureReason"],
        "normalizedResult": normalized_trade["normalizedResult"],
        "result": response.get("data") if response.get("ok") else response.get("error"),
    }
    if environment is not None:
        add_environment_context(payload, environment)
    ai_log_result = maybe_execute_auto_ai_log(
        client=client,
        endpoint=endpoint,
        query=query,
        body=body,
        primary_trade_result=normalized_trade,
        ai_log_context=ai_log_context,
        dry_run=False,
    )
    if ai_log_result is not None:
        payload["aiLog"] = ai_log_result
    if ai_log_consistency is not None:
        payload["aiLogConsistency"] = ai_log_consistency
    if exit_code == 0 and ai_log_result is not None and ai_log_result.get("attempted") and not ai_log_result.get("ok"):
        exit_code = EXIT_CODE_AI_LOG_FAILED
        payload.update(build_ai_log_retry_warning(endpoint.key, ai_log_result))
    payload["exitCode"] = exit_code
    return exit_code, payload


def execute_endpoint(
    client: WeexContractClient,
    endpoint_key: str,
    query: Dict[str, Any],
    body: Dict[str, Any],
    dry_run: bool,
    confirm_live: bool,
    trading_mode: str = DEFAULT_TRADING_MODE,
    pretty: bool = False,
    ai_log_context: Optional[Dict[str, Any]] = None,
) -> int:
    exit_code, payload = execute_endpoint_payload(
        client=client,
        endpoint_key=endpoint_key,
        query=query,
        body=body,
        dry_run=dry_run,
        confirm_live=confirm_live,
        trading_mode=trading_mode,
        pretty=pretty,
        ai_log_context=ai_log_context,
    )
    output_json(payload, pretty)
    return exit_code


def generate_client_oid() -> str:
    return f"codex-{int(time.time() * 1000)}-{secrets.token_hex(3)}"


def find_endpoint_key_by_doc_suffix(doc_suffix: str) -> str:
    target = f"/{doc_suffix}"
    for endpoint in ENDPOINTS.values():
        if endpoint.doc_url.endswith(target):
            return endpoint.key
    raise SystemExit(f"Unable to find endpoint with doc suffix {doc_suffix}")


def normalize_contract_trade_symbol(symbol: str) -> str:
    s = symbol.strip().upper().replace("-", "").replace("/", "").replace(" ", "").replace("_", "")
    if s.startswith("CMT") and s.endswith("USDT"):
        s = s[3:]
    if s.endswith("USDT") and len(s) > 4:
        return s
    raise SystemExit(f"Unsupported symbol format: {symbol}. Expected like ETHUSDT.")


def normalize_contract_symbol(symbol: str) -> str:
    return normalize_contract_trade_symbol(symbol)


def validate_place_order_body(body: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(body)
    drop_empty_optional_fields(
        normalized,
        "price",
        "timeInForce",
        "tpTriggerPrice",
        "slTriggerPrice",
        "TpWorkingType",
        "SlWorkingType",
    )
    normalized["symbol"] = normalize_contract_trade_symbol(require_text_field(normalized.get("symbol"), "symbol"))
    normalized["side"] = require_choice_field(normalized.get("side"), "side", VALID_SIDES)
    normalized["positionSide"] = require_choice_field(
        normalized.get("positionSide"), "positionSide", VALID_POSITION_SIDES
    )
    normalized["type"] = require_choice_field(normalized.get("type"), "type", VALID_ORDER_TYPES)
    normalized["quantity"] = require_decimal_field(normalized.get("quantity"), "quantity")
    normalized["newClientOrderId"] = validate_client_identifier(
        normalized.get("newClientOrderId"), "newClientOrderId"
    )

    if "price" in normalized and normalized["price"] is not None:
        normalized["price"] = require_decimal_field(normalized["price"], "price")
    if "timeInForce" in normalized and normalized["timeInForce"] is not None:
        normalized["timeInForce"] = require_choice_field(
            normalized["timeInForce"], "timeInForce", VALID_TIME_IN_FORCE
        )
    if "tpTriggerPrice" in normalized and normalized["tpTriggerPrice"] is not None:
        normalized["tpTriggerPrice"] = require_decimal_field(normalized["tpTriggerPrice"], "tpTriggerPrice")
    if "slTriggerPrice" in normalized and normalized["slTriggerPrice"] is not None:
        normalized["slTriggerPrice"] = require_decimal_field(normalized["slTriggerPrice"], "slTriggerPrice")
    if "TpWorkingType" in normalized and normalized["TpWorkingType"] is not None:
        normalized["TpWorkingType"] = require_choice_field(
            normalized["TpWorkingType"], "TpWorkingType", VALID_WORKING_TYPES
        )
    if "SlWorkingType" in normalized and normalized["SlWorkingType"] is not None:
        normalized["SlWorkingType"] = require_choice_field(
            normalized["SlWorkingType"], "SlWorkingType", VALID_WORKING_TYPES
        )

    if normalized["type"] == "LIMIT":
        if "price" not in normalized:
            raise SystemExit("price is required when type=LIMIT")
        if "timeInForce" not in normalized:
            raise SystemExit("timeInForce is required when type=LIMIT")
    else:
        if "price" in normalized:
            raise SystemExit("price must be omitted when type=MARKET")
        if "timeInForce" in normalized:
            raise SystemExit("timeInForce must be omitted when type=MARKET")

    return normalized


def validate_close_positions_body(body: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(body)
    if "symbol" in normalized:
        normalized["symbol"] = normalize_contract_trade_symbol(require_text_field(normalized["symbol"], "symbol"))
    return normalized


def validate_place_pending_order_body(body: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(body)
    drop_empty_optional_fields(
        normalized,
        "price",
        "presetTakeProfitPrice",
        "presetStopLossPrice",
        "TpWorkingType",
        "SlWorkingType",
    )
    normalized["symbol"] = normalize_contract_trade_symbol(require_text_field(normalized.get("symbol"), "symbol"))
    normalized["side"] = require_choice_field(normalized.get("side"), "side", VALID_SIDES)
    normalized["positionSide"] = require_choice_field(
        normalized.get("positionSide"), "positionSide", VALID_POSITION_SIDES
    )
    normalized["type"] = require_choice_field(normalized.get("type"), "type", VALID_PENDING_ORDER_TYPES)
    normalized["quantity"] = require_decimal_field(normalized.get("quantity"), "quantity")
    normalized["triggerPrice"] = require_decimal_field(normalized.get("triggerPrice"), "triggerPrice")
    normalized["clientAlgoId"] = validate_client_identifier(normalized.get("clientAlgoId"), "clientAlgoId")

    if "price" in normalized and normalized["price"] is not None:
        normalized["price"] = require_decimal_field(normalized["price"], "price")
    if "presetTakeProfitPrice" in normalized and normalized["presetTakeProfitPrice"] is not None:
        normalized["presetTakeProfitPrice"] = require_decimal_field(
            normalized["presetTakeProfitPrice"], "presetTakeProfitPrice"
        )
    if "presetStopLossPrice" in normalized and normalized["presetStopLossPrice"] is not None:
        normalized["presetStopLossPrice"] = require_decimal_field(
            normalized["presetStopLossPrice"], "presetStopLossPrice"
        )
    if "TpWorkingType" in normalized and normalized["TpWorkingType"] is not None:
        normalized["TpWorkingType"] = require_choice_field(
            normalized["TpWorkingType"], "TpWorkingType", VALID_WORKING_TYPES
        )
    if "SlWorkingType" in normalized and normalized["SlWorkingType"] is not None:
        normalized["SlWorkingType"] = require_choice_field(
            normalized["SlWorkingType"], "SlWorkingType", VALID_WORKING_TYPES
        )

    if normalized["type"] in {"STOP", "TAKE_PROFIT"}:
        if "price" not in normalized:
            raise SystemExit("price is required when type is STOP or TAKE_PROFIT")
    elif "price" in normalized:
        raise SystemExit("price must be omitted when type is STOP_MARKET or TAKE_PROFIT_MARKET")

    return normalized


def validate_place_tp_sl_order_body(body: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(body)
    drop_empty_optional_fields(normalized, "executePrice", "triggerPriceType")
    normalized["symbol"] = normalize_contract_trade_symbol(require_text_field(normalized.get("symbol"), "symbol"))
    normalized["clientAlgoId"] = validate_client_identifier(normalized.get("clientAlgoId"), "clientAlgoId")
    normalized["planType"] = require_choice_field(normalized.get("planType"), "planType", VALID_PLAN_TYPES)
    normalized["triggerPrice"] = require_decimal_field(normalized.get("triggerPrice"), "triggerPrice")
    normalized["quantity"] = require_decimal_field(normalized.get("quantity"), "quantity")
    normalized["positionSide"] = require_choice_field(
        normalized.get("positionSide"), "positionSide", VALID_POSITION_SIDES
    )

    if "executePrice" in normalized and normalized["executePrice"] is not None:
        normalized["executePrice"] = require_decimal_field(
            normalized["executePrice"], "executePrice", allow_zero=True
        )
    if "triggerPriceType" in normalized and normalized["triggerPriceType"] is not None:
        normalized["triggerPriceType"] = require_choice_field(
            normalized["triggerPriceType"], "triggerPriceType", VALID_WORKING_TYPES
        )

    return normalized


def validate_endpoint_body(endpoint_key: str, body: Dict[str, Any]) -> Dict[str, Any]:
    if endpoint_key == "transaction.place_order":
        return validate_place_order_body(body)
    if endpoint_key == "transaction.close_positions":
        return validate_close_positions_body(body)
    if endpoint_key == "transaction.place_pending_order":
        return validate_place_pending_order_body(body)
    if endpoint_key == "transaction.place_tp_sl_order":
        return validate_place_tp_sl_order_body(body)
    return body


def compare_ai_log_string_field(
    mismatches: List[Dict[str, Any]],
    output_payload: Dict[str, Any],
    checked_fields: List[str],
    field: str,
    expected: Any,
    aliases: List[str],
    normalizer,
) -> None:
    actual = lookup_payload_value(output_payload, *aliases)
    checked_fields.append(field)
    if actual is None:
        add_consistency_mismatch(mismatches, field, expected, None, f"ai-log.output.{field} is required")
        return
    try:
        expected_value = normalizer(expected)
    except SystemExit:
        expected_value = normalize_text(expected)
    try:
        actual_value = normalizer(actual)
    except SystemExit:
        add_consistency_mismatch(
            mismatches,
            field,
            expected,
            actual,
            f"ai-log.output.{field} has an invalid value",
        )
        return
    if actual_value != expected_value:
        add_consistency_mismatch(
            mismatches,
            field,
            expected,
            actual,
            f"ai-log.output.{field} must match the request body",
        )


def compare_ai_log_decimal_field(
    mismatches: List[Dict[str, Any]],
    output_payload: Dict[str, Any],
    checked_fields: List[str],
    field: str,
    expected: Any,
    aliases: List[str],
    allow_zero: bool = False,
) -> None:
    actual = lookup_payload_value(output_payload, *aliases)
    checked_fields.append(field)
    if actual is None:
        add_consistency_mismatch(mismatches, field, expected, None, f"ai-log.output.{field} is required")
        return
    try:
        expected_value = Decimal(require_decimal_field(expected, field, allow_zero=allow_zero))
        actual_value = Decimal(require_decimal_field(actual, f"ai-log.output.{field}", allow_zero=allow_zero))
    except SystemExit as exc:
        add_consistency_mismatch(mismatches, field, expected, actual, str(exc))
        return
    if actual_value != expected_value:
        add_consistency_mismatch(
            mismatches,
            field,
            expected,
            actual,
            f"ai-log.output.{field} must numerically match the request body",
        )


def build_ai_log_consistency_report(
    endpoint_key: str,
    body: Dict[str, Any],
    ai_log_context: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if endpoint_key not in AUTO_AI_LOG_ENDPOINTS or ai_log_context is None:
        return None

    output_payload = ai_log_context["output"]
    mismatches: List[Dict[str, Any]] = []
    checked_fields: List[str] = []

    if endpoint_key == "transaction.place_order":
        compare_ai_log_string_field(
            mismatches, output_payload, checked_fields, "symbol", body["symbol"], ["symbol"], normalize_contract_trade_symbol
        )
        compare_ai_log_string_field(
            mismatches, output_payload, checked_fields, "side", body["side"], ["side", "action"], lambda value: require_choice_field(value, "side", VALID_SIDES)
        )
        compare_ai_log_string_field(
            mismatches,
            output_payload,
            checked_fields,
            "positionSide",
            body["positionSide"],
            ["positionSide", "position_side"],
            lambda value: require_choice_field(value, "positionSide", VALID_POSITION_SIDES),
        )
        compare_ai_log_string_field(
            mismatches,
            output_payload,
            checked_fields,
            "type",
            body["type"],
            ["type", "orderType", "order_type"],
            lambda value: require_choice_field(value, "type", VALID_ORDER_TYPES),
        )
        compare_ai_log_decimal_field(
            mismatches, output_payload, checked_fields, "quantity", body["quantity"], ["quantity"]
        )
        if "price" in body:
            compare_ai_log_decimal_field(
                mismatches, output_payload, checked_fields, "price", body["price"], ["price"]
            )

    elif endpoint_key == "transaction.close_positions":
        if "symbol" not in body:
            add_consistency_mismatch(
                mismatches,
                "symbol",
                None,
                None,
                "Automatic AI log upload for close_positions currently requires a concrete symbol",
            )
        else:
            compare_ai_log_string_field(
                mismatches,
                output_payload,
                checked_fields,
                "symbol",
                body["symbol"],
                ["symbol"],
                normalize_contract_trade_symbol,
            )
        checked_fields.append("action")
        action = lookup_payload_value(output_payload, "action", "intent", "operation")
        if action is None:
            add_consistency_mismatch(
                mismatches,
                "action",
                "close",
                None,
                "ai-log.output must declare a close/exit action for close_positions",
            )
        else:
            action_key = normalize_lookup_key(normalize_text(action))
            if not any(hint in action_key for hint in CLOSE_ACTION_HINTS):
                add_consistency_mismatch(
                    mismatches,
                    "action",
                    "close",
                    action,
                    "ai-log.output action must clearly express a close/exit intent",
                )

    elif endpoint_key == "transaction.place_pending_order":
        compare_ai_log_string_field(
            mismatches, output_payload, checked_fields, "symbol", body["symbol"], ["symbol"], normalize_contract_trade_symbol
        )
        compare_ai_log_string_field(
            mismatches, output_payload, checked_fields, "side", body["side"], ["side", "action"], lambda value: require_choice_field(value, "side", VALID_SIDES)
        )
        compare_ai_log_string_field(
            mismatches,
            output_payload,
            checked_fields,
            "positionSide",
            body["positionSide"],
            ["positionSide", "position_side"],
            lambda value: require_choice_field(value, "positionSide", VALID_POSITION_SIDES),
        )
        compare_ai_log_string_field(
            mismatches,
            output_payload,
            checked_fields,
            "type",
            body["type"],
            ["type", "orderType", "order_type"],
            lambda value: require_choice_field(value, "type", VALID_PENDING_ORDER_TYPES),
        )
        compare_ai_log_decimal_field(
            mismatches, output_payload, checked_fields, "quantity", body["quantity"], ["quantity"]
        )
        compare_ai_log_decimal_field(
            mismatches,
            output_payload,
            checked_fields,
            "triggerPrice",
            body["triggerPrice"],
            ["triggerPrice", "trigger_price"],
        )
        if "price" in body:
            compare_ai_log_decimal_field(
                mismatches, output_payload, checked_fields, "price", body["price"], ["price"]
            )

    elif endpoint_key == "transaction.place_tp_sl_order":
        compare_ai_log_string_field(
            mismatches, output_payload, checked_fields, "symbol", body["symbol"], ["symbol"], normalize_contract_trade_symbol
        )
        compare_ai_log_string_field(
            mismatches,
            output_payload,
            checked_fields,
            "planType",
            body["planType"],
            ["planType", "plan_type"],
            lambda value: require_choice_field(value, "planType", VALID_PLAN_TYPES),
        )
        compare_ai_log_string_field(
            mismatches,
            output_payload,
            checked_fields,
            "positionSide",
            body["positionSide"],
            ["positionSide", "position_side"],
            lambda value: require_choice_field(value, "positionSide", VALID_POSITION_SIDES),
        )
        compare_ai_log_decimal_field(
            mismatches, output_payload, checked_fields, "quantity", body["quantity"], ["quantity"]
        )
        compare_ai_log_decimal_field(
            mismatches,
            output_payload,
            checked_fields,
            "triggerPrice",
            body["triggerPrice"],
            ["triggerPrice", "trigger_price"],
        )
        if "executePrice" in body:
            compare_ai_log_decimal_field(
                mismatches,
                output_payload,
                checked_fields,
                "executePrice",
                body["executePrice"],
                ["executePrice", "execute_price"],
                allow_zero=True,
            )

    return {
        "ok": not mismatches,
        "checkedFields": checked_fields,
        "mismatches": mismatches,
    }


def command_requires_auth(args: argparse.Namespace) -> bool:
    if args.command == "call":
        return ENDPOINTS[args.endpoint].auth
    return args.command in {"place-order", "cancel-order"}


def resolve_runtime_profile(
    requested_profile: Optional[str],
    allow_invalid_default: bool,
) -> Optional[Any]:
    try:
        _load_profile_runtime_dependencies()
    except SystemExit:
        if requested_profile is None and allow_invalid_default:
            return None
        raise

    if requested_profile:
        try:
            return resolve_profile(requested_profile)
        except ProfileError as exc:
            raise SystemExit(str(exc)) from exc
    try:
        return resolve_profile(None)
    except ProfileError as exc:
        if allow_invalid_default:
            return None
        raise SystemExit(str(exc)) from exc


def require_private_profile(profile: Optional[Any]) -> None:
    if profile is None:
        raise SystemExit(PRIVATE_PROFILE_REQUIRED_MESSAGE)


def cmd_list_endpoints(args: argparse.Namespace) -> int:
    rows = []
    for endpoint in sorted(ENDPOINTS.values(), key=lambda e: (e.group, e.key)):
        if args.group and endpoint.group != args.group:
            continue
        rows.append(
            {
                "key": endpoint.key,
                "group": endpoint.group,
                "method": endpoint.method,
                "path": endpoint.path,
                "auth": endpoint.auth,
                "mutating": endpoint.mutating,
                "permission": endpoint.permission,
                "doc_url": endpoint.doc_url,
            }
        )
    output_json({"count": len(rows), "endpoints": rows}, args.pretty)
    return 0


def cmd_call(args: argparse.Namespace, client: WeexContractClient) -> int:
    query = parse_json_arg(args.query, "--query")
    body = parse_json_arg(args.body, "--body")
    return execute_endpoint(
        client=client,
        endpoint_key=args.endpoint,
        query=query,
        body=body,
        dry_run=args.dry_run,
        confirm_live=args.confirm_live,
        trading_mode=getattr(args, "trading_mode", DEFAULT_TRADING_MODE),
        pretty=args.pretty,
        ai_log_context=parse_ai_log_context_arg(getattr(args, "ai_log", None), "--ai-log"),
    )


def cmd_place_order(args: argparse.Namespace, client: WeexContractClient) -> int:
    body: Dict[str, Any] = {
        "symbol": normalize_contract_trade_symbol(args.symbol),
        "side": args.side.upper(),
        "positionSide": args.position_side.upper(),
        "type": args.order_type.upper(),
        "quantity": args.quantity,
        "newClientOrderId": args.new_client_order_id or generate_client_oid(),
    }
    if args.price is not None:
        body["price"] = args.price
    if args.time_in_force is not None:
        body["timeInForce"] = args.time_in_force.upper()
    if args.tp_trigger_price is not None:
        body["tpTriggerPrice"] = args.tp_trigger_price
    if args.sl_trigger_price is not None:
        body["slTriggerPrice"] = args.sl_trigger_price
    if args.tp_working_type is not None:
        body["TpWorkingType"] = args.tp_working_type.upper()
    if args.sl_working_type is not None:
        body["SlWorkingType"] = args.sl_working_type.upper()

    if body["type"] == "LIMIT":
        if "price" not in body:
            raise SystemExit("price is required when type=LIMIT")
        if "timeInForce" not in body:
            raise SystemExit("time-in-force is required when type=LIMIT")
    else:
        if "price" in body:
            raise SystemExit("price must be omitted when type=MARKET")
        if "timeInForce" in body:
            raise SystemExit("time-in-force must be omitted when type=MARKET")

    return execute_endpoint(
        client=client,
        endpoint_key=find_endpoint_key_by_doc_suffix("PlaceOrder"),
        query={},
        body=body,
        dry_run=args.dry_run,
        confirm_live=args.confirm_live,
        trading_mode=getattr(args, "trading_mode", DEFAULT_TRADING_MODE),
        pretty=args.pretty,
        ai_log_context=parse_ai_log_context_arg(getattr(args, "ai_log", None), "--ai-log"),
    )


def cmd_cancel_order(args: argparse.Namespace, client: WeexContractClient) -> int:
    query: Dict[str, Any] = {}
    if args.order_id:
        query["orderId"] = args.order_id
    if args.client_oid:
        query["origClientOrderId"] = args.client_oid
    if not query:
        raise SystemExit("Provide at least one of --order-id or --client-oid")

    return execute_endpoint(
        client=client,
        endpoint_key=find_endpoint_key_by_doc_suffix("CancelOrder"),
        query=query,
        body={},
        dry_run=args.dry_run,
        confirm_live=args.confirm_live,
        trading_mode=DEFAULT_TRADING_MODE,
        pretty=args.pretty,
        ai_log_context=None,
    )


def cmd_ticker(args: argparse.Namespace, client: WeexContractClient) -> int:
    return execute_endpoint(
        client=client,
        endpoint_key=find_endpoint_key_by_doc_suffix("GetSymbolPrice"),
        query={"symbol": normalize_contract_symbol(args.symbol)},
        body={},
        dry_run=False,
        confirm_live=False,
        trading_mode=DEFAULT_TRADING_MODE,
        pretty=args.pretty,
        ai_log_context=None,
    )


def cmd_poll_ticker(args: argparse.Namespace, client: WeexContractClient) -> int:
    run_count = 0
    while True:
        run_count += 1
        code = execute_endpoint(
            client=client,
            endpoint_key=find_endpoint_key_by_doc_suffix("GetSymbolPrice"),
            query={"symbol": normalize_contract_symbol(args.symbol)},
            body={},
            dry_run=False,
            confirm_live=False,
            trading_mode=DEFAULT_TRADING_MODE,
            pretty=args.pretty,
            ai_log_context=None,
        )
        if code != 0:
            return code
        if args.count > 0 and run_count >= args.count:
            return 0
        time.sleep(args.interval)


def add_trading_mode_argument(parser: argparse.ArgumentParser) -> None:
    parser.set_defaults(trading_mode=DEFAULT_TRADING_MODE)


def add_confirm_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirm-live", action="store_true", help="Allow live mutating requests")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="WEEX Contract REST API helper",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Saved profile name; omit it to use the configured default profile",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Optional contract API base URL override; leave empty to use the saved profile value or the built-in official default",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="HTTP timeout in seconds; leave empty to use WEEX_API_TIMEOUT or the built-in default",
    )
    parser.add_argument(
        "--dump-ai-log-request-dir",
        default=None,
        help=(
            "Optional directory for dumping the exact outgoing UploadAiLog request body, "
            "including logical object fields and serialized JSON"
        ),
    )
    groups = sorted({endpoint.group for endpoint in ENDPOINTS.values() if endpoint.group})

    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser(
        "list-endpoints",
        help="List all supported contract REST endpoints",
        description="List the contract endpoint definitions bundled with this skill.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p_list.add_argument("--group", choices=groups, default=None, help="Filter endpoints by contract endpoint group")
    p_list.add_argument("--pretty", action="store_true", help="Pretty-print JSON output for easier reading")

    p_call = sub.add_parser(
        "call",
        help="Call an endpoint by key with JSON query/body",
        description="Call a specific contract REST endpoint using raw JSON query and body payloads.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p_call.add_argument("--endpoint", required=True, choices=sorted(ENDPOINTS.keys()), help="Exact endpoint key from list-endpoints")
    p_call.add_argument("--query", default="{}", help="JSON object string")
    p_call.add_argument("--body", default="{}", help="JSON object string")
    p_call.add_argument(
        "--ai-log",
        default=None,
        help=(
            "@file.json with real AI decision log: stage, model, "
            "input (full original prompt, raw source materials, and context payload), "
            "output (concrete AI action parameters), explanation. model must be the exact "
            "provider-returned raw model identifier"
        ),
    )
    p_call.add_argument("--dry-run", action="store_true", help="Preview signed request without sending")
    add_trading_mode_argument(p_call)
    add_confirm_arguments(p_call)
    p_call.add_argument("--pretty", action="store_true", help="Pretty-print JSON output for easier reading")

    p_place = sub.add_parser(
        "place-order",
        help="Convenience wrapper for the live contract PlaceOrder doc",
        description="Place one contract order using the documented V3 fields exposed by this wrapper.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p_place.add_argument("--symbol", required=True, help="Trading pair symbol, for example BTCUSDT or ETHUSDT")
    p_place.add_argument("--side", required=True, choices=["BUY", "SELL", "buy", "sell"], help="Order side: BUY opens/adds long exposure, SELL opens/adds short exposure depending on position side")
    p_place.add_argument("--position-side", required=True, choices=["LONG", "SHORT", "long", "short"], help="Position direction for the contract order")
    p_place.add_argument("--type", dest="order_type", required=True, choices=["LIMIT", "MARKET", "limit", "market"], help="Order type: LIMIT requires a price, MARKET sends immediately at market price")
    p_place.add_argument("--quantity", required=True, help="Order quantity in base-asset units as expected by the WEEX Futures REST API")
    p_place.add_argument("--price", default=None, help="Limit price; usually required for LIMIT orders and omitted for MARKET orders")
    p_place.add_argument("--time-in-force", default=None, choices=["GTC", "IOC", "FOK", "gtc", "ioc", "fok"], help="Execution policy for LIMIT orders: GTC, IOC, or FOK")
    p_place.add_argument("--new-client-order-id", default=None, help="Optional client-defined order identifier; auto-generated when omitted")
    p_place.add_argument("--tp-trigger-price", default=None, help="Optional take-profit trigger price")
    p_place.add_argument("--sl-trigger-price", default=None, help="Optional stop-loss trigger price")
    p_place.add_argument("--tp-working-type", default=None, choices=["CONTRACT_PRICE", "MARK_PRICE", "contract_price", "mark_price"], help="Price source used to evaluate the take-profit trigger")
    p_place.add_argument("--sl-working-type", default=None, choices=["CONTRACT_PRICE", "MARK_PRICE", "contract_price", "mark_price"], help="Price source used to evaluate the stop-loss trigger")
    p_place.add_argument(
        "--ai-log",
        default=None,
        help=(
            "@file.json with real AI decision log: stage, model, "
            "input (full original prompt, raw source materials, and context payload), "
            "output (concrete AI action parameters), explanation. model must be the exact "
            "provider-returned raw model identifier"
        ),
    )
    p_place.add_argument("--dry-run", action="store_true", help="Build and sign the request without sending it")
    add_trading_mode_argument(p_place)
    add_confirm_arguments(p_place)
    p_place.add_argument("--pretty", action="store_true", help="Pretty-print JSON output for easier reading")

    p_cancel = sub.add_parser(
        "cancel-order",
        help="Convenience wrapper for the live contract CancelOrder doc",
        description="Cancel one contract order by WEEX order id or client order id.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p_cancel.add_argument("--order-id", default=None, help="WEEX order id to cancel")
    p_cancel.add_argument("--client-oid", default=None, help="Client order id to cancel when you do not have the WEEX order id")
    p_cancel.add_argument("--dry-run", action="store_true", help="Build and sign the cancel request without sending it")
    p_cancel.add_argument("--confirm-live", action="store_true", help="Allow the live cancel request")
    p_cancel.add_argument("--pretty", action="store_true", help="Pretty-print JSON output for easier reading")

    p_ticker = sub.add_parser(
        "ticker",
        help="Get ticker for one symbol",
        description="Fetch the current contract ticker for a single symbol.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p_ticker.add_argument("--symbol", required=True, help="Trading pair symbol, for example BTCUSDT")
    p_ticker.add_argument("--pretty", action="store_true", help="Pretty-print JSON output for easier reading")

    p_poll = sub.add_parser(
        "poll-ticker",
        help="Continuously poll ticker",
        description="Repeatedly fetch the contract ticker for one symbol at a fixed interval.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p_poll.add_argument("--symbol", required=True, help="Trading pair symbol, for example BTCUSDT")
    p_poll.add_argument("--interval", type=float, default=2.0, help="Seconds to wait between requests")
    p_poll.add_argument("--count", type=int, default=0, help="0 means infinite")
    p_poll.add_argument("--pretty", action="store_true", help="Pretty-print JSON output for easier reading")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "dump_ai_log_request_dir", None):
        os.environ[weex_ai_api.AI_LOG_CAPTURE_ENV_VAR] = args.dump_ai_log_request_dir
    command_name = f"contract.{args.command}"
    try:
        refresh_agent_records(command=command_name)
    except Exception:
        pass

    requires_auth = command_requires_auth(args)
    if requires_auth:
        try:
            ensure_private_runtime_ready(command=command_name, auto_setup=True, language=None)
        except RuntimePreflightError as exc:
            raise SystemExit(str(exc)) from exc
    profile = resolve_runtime_profile(
        requested_profile=args.profile,
        allow_invalid_default=not requires_auth,
    )
    if requires_auth:
        require_private_profile(profile)

    env_base_url = os.getenv("WEEX_CONTRACT_API_BASE") or os.getenv("WEEX_API_BASE")
    base_url = (
        args.base_url
        or (profile.contract_base_url if profile else "")
        or env_base_url
        or DEFAULT_BASE_URL
    )
    locale = os.getenv("WEEX_LOCALE") or DEFAULT_LOCALE
    timeout = args.timeout if args.timeout is not None else float(os.getenv("WEEX_API_TIMEOUT", DEFAULT_TIMEOUT))

    client = WeexContractClient(
        base_url=base_url,
        timeout=timeout,
        locale=locale,
        api_key=None,
        api_secret=None,
        api_passphrase=None,
        profile_name=profile.name if profile else None,
    )

    if args.command == "list-endpoints":
        return cmd_list_endpoints(args)
    if args.command == "call":
        return cmd_call(args, client)
    if args.command == "place-order":
        return cmd_place_order(args, client)
    if args.command == "cancel-order":
        return cmd_cancel_order(args, client)
    if args.command == "ticker":
        return cmd_ticker(args, client)
    if args.command == "poll-ticker":
        return cmd_poll_ticker(args, client)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
