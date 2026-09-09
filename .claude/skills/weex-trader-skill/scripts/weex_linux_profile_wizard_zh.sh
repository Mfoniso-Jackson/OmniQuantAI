#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROFILE_CLI="$SCRIPT_DIR/weex_profiles_zh.py"
VAULT_CLI="$SCRIPT_DIR/weex_vault_zh.py"
MSG_ERROR_PREFIX='错误：'
MSG_REQUIRED_EMPTY='该字段不能为空。'
MSG_YES_NO='请输入 yes/no，或输入 y/n。'
MSG_NOT_LINUX='该脚本仅用于 Linux。'
MSG_PROFILE_CLI_MISSING="找不到 $PROFILE_CLI"
MSG_PYTHON_MISSING='需要 python3 或 python。'
MSG_TITLE='WEEX Linux 账号向导'
MSG_SUBTITLE='可选字段可直接回车，使用内置默认值。'
PROMPT_PROFILE_NAME='1. 账号名：'
PROMPT_DESCRIPTION='2. 用途备注（可留空）：'
PROMPT_CONTRACT_BASE_URL='3. 合约 Base URL（可留空）：'
PROMPT_SET_DEFAULT='4. 是否设为默认账号？ [y/N]: '
MSG_SECRET_NOTICE_1='5. 接下来会提示输入 API Key、Secret Key 和 Passphrase。'
MSG_SECRET_NOTICE_2='   密钥会写入加密账户库（vault）。'
MSG_VAULT_NOTICE='Linux 环境统一使用加密账户库（vault）模式。'
MSG_VAULT_SETUP='当前还没有初始化账户库，先开始创建 vault。'
MSG_VAULT_UNLOCK='当前账户库已锁定，先执行一次解锁。'
MSG_VAULT_MISCONFIGURED='当前账户库配置异常，请先执行 scripts/weex_vault.py status 检查。'

# shellcheck source=/dev/null
. "$SCRIPT_DIR/weex_linux_profile_wizard_common.sh"
