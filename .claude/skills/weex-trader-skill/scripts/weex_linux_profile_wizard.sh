#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

detect_language() {
  local config_home="${WEEX_TRADER_SKILL_HOME:-$HOME/.weex-trader-skill}"
  local init_path="$config_home/agent-init.json"
  local python_bin=""
  local detected=""
  if [[ ! -f "$init_path" ]]; then
    printf 'en'
    return
  fi

  for python_bin in python3 python; do
    if detected="$("$python_bin" - "$init_path" 2>/dev/null <<'PY'
import json
import sys

try:
    payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
    raw = ((payload.get("language") or {}).get("preferred") or "").strip().lower().replace("-", "_")
except Exception:
    raw = ""

if raw.startswith("zh") or raw in {"cn", "zh_cn", "zh_tw", "zh_hk"} or "chinese" in raw:
    print("zh")
else:
    print("en")
PY
)"; then
      printf '%s' "$detected"
      return
    fi
  done

  printf 'en'
}

TARGET_SCRIPT="$SCRIPT_DIR/weex_linux_profile_wizard_en.sh"
if [[ "$(detect_language)" == "zh" ]]; then
  TARGET_SCRIPT="$SCRIPT_DIR/weex_linux_profile_wizard_zh.sh"
fi

if [[ ! -f "$TARGET_SCRIPT" ]]; then
  printf 'Error: Cannot find %s\n' "$TARGET_SCRIPT" >&2
  exit 1
fi

exec bash "$TARGET_SCRIPT" "$@"
