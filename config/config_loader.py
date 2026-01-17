"""
OmniQuantAI - Config Loader
--------------------------
Loads competition.yaml cleanly and safely.

Usage:
    from config_loader import load_config, cfg_get

    cfg = load_config("competition.yaml")
    symbol = cfg_get(cfg, "weex.symbol")
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import os

import yaml


# ===============================
# Exceptions
# ===============================

class ConfigError(Exception):
    pass


# ===============================
# Core Loader
# ===============================

def load_config(path: str = "competition.yaml") -> Dict[str, Any]:
    """
    Load YAML config file into a dict, validate required structure.
    """
    if not os.path.exists(path):
        raise ConfigError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if not isinstance(cfg, dict):
        raise ConfigError("Config file must parse into a dictionary (YAML object).")

    validate_config(cfg)

    return cfg


# ===============================
# Helpers
# ===============================

def cfg_get(cfg: Dict[str, Any], dotted_key: str, default: Optional[Any] = None) -> Any:
    """
    Get nested config keys using dotted path.

    Example:
        cfg_get(cfg, "weex.symbol")
    """
    parts = dotted_key.split(".")
    current: Any = cfg

    for p in parts:
        if not isinstance(current, dict) or p not in current:
            return default
        current = current[p]

    return current


# ===============================
# Validation
# ===============================

def validate_config(cfg: Dict[str, Any]) -> None:
    """
    Minimal validation that ensures critical config keys exist.
    Add more keys over time as your system grows.
    """

    required_keys = [
        "project.name",
        "project.version",
        "weex.base_url",
        "weex.symbol",
        "weex.leverage",
        "bot.loop_seconds",
        "risk_engine.limits.max_risk_per_trade",
        "risk_engine.limits.max_position_size",
        "risk_engine.limits.max_daily_drawdown",
        "ai_log.enabled",
        "backup.enabled",
        "backup.folder"
    ]

    missing = []
    for k in required_keys:
        if cfg_get(cfg, k) is None:
            missing.append(k)

    if missing:
        raise ConfigError(
            "Missing required config keys:\n"
            + "\n".join([f" - {m}" for m in missing])
        )


# ===============================
# Optional: Pretty Print
# ===============================

def print_config_summary(cfg: Dict[str, Any]) -> None:
    """
    Print minimal readable summary (useful on VPS).
    """
    print("\n✅ OmniQuantAI Config Loaded")
    print("-" * 40)
    print("Project:", cfg_get(cfg, "project.name"), cfg_get(cfg, "project.version"))
    print("Environment:", cfg_get(cfg, "project.environment"))
    print("WEEX Base URL:", cfg_get(cfg, "weex.base_url"))
    print("Symbol:", cfg_get(cfg, "weex.symbol"))
    print("Leverage:", cfg_get(cfg, "weex.leverage"))
    print("Loop seconds:", cfg_get(cfg, "bot.loop_seconds"))
    print("AI Log enabled:", cfg_get(cfg, "ai_log.enabled"))
    print("Backup folder:", cfg_get(cfg, "backup.folder"))
    print("-" * 40)


# ===============================
# CLI Test
# ===============================

if __name__ == "__main__":
    cfg = load_config("competition.yaml")
    print_config_summary(cfg)
