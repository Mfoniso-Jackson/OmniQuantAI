#!/usr/bin/env bash
set -euo pipefail

print_error() {
  printf '%s%s\n' "$MSG_ERROR_PREFIX" "$1" >&2
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

prompt_required() {
  local prompt_text="$1"
  local value=""
  while true; do
    read -r -p "$prompt_text" value
    value="$(trim "$value")"
    if [[ -n "$value" ]]; then
      printf '%s' "$value"
      return 0
    fi
    printf '%s\n' "$MSG_REQUIRED_EMPTY" >&2
  done
}

prompt_optional() {
  local prompt_text="$1"
  local value=""
  read -r -p "$prompt_text" value
  value="$(trim "$value")"
  printf '%s' "$value"
}

prompt_yes_no() {
  local prompt_text="$1"
  local default_answer="$2"
  local value=""
  while true; do
    read -r -p "$prompt_text" value
    value="$(trim "$value")"
    if [[ -z "$value" ]]; then
      value="$default_answer"
    fi
    case "${value,,}" in
      y|yes)
        return 0
        ;;
      n|no)
        return 1
        ;;
    esac
    printf '%s\n' "$MSG_YES_NO" >&2
  done
}

resolve_python() {
  if command -v python3 >/dev/null 2>&1; then
    printf 'python3'
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf 'python'
    return 0
  fi
  return 1
}

require_linux_dependencies() {
  if [[ "$(uname -s)" != "Linux" ]]; then
    print_error "$MSG_NOT_LINUX"
    exit 1
  fi

  if [[ ! -f "$PROFILE_CLI" ]]; then
    print_error "$MSG_PROFILE_CLI_MISSING"
    exit 1
  fi
}

ensure_vault_ready() {
  local python_bin="$1"
  local status_json=""
  local vault_action=""

  if [[ ! -f "$VAULT_CLI" ]]; then
    print_error "Cannot find $VAULT_CLI"
    exit 1
  fi

  printf '%s\n' "$MSG_VAULT_NOTICE"

  status_json="$("$python_bin" "$VAULT_CLI" status)"
  vault_action="$("$python_bin" -c 'import json,sys; print(json.load(sys.stdin).get("action_required",""))' <<<"$status_json")"

  case "$vault_action" in
    setup)
      printf '%s\n' "$MSG_VAULT_SETUP"
      "$python_bin" "$VAULT_CLI" setup --pretty
      ;;
    unlock)
      printf '%s\n' "$MSG_VAULT_UNLOCK"
      "$python_bin" "$VAULT_CLI" unlock --pretty
      ;;
    repair)
      print_error "$MSG_VAULT_MISCONFIGURED"
      exit 1
      ;;
  esac
}

main() {
  local python_bin=""
  local profile_name=""
  local description=""
  local contract_base_url=""
  local set_default="false"
  local save_cmd=()

  require_linux_dependencies

  if ! python_bin="$(resolve_python)"; then
    print_error "$MSG_PYTHON_MISSING"
    exit 1
  fi

  ensure_vault_ready "$python_bin"

  printf '%s\n' "$MSG_TITLE"
  printf '%s\n' "$MSG_SUBTITLE"
  printf '\n'

  profile_name="$(prompt_required "$PROMPT_PROFILE_NAME")"
  description="$(prompt_optional "$PROMPT_DESCRIPTION")"
  contract_base_url="$(prompt_optional "$PROMPT_CONTRACT_BASE_URL")"

  if prompt_yes_no "$PROMPT_SET_DEFAULT" "n"; then
    set_default="true"
  fi

  printf '\n'
  printf '%s\n' "$MSG_SECRET_NOTICE_1"
  printf '%s\n' "$MSG_SECRET_NOTICE_2"
  printf '\n'

  save_cmd=(
    "$python_bin"
    "$PROFILE_CLI"
    save
    --profile
    "$profile_name"
    --prompt-secrets
    --pretty
  )

  if [[ -n "$description" ]]; then
    save_cmd+=(--description "$description")
  fi
  if [[ -n "$contract_base_url" ]]; then
    save_cmd+=(--contract-base-url "$contract_base_url")
  fi
  if [[ "$set_default" == "true" ]]; then
    save_cmd+=(--set-default)
  fi

  exec "${save_cmd[@]}"
}

main "$@"
