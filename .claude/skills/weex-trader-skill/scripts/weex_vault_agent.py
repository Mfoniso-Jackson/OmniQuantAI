#!/usr/bin/env python3
"""Local in-memory session agent for WEEX manual_once vault mode."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from typing import Any, Dict

import weex_profile_store as store


def _safe_remove_session_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _read_bootstrap_key() -> str:
    raw = sys.stdin.read()
    if not raw.strip():
        raise SystemExit("vault session bootstrap payload was empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise SystemExit("vault session bootstrap payload must be a JSON object")
    key = payload.get("key")
    if not isinstance(key, str) or not key:
        raise SystemExit("vault session bootstrap payload is missing key")
    return key


def _read_request(conn: socket.socket) -> Dict[str, Any]:
    chunks: list[bytes] = []
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    payload = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request payload must be an object")
    return payload


def _write_response(conn: socket.socket, payload: Dict[str, Any]) -> None:
    conn.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the WEEX vault session agent.")
    parser.add_argument("--session-file", required=True, help="Path to the session descriptor file")
    args = parser.parse_args(argv)

    session_path = Path(args.session_file).expanduser()
    store._ensure_private_dir(session_path.parent)
    key_b64 = _read_bootstrap_key()
    token = secrets.token_urlsafe(32)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((store.VAULT_AGENT_HOST, 0))
    server.listen(8)
    server.settimeout(0.5)

    descriptor = {
        "version": store.VAULT_AGENT_VERSION,
        "host": store.VAULT_AGENT_HOST,
        "port": int(server.getsockname()[1]),
        "token": token,
        "pid": os.getpid(),
    }
    store._atomic_write_text(session_path, json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n", 0o600)

    try:
        while True:
            try:
                conn, _addr = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break

            with conn:
                try:
                    request = _read_request(conn)
                    if request.get("token") != token:
                        _write_response(conn, {"ok": False, "error": "invalid token"})
                        continue

                    action = request.get("action")
                    if action == "ping":
                        _write_response(conn, {"ok": True, "pid": os.getpid()})
                        continue
                    if action == "get_key":
                        _write_response(conn, {"ok": True, "key": key_b64})
                        continue
                    if action == "shutdown":
                        _write_response(conn, {"ok": True})
                        return 0
                    _write_response(conn, {"ok": False, "error": "unsupported action"})
                except Exception as exc:  # pragma: no cover - best-effort agent robustness
                    _write_response(conn, {"ok": False, "error": str(exc)})
    finally:
        try:
            server.close()
        finally:
            _safe_remove_session_file(session_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
