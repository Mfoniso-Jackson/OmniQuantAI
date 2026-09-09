#!/usr/bin/env python3
"""WEEX AI Wars REST API helper.

- Endpoint definitions loaded from references/ai-api-definitions.json
- Private auth from environment variables only
- Supports generic endpoint calls and a deterministic upload-ai-log command
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
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error, parse, request

from weex_url_policy import BaseUrlPolicyError, open_weex_request, validate_weex_base_url


DEFAULT_BASE_URL = "https://api-contract.weex.com"
DEFAULT_LOCALE = "en-US"
DEFAULT_TIMEOUT = 15.0
AI_LOG_CAPTURE_ENV_VAR = "WEEX_AI_LOG_CAPTURE_DIR"


@dataclass(frozen=True)
class Endpoint:
    key: str
    category: str
    title: str
    method: str
    path: str
    requires_auth: bool
    doc_url: str


def load_endpoint_map() -> Dict[str, Endpoint]:
    refs = Path(__file__).resolve().parent.parent / "references" / "ai-api-definitions.json"
    obj = json.loads(refs.read_text(encoding="utf-8"))
    endpoint_map: Dict[str, Endpoint] = {}
    for d in obj.get("definitions", []):
        ep = Endpoint(
            key=d["key"],
            category=d.get("category", ""),
            title=d.get("title", ""),
            method=d.get("method", "GET").upper(),
            path=d.get("path", ""),
            requires_auth=bool(d.get("requires_auth", False)),
            doc_url=d.get("doc_url", ""),
        )
        endpoint_map[ep.key] = ep
    return endpoint_map


ENDPOINTS = load_endpoint_map()
AI_LOG_REQUIRED_FIELDS = ("stage", "model", "input", "output", "explanation")
SUCCESS_CODES = {"0", "00000"}
INVALID_MODEL_IDENTIFIER_MARKERS = {
    "provider-returned-model-id",
    "<provider-returned-model-id>",
    "resolved-model-id",
    "<resolved-model-id>",
    "your-model-id",
    "<your-model-id>",
    "raw-model-id",
    "<raw-model-id>",
    "model-id",
    "<model-id>",
}
GARBLED_QUESTION_RUN_RE = re.compile(r"\?{3,}")


def find_endpoint_key_by_doc_suffix(doc_suffix: str) -> str:
    target = f"/{doc_suffix}"
    for endpoint in ENDPOINTS.values():
        if endpoint.doc_url.endswith(target):
            return endpoint.key
    raise SystemExit(f"Unable to find endpoint with doc suffix {doc_suffix}")


def parse_json_arg(raw: str, arg_name: str) -> Dict[str, Any]:
    if not raw:
        return {}
    payload = raw
    if raw.startswith("@"):
        payload = Path(raw[1:]).read_text(encoding="utf-8-sig")
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for {arg_name}: {exc}") from exc
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise SystemExit(f"{arg_name} must be a JSON object")
    return parsed


def parse_json_value_arg(raw: str, arg_name: str) -> Any:
    payload = raw
    if raw.startswith("@"):
        payload = Path(raw[1:]).read_text(encoding="utf-8-sig")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for {arg_name}: {exc}") from exc


def parse_json_file_value_arg(raw: str, arg_name: str) -> Any:
    if not isinstance(raw, str) or not raw.startswith("@"):
        raise SystemExit(
            f"{arg_name} must be provided as @file.json. "
            "Inline JSON is blocked to avoid PowerShell encoding and quoting corruption."
        )
    return parse_json_value_arg(raw, arg_name)


def compact_json(value: Optional[Dict[str, Any]]) -> str:
    if not value:
        return ""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def json_value_type(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def build_request_capture_payload(
    endpoint_key: str,
    prepared: Dict[str, Any],
    body: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data = prepared.get("data")
    if isinstance(data, (bytes, bytearray)):
        serialized_body = data.decode("utf-8", errors="replace")
    else:
        serialized_body = ""

    payload: Dict[str, Any] = {
        "capturedAtMs": int(time.time() * 1000),
        "endpoint": endpoint_key,
        "method": prepared.get("method"),
        "url": prepared.get("url"),
        "headers": sanitize_headers(prepared.get("headers", {})),
        "bodyFieldTypes": {key: json_value_type(value) for key, value in body.items()},
        "body": body,
        "serializedBody": serialized_body,
    }
    if extra:
        payload["context"] = extra
    return payload


def maybe_dump_ai_log_request(
    endpoint_key: str,
    prepared: Dict[str, Any],
    body: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    raw_dir = os.getenv(AI_LOG_CAPTURE_ENV_VAR, "").strip()
    if not raw_dir:
        return None

    try:
        capture_dir = Path(raw_dir).expanduser()
        capture_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{int(time.time() * 1000)}-{endpoint_key.replace('.', '_')}-{secrets.token_hex(4)}.json"
        file_path = capture_dir / filename
        payload = build_request_capture_payload(endpoint_key, prepared, body, extra=extra)
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "enabled": True,
            "path": str(file_path.resolve()),
            "bodyFieldTypes": payload["bodyFieldTypes"],
        }
    except Exception as exc:
        return {
            "enabled": True,
            "error": {"message": f"{type(exc).__name__}: {exc}"},
        }


class WeexAiClient:
    def __init__(
        self,
        base_url: str,
        timeout: float,
        locale: str,
        api_key: Optional[str],
        api_secret: Optional[str],
        api_passphrase: Optional[str],
        user_agent: str = "weex-trader-skill-ai/1.0",
    ) -> None:
        try:
            self.base_url = validate_weex_base_url(base_url, label="AI API base URL")
        except BaseUrlPolicyError as exc:
            raise SystemExit(str(exc)) from exc
        self.timeout = timeout
        self.locale = locale
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.user_agent = user_agent

    def _require_auth(self) -> None:
        missing = []
        if not self.api_key:
            missing.append("WEEX_API_KEY")
        if not self.api_secret:
            missing.append("WEEX_API_SECRET")
        if not self.api_passphrase:
            missing.append("WEEX_API_PASSPHRASE")
        if missing:
            raise SystemExit(
                "Missing private API credentials in environment. "
                "Set these vars and retry: " + ", ".join(missing)
            )

    def _sign(self, timestamp_ms: str, method: str, path: str, query_string: str, body_str: str) -> str:
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
        query_string = parse.urlencode(q, doseq=True)
        body_str = compact_json(b)

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "locale": self.locale,
            "User-Agent": self.user_agent,
        }

        if endpoint.requires_auth:
            self._require_auth()
            ts = str(int(time.time() * 1000))
            sign = self._sign(ts, method, endpoint.path, query_string, body_str)
            headers.update(
                {
                    "ACCESS-KEY": self.api_key,
                    "ACCESS-PASSPHRASE": self.api_passphrase,
                    "ACCESS-TIMESTAMP": ts,
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
            return {"ok": False, "status": exc.code, "error": payload}
        except error.URLError as exc:
            return {"ok": False, "status": None, "error": {"message": str(exc)}}


def sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
    result = dict(headers)
    for key in ["ACCESS-KEY", "ACCESS-PASSPHRASE", "ACCESS-SIGN"]:
        if key in result:
            result[key] = "***"
    return result


def output_json(payload: Dict[str, Any], pretty: bool) -> None:
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def is_mutating(endpoint: Endpoint) -> bool:
    return endpoint.method in {"POST", "PUT", "DELETE"} and endpoint.requires_auth


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def looks_like_powershell_garbled_explanation(explanation: str) -> bool:
    question_runs = [len(match.group(0)) for match in GARBLED_QUESTION_RUN_RE.finditer(explanation)]
    if not question_runs:
        return False

    question_mark_count = explanation.count("?")
    if question_mark_count < 8:
        return False

    longest_run = max(question_runs)
    if longest_run < 5:
        return False

    non_space_length = len(re.sub(r"\s+", "", explanation))
    if non_space_length == 0:
        return False

    question_ratio = question_mark_count / non_space_length
    if question_ratio < 0.2:
        return False

    ascii_letter_count = sum(1 for ch in explanation if ch.isascii() and ch.isalpha())
    non_ascii_count = sum(1 for ch in explanation if ord(ch) > 127)
    return non_ascii_count == 0 and question_mark_count > ascii_letter_count


def validate_explanation_text(value: Any, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{source}.explanation must be a non-empty detailed string")
    explanation = value.strip()
    if len(explanation) > 1000:
        raise SystemExit(f"{source}.explanation must be 1000 characters or fewer")
    if "\ufffd" in explanation:
        raise SystemExit(
            f"{source}.explanation appears garbled because it contains the Unicode replacement character. "
            "Write the ai-log JSON as UTF-8 and avoid piping non-ASCII Python source through PowerShell."
        )
    if looks_like_powershell_garbled_explanation(explanation):
        raise SystemExit(
            f"{source}.explanation appears garbled because question-mark replacement characters dominate the text. "
            "Write the ai-log JSON as a UTF-8 file and avoid PowerShell here-string pipelines such as @'...'@ | python -."
        )
    return explanation


def validate_model_identifier(value: Any, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(
            f"{source}.model must be a non-empty string using the exact provider-returned "
            "raw model identifier"
        )
    if value != value.strip():
        raise SystemExit(
            f"{source}.model must preserve the exact provider-returned raw model identifier "
            "without added whitespace"
        )
    normalized = value.strip()
    lowered = normalized.lower()
    if lowered in INVALID_MODEL_IDENTIFIER_MARKERS or "provider-returned-model-id" in lowered:
        raise SystemExit(
            f"{source}.model must be the exact provider-returned raw model identifier, "
            f"not a documentation placeholder such as {normalized!r}"
        )
    return normalized


def validate_ai_log_payload(body: Dict[str, Any], source: str) -> Dict[str, Any]:
    missing = [field for field in AI_LOG_REQUIRED_FIELDS if field not in body]
    if missing:
        raise SystemExit(f"{source} is missing required fields: {', '.join(missing)}")
    if not isinstance(body["stage"], str) or not body["stage"].strip():
        raise SystemExit(f"{source}.stage must be a non-empty string")
    body["model"] = validate_model_identifier(body["model"], source)
    if not isinstance(body["input"], dict) or not body["input"]:
        raise SystemExit(
            f"{source}.input must be a non-empty JSON object containing the complete prompt, "
            "raw source materials, and context in the original request format"
        )
    if not isinstance(body["output"], dict):
        raise SystemExit(
            f"{source}.output must be a JSON object describing the concrete action "
            "parameters decided by the AI"
        )
    body["explanation"] = validate_explanation_text(body["explanation"], source)
    return body


def normalize_ai_endpoint_result(endpoint_key: str, response: Dict[str, Any]) -> Dict[str, Any]:
    raw_payload = response.get("data") if response.get("ok") else response.get("error")
    normalized: Dict[str, Any] = {
        "httpStatus": response.get("status"),
        "transportOk": bool(response.get("ok")),
        "businessOk": False,
        "response": raw_payload,
        "normalizedResult": None,
        "failureReason": None,
    }
    if not response.get("ok"):
        message = ""
        if isinstance(raw_payload, dict):
            message = normalize_text(raw_payload.get("msg") or raw_payload.get("message") or raw_payload.get("raw"))
        normalized["failureReason"] = message or f"HTTP request failed with status {response.get('status')}"
        return normalized

    if not isinstance(raw_payload, dict):
        normalized["failureReason"] = "AI API returned a non-JSON-object payload"
        return normalized

    code = normalize_text(raw_payload.get("code"))
    msg = normalize_text(raw_payload.get("msg"))
    data = raw_payload.get("data")
    business_ok = code in SUCCESS_CODES
    normalized["businessOk"] = business_ok
    normalized["normalizedResult"] = {
        "code": code,
        "msg": msg,
        "data": data,
    }
    if not business_ok:
        normalized["failureReason"] = (
            f"WEEX AI endpoint {endpoint_key} returned code {code or '<missing>'}: {msg or 'unknown error'}"
        )
    return normalized


def execute_endpoint(
    client: WeexAiClient,
    endpoint_key: str,
    query: Dict[str, Any],
    body: Dict[str, Any],
    dry_run: bool,
    confirm_live: bool,
    pretty: bool,
) -> int:
    endpoint = ENDPOINTS[endpoint_key]
    upload_ai_log_endpoint_key = find_endpoint_key_by_doc_suffix("UploadAiLog")
    if endpoint_key == upload_ai_log_endpoint_key:
        validate_ai_log_payload(body, "AI log body")

    if is_mutating(endpoint) and not confirm_live and not dry_run:
        raise SystemExit(
            f"Refusing live mutating request for {endpoint_key}. "
            "Use --confirm-live to send, or --dry-run to preview."
        )

    prepared = client.prepare_request(endpoint, query=query, body=body)
    capture = None
    if endpoint_key == upload_ai_log_endpoint_key:
        capture = maybe_dump_ai_log_request(
            endpoint_key,
            prepared,
            body,
            extra={"dryRun": dry_run},
        )
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
        if capture is not None:
            preview["capture"] = capture
        output_json(preview, pretty)
        return 0

    resp = client.send(prepared)
    normalized = normalize_ai_endpoint_result(endpoint_key, resp)
    exit_code = 0 if normalized["businessOk"] else 1
    payload = {
        "endpoint": endpoint.key,
        "method": endpoint.method,
        "path": endpoint.path,
        "status": resp.get("status"),
        "ok": resp.get("ok"),
        "transportOk": normalized["transportOk"],
        "businessOk": normalized["businessOk"],
        "failureReason": normalized["failureReason"],
        "normalizedResult": normalized["normalizedResult"],
        "result": resp.get("data") if resp.get("ok") else resp.get("error"),
        "exitCode": exit_code,
    }
    if capture is not None:
        payload["capture"] = capture
    output_json(payload, pretty)
    return exit_code


def cmd_list_endpoints(args: argparse.Namespace) -> int:
    rows = []
    for ep in sorted(ENDPOINTS.values(), key=lambda e: (e.category, e.key)):
        if args.category and ep.category != args.category:
            continue
        rows.append(
            {
                "key": ep.key,
                "category": ep.category,
                "method": ep.method,
                "path": ep.path,
                "requires_auth": ep.requires_auth,
                "doc_url": ep.doc_url,
            }
        )
    output_json({"count": len(rows), "endpoints": rows}, args.pretty)
    return 0


def cmd_call(args: argparse.Namespace, client: WeexAiClient) -> int:
    return execute_endpoint(
        client=client,
        endpoint_key=args.endpoint,
        query=parse_json_arg(args.query, "--query"),
        body=parse_json_arg(args.body, "--body"),
        dry_run=args.dry_run,
        confirm_live=args.confirm_live,
        pretty=args.pretty,
    )


def cmd_upload_ai_log(args: argparse.Namespace, client: WeexAiClient) -> int:
    body: Dict[str, Any] = {
        "stage": args.stage,
        "model": args.model,
        "input": parse_json_value_arg(args.input_payload, "--input"),
        "output": parse_json_value_arg(args.output_payload, "--output"),
        "explanation": args.explanation,
    }
    if args.order_id is not None:
        body["orderId"] = args.order_id
    validate_ai_log_payload(body, "AI log body")

    return execute_endpoint(
        client=client,
        endpoint_key=find_endpoint_key_by_doc_suffix("UploadAiLog"),
        query={},
        body=body,
        dry_run=args.dry_run,
        confirm_live=args.confirm_live,
        pretty=args.pretty,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WEEX AI Wars REST API helper")
    parser.add_argument(
        "--base-url",
        default=os.getenv("WEEX_AI_API_BASE", os.getenv("WEEX_API_BASE", DEFAULT_BASE_URL)),
    )
    parser.add_argument("--locale", default=os.getenv("WEEX_LOCALE", DEFAULT_LOCALE))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("WEEX_API_TIMEOUT", DEFAULT_TIMEOUT)))
    parser.add_argument(
        "--dump-ai-log-request-dir",
        default=os.getenv(AI_LOG_CAPTURE_ENV_VAR),
        help=(
            "Optional directory for dumping the exact outgoing UploadAiLog request body, "
            "including logical object fields and serialized JSON"
        ),
    )
    categories = sorted({endpoint.category for endpoint in ENDPOINTS.values() if endpoint.category})

    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-endpoints", help="List supported AI Wars REST endpoints")
    p_list.add_argument("--category", choices=categories, default=None)
    p_list.add_argument("--pretty", action="store_true")

    p_call = sub.add_parser("call", help="Call an AI Wars endpoint by key with JSON query/body")
    p_call.add_argument("--endpoint", required=True, choices=sorted(ENDPOINTS.keys()))
    p_call.add_argument("--query", default="{}", help="JSON object or @file.json")
    p_call.add_argument("--body", default="{}", help="JSON object or @file.json")
    p_call.add_argument("--dry-run", action="store_true")
    p_call.add_argument("--confirm-live", action="store_true")
    p_call.add_argument("--pretty", action="store_true")

    p_upload = sub.add_parser("upload-ai-log", help="Convenience wrapper for the AI Wars UploadAiLog doc")
    p_upload.add_argument("--order-id", type=int, default=None, help="Optional AI Wars order identifier")
    p_upload.add_argument("--stage", required=True, help="Current AI trading stage")
    p_upload.add_argument(
        "--model",
        required=True,
        help="Exact provider-returned raw model identifier used for the request",
    )
    p_upload.add_argument(
        "--input",
        dest="input_payload",
        required=True,
        help="Non-empty JSON object or @file.json with the full original prompt, raw source materials, and context payload",
    )
    p_upload.add_argument(
        "--output",
        dest="output_payload",
        required=True,
        help="JSON object or @file.json with the concrete AI action parameters",
    )
    p_upload.add_argument(
        "--explanation",
        required=True,
        help="Detailed natural-language explanation up to 1000 chars",
    )
    p_upload.add_argument("--dry-run", action="store_true")
    p_upload.add_argument("--confirm-live", action="store_true")
    p_upload.add_argument("--pretty", action="store_true")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.dump_ai_log_request_dir:
        os.environ[AI_LOG_CAPTURE_ENV_VAR] = args.dump_ai_log_request_dir
    client = WeexAiClient(
        base_url=args.base_url,
        timeout=args.timeout,
        locale=args.locale,
        api_key=os.getenv("WEEX_API_KEY"),
        api_secret=os.getenv("WEEX_API_SECRET"),
        api_passphrase=os.getenv("WEEX_API_PASSPHRASE"),
    )

    if args.command == "list-endpoints":
        return cmd_list_endpoints(args)
    if args.command == "call":
        return cmd_call(args, client)
    if args.command == "upload-ai-log":
        return cmd_upload_ai_log(args, client)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
