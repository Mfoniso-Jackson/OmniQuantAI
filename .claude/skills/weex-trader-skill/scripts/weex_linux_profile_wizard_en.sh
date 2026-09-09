#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROFILE_CLI="$SCRIPT_DIR/weex_profiles_en.py"
VAULT_CLI="$SCRIPT_DIR/weex_vault_en.py"
MSG_ERROR_PREFIX='Error: '
MSG_REQUIRED_EMPTY='This field cannot be empty.'
MSG_YES_NO='Please answer yes or no.'
MSG_NOT_LINUX='This helper is intended for Linux.'
MSG_PROFILE_CLI_MISSING="Cannot find $PROFILE_CLI"
MSG_PYTHON_MISSING='python3 or python is required.'
MSG_TITLE='WEEX Linux profile wizard'
MSG_SUBTITLE='Leave optional fields empty to use the built-in defaults.'
PROMPT_PROFILE_NAME='1. Profile name: '
PROMPT_DESCRIPTION='2. Description (optional): '
PROMPT_CONTRACT_BASE_URL='3. Contract Base URL (optional): '
PROMPT_SET_DEFAULT='4. Set this profile as default? [y/N]: '
MSG_SECRET_NOTICE_1='5. API Key, Secret Key, and Passphrase will be requested next.'
MSG_SECRET_NOTICE_2='   Secrets will be stored in the encrypted vault.'
MSG_VAULT_NOTICE='Linux uses the encrypted vault workflow for profile secrets.'
MSG_VAULT_SETUP='No vault is configured yet. Starting vault setup first.'
MSG_VAULT_UNLOCK='The vault is currently locked. Unlocking it first.'
MSG_VAULT_MISCONFIGURED='The current vault setup is misconfigured. Run scripts/weex_vault.py status first.'

# shellcheck source=/dev/null
. "$SCRIPT_DIR/weex_linux_profile_wizard_common.sh"
