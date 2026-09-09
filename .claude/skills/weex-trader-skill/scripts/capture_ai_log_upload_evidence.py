#!/usr/bin/env python3
"""Capture a reproducible UploadAiLog evidence bundle for backend debugging."""

from __future__ import annotations

import argparse
import hashlib
import json
import locale
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import weex_ai_api


DEFAULT_EVIDENCE_ROOT = Path.cwd() / "ai_logs" / "evidence"


def parse_ai_log_arg(raw: str) -> Dict[str, Any]:
    payload = weex_ai_api.parse_json_file_value_arg(raw, "--ai-log")
    if not isinstance(payload, dict):
        raise SystemExit("--ai-log must be provided as @file.json")
    return weex_ai_api.validate_ai_log_payload(payload, "AI log body")


def sanitize_label(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isascii() and ch.isalnum() else "-" for ch in value.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "upload-ai-log"


def analyze_explanation(text: str) -> Dict[str, Any]:
    utf8_bytes = text.encode("utf-8")
    return {
        "charLength": len(text),
        "utf8ByteLength": len(utf8_bytes),
        "nonAsciiCount": sum(1 for ch in text if ord(ch) > 127),
        "questionMarkCount": text.count("?"),
        "containsReplacementChar": "\ufffd" in text,
        "sha256Utf8": hashlib.sha256(utf8_bytes).hexdigest(),
        "preview": text[:160],
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def create_bundle_dir(root: Path, label: str) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    bundle_dir = root / f"{timestamp}-{sanitize_label(label)}-{secrets.token_hex(4)}"
    bundle_dir.mkdir(parents=True, exist_ok=False)
    return bundle_dir


def build_environment_summary(base_url: str, locale_name: str) -> Dict[str, Any]:
    return {
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "defaultEncoding": sys.getdefaultencoding(),
            "filesystemEncoding": sys.getfilesystemencoding(),
            "stdoutEncoding": sys.stdout.encoding,
            "stderrEncoding": sys.stderr.encoding,
            "preferredLocaleEncoding": locale.getpreferredencoding(False),
        },
        "environment": {
            "WEEX_API_BASE": os.getenv("WEEX_API_BASE"),
            "WEEX_AI_API_BASE": os.getenv("WEEX_AI_API_BASE"),
            "WEEX_LOCALE": os.getenv("WEEX_LOCALE"),
            "PYTHONUTF8": os.getenv("PYTHONUTF8"),
            "PYTHONIOENCODING": os.getenv("PYTHONIOENCODING"),
        },
        "requestDefaults": {
            "baseUrl": base_url,
            "locale": locale_name,
        },
    }


def build_request_preview(
    endpoint_key: str,
    prepared: Dict[str, Any],
    body: Dict[str, Any],
    explanation_analysis: Dict[str, Any],
    confirm_live: bool,
    capture: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    serialized_body = ""
    if isinstance(prepared.get("data"), (bytes, bytearray)):
        serialized_body = prepared["data"].decode("utf-8", errors="replace")

    payload: Dict[str, Any] = {
        "endpoint": endpoint_key,
        "method": prepared.get("method"),
        "url": prepared.get("url"),
        "headers": weex_ai_api.sanitize_headers(prepared.get("headers", {})),
        "body": body,
        "serializedBody": serialized_body,
        "explanationAnalysis": explanation_analysis,
        "confirmLive": confirm_live,
    }
    if capture is not None:
        payload["capture"] = capture
    return payload


def capture_request_body(
    endpoint_key: str,
    prepared: Dict[str, Any],
    body: Dict[str, Any],
    bundle_dir: Path,
    confirm_live: bool,
) -> Optional[Dict[str, Any]]:
    capture_dir = bundle_dir / "captures"
    previous = os.getenv(weex_ai_api.AI_LOG_CAPTURE_ENV_VAR)
    os.environ[weex_ai_api.AI_LOG_CAPTURE_ENV_VAR] = str(capture_dir)
    try:
        return weex_ai_api.maybe_dump_ai_log_request(
            endpoint_key,
            prepared,
            body,
            extra={"confirmLive": confirm_live},
        )
    finally:
        if previous is None:
            os.environ.pop(weex_ai_api.AI_LOG_CAPTURE_ENV_VAR, None)
        else:
            os.environ[weex_ai_api.AI_LOG_CAPTURE_ENV_VAR] = previous


def normalize_live_response(endpoint_key: str, response: Dict[str, Any]) -> Dict[str, Any]:
    normalized = weex_ai_api.normalize_ai_endpoint_result(endpoint_key, response)
    return {
        "status": response.get("status"),
        "ok": response.get("ok"),
        "transportOk": normalized["transportOk"],
        "businessOk": normalized["businessOk"],
        "failureReason": normalized["failureReason"],
        "normalizedResult": normalized["normalizedResult"],
        "result": response.get("data") if response.get("ok") else response.get("error"),
        "exitCode": 0 if normalized["businessOk"] else 1,
    }


def write_bundle_readme(bundle_dir: Path, summary: Dict[str, Any]) -> None:
    files = summary["files"]
    lines = [
        "# UploadAiLog Evidence Bundle",
        "",
        "- `source-ai-log.json`: original AI log payload used for UploadAiLog.",
        "- `request-preview.json`: sanitized request preview plus final serialized JSON body.",
        "- `captures/*.json`: exact outgoing request body recorded by the existing helper.",
        "- `environment.json`: Python and locale/encoding context from the client side.",
        "- `response.json`: live response from WEEX when `--confirm-live` was used.",
        "",
        "## Explanation Summary",
        "",
        f"- Characters: {summary['explanationAnalysis']['charLength']}",
        f"- UTF-8 bytes: {summary['explanationAnalysis']['utf8ByteLength']}",
        f"- Non-ASCII chars: {summary['explanationAnalysis']['nonAsciiCount']}",
        f"- Question marks: {summary['explanationAnalysis']['questionMarkCount']}",
        f"- UTF-8 SHA256: `{summary['explanationAnalysis']['sha256Utf8']}`",
        "",
        "## File Paths",
        "",
        f"- Source AI log: `{files['sourceAiLog']}`",
        f"- Request preview: `{files['requestPreview']}`",
        f"- Environment summary: `{files['environment']}`",
    ]
    if "capture" in files:
        lines.append(f"- Request capture: `{files['capture']}`")
    if "response" in files:
        lines.append(f"- Live response: `{files['response']}`")
    write_markdown(bundle_dir / "README.md", lines)


def execute_capture(
    *,
    ai_log_body: Dict[str, Any],
    base_url: str,
    locale_name: str,
    timeout: float,
    evidence_root: Path,
    label: str,
    confirm_live: bool,
) -> Dict[str, Any]:
    endpoint_key = weex_ai_api.find_endpoint_key_by_doc_suffix("UploadAiLog")
    endpoint = weex_ai_api.ENDPOINTS[endpoint_key]
    client = weex_ai_api.WeexAiClient(
        base_url=base_url,
        timeout=timeout,
        locale=locale_name,
        api_key=os.getenv("WEEX_API_KEY"),
        api_secret=os.getenv("WEEX_API_SECRET"),
        api_passphrase=os.getenv("WEEX_API_PASSPHRASE"),
        user_agent="weex-trader-skill-ai-evidence/1.0",
    )
    prepared = client.prepare_request(endpoint, query={}, body=ai_log_body)
    explanation_analysis = analyze_explanation(ai_log_body["explanation"])
    bundle_dir = create_bundle_dir(evidence_root, label)

    source_path = bundle_dir / "source-ai-log.json"
    write_json(source_path, ai_log_body)

    environment_path = bundle_dir / "environment.json"
    write_json(environment_path, build_environment_summary(base_url, locale_name))

    capture = capture_request_body(
        endpoint_key=endpoint_key,
        prepared=prepared,
        body=ai_log_body,
        bundle_dir=bundle_dir,
        confirm_live=confirm_live,
    )
    preview_path = bundle_dir / "request-preview.json"
    write_json(
        preview_path,
        build_request_preview(
            endpoint_key=endpoint_key,
            prepared=prepared,
            body=ai_log_body,
            explanation_analysis=explanation_analysis,
            confirm_live=confirm_live,
            capture=capture,
        ),
    )

    response_path: Optional[Path] = None
    response_payload: Optional[Dict[str, Any]] = None
    if confirm_live:
        response_payload = normalize_live_response(endpoint_key, client.send(prepared))
        response_path = bundle_dir / "response.json"
        write_json(response_path, response_payload)

    summary: Dict[str, Any] = {
        "bundleDir": str(bundle_dir.resolve()),
        "confirmLive": confirm_live,
        "endpoint": endpoint_key,
        "explanationAnalysis": explanation_analysis,
        "files": {
            "sourceAiLog": str(source_path.resolve()),
            "requestPreview": str(preview_path.resolve()),
            "environment": str(environment_path.resolve()),
        },
    }
    if capture and capture.get("path"):
        summary["files"]["capture"] = str(Path(capture["path"]).resolve())
    if response_path is not None:
        summary["files"]["response"] = str(response_path.resolve())
        summary["response"] = response_payload

    write_bundle_readme(bundle_dir, summary)
    summary["files"]["readme"] = str((bundle_dir / "README.md").resolve())
    write_json(bundle_dir / "summary.json", summary)
    summary["files"]["summary"] = str((bundle_dir / "summary.json").resolve())
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture a reproducible UploadAiLog evidence bundle for backend debugging"
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("WEEX_AI_API_BASE", os.getenv("WEEX_API_BASE", weex_ai_api.DEFAULT_BASE_URL)),
    )
    parser.add_argument("--locale", default=os.getenv("WEEX_LOCALE", weex_ai_api.DEFAULT_LOCALE))
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("WEEX_API_TIMEOUT", weex_ai_api.DEFAULT_TIMEOUT)),
    )
    parser.add_argument(
        "--ai-log",
        required=True,
        help="@file.json containing stage, model, input, output, explanation",
    )
    parser.add_argument(
        "--evidence-root",
        default=str(DEFAULT_EVIDENCE_ROOT),
        help="Directory where the evidence bundle directory will be created",
    )
    parser.add_argument(
        "--label",
        default="upload-ai-log",
        help="Short label added to the evidence bundle directory name",
    )
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Actually send UploadAiLog after writing the request evidence bundle",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the final summary JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary = execute_capture(
        ai_log_body=parse_ai_log_arg(args.ai_log),
        base_url=args.base_url,
        locale_name=args.locale,
        timeout=args.timeout,
        evidence_root=Path(args.evidence_root).expanduser(),
        label=args.label,
        confirm_live=args.confirm_live,
    )
    if args.pretty:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False))
    return 0 if not args.confirm_live or summary.get("response", {}).get("exitCode", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
