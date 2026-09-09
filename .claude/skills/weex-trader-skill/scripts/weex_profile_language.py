#!/usr/bin/env python3
"""Language helpers for localized WEEX profile setup scripts."""

from __future__ import annotations

import json
import os
from pathlib import Path


CONFIG_HOME_ENV = "WEEX_TRADER_SKILL_HOME"
AGENT_INIT_FILENAME = "agent-init.json"


def normalize_language(value: str | None) -> str:
    raw = (value or "").strip().lower().replace("-", "_")
    if raw.startswith("zh") or raw in {"cn", "zh_cn", "zh_tw", "zh_hk"} or "chinese" in raw:
        return "zh"
    return "en"


def config_dir() -> Path:
    raw = os.getenv(CONFIG_HOME_ENV)
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".weex-trader-skill"


def agent_init_path() -> Path:
    return config_dir() / AGENT_INIT_FILENAME


def load_cached_language() -> str | None:
    path = agent_init_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    language = payload.get("language")
    if not isinstance(language, dict):
        return None
    preferred = language.get("preferred")
    if not isinstance(preferred, str) or not preferred.strip():
        return None
    return normalize_language(preferred)


def resolve_language_with_source(preferred: str | None = None) -> tuple[str, str]:
    if preferred:
        return normalize_language(preferred), "explicit"
    cached = load_cached_language()
    if cached:
        return cached, "cached"
    return "en", "default"


def resolve_language(preferred: str | None = None) -> str:
    return resolve_language_with_source(preferred)[0]
