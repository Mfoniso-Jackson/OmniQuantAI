# Linux Vault

Use this reference for Linux `manual_once` vault setup, risk trade-offs, password handling, and lock/unlock operations.

## Contents

- Command context
- Mode
- Complete vault setup parameter list
- Secret handling rules
- Setup commands
- Runtime operations
- Environment notes
- Metadata behavior

## Command Context

Run the shell commands below from the skill root.

If you stay outside the skill root, replace repo-relative paths such as `scripts/weex_vault_en.py` with the full path to that file inside your checkout.

## Mode

Linux uses `manual_once`.

- `manual_once`: safer default for interactive/manual use. The vault remains locked until the user unlocks it for the current session. This reduces standing exposure, but requires re-unlock after a reboot or session reset.

Recommendations:

- Recommend `manual_once` for human-driven trading, profile management, or ad hoc terminal use.
- If the user wants stricter operational hygiene with `manual_once`, suggest locking again after the sensitive operation completes.
- Explain the security trade-offs clearly: `manual_once` reduces standing exposure, but adds an explicit unlock step after reboot or session reset.

## Complete Vault Setup Parameter List

Do not introduce vault setup as only the minimum combination needed to run setup. Explain the full parameter set, what each item controls, when it is required, and the security or operational trade-off behind it.

- vault mode: `manual_once`
- vault password / passphrase: required. User-chosen secret that encrypts the vault.
- `--password-env`: optional transport for setup, unlock, or password rotation when the secret already lives in an environment variable.
- `--password-file`: optional transport for one-shot non-interactive flows that can safely create and delete a temporary secret file.
- unlock immediately after setup: operational choice for `manual_once`; setup keeps the vault unlocked for the current session unless `--no-unlock` is used.
- `--force`: destructive reset path that overwrites an existing vault configuration.

## Secret Handling Rules

- The vault password must be explicitly chosen and provided by the user for the current setup, unlock, or rotation flow.
- The user must clearly designate which value should be used as the vault password.
- Before any `setup` or `change-password` action that sets a new vault password, the user must confirm that same password a second time.
- `unlock` only needs one passphrase entry because it verifies an existing vault password instead of setting a new one.
- AI must not silently decide, infer, generate, or substitute the vault password.
- Never generate a vault passphrase on the user's behalf.
- AI may autonomously execute vault commands such as `setup`, `unlock`, and `change-password` after the user provides the secret and explicitly asks the agent to proceed.
- The user may provide the secret directly to the agent in chat or via another authorized source. Do not refuse solely because the secret arrived through the current conversation.
- Unless the user explicitly asks for `lock`, do not autonomously execute `weex_vault ... lock`.
- Still avoid placing vault secrets in repo files, shell history, or literal command-line arguments when there is a safer transport available.
- For one-shot non-interactive execution, prefer `--password-file` over interactive PTY prompts.
- Avoid passing vault passwords as literal command-line arguments.

## Setup Commands

The user provides the vault passphrase interactively:

```bash
python3 scripts/weex_vault_zh.py setup --mode manual_once

# For non-Chinese users
python3 scripts/weex_vault_en.py setup --mode manual_once
```

Non-interactive alternative for tools that can create a temporary secret file safely:

```bash
python3 scripts/weex_vault_zh.py setup --mode manual_once --password-file /path/to/temp-secret.txt

# For non-Chinese users
python3 scripts/weex_vault_en.py setup --mode manual_once --password-file /path/to/temp-secret.txt
```

## Runtime Operations

Status:

```bash
python3 scripts/weex_vault_zh.py status --pretty

# For non-Chinese users
python3 scripts/weex_vault_en.py status --pretty
```

Unlock after a reboot or session reset:

```bash
python3 scripts/weex_vault_zh.py unlock --pretty

# For non-Chinese users
python3 scripts/weex_vault_en.py unlock --pretty
```

Non-interactive unlock alternative:

```bash
python3 scripts/weex_vault_zh.py unlock --password-file /path/to/temp-secret.txt --pretty

# For non-Chinese users
python3 scripts/weex_vault_en.py unlock --password-file /path/to/temp-secret.txt --pretty
```

Lock again after the sensitive operation is complete:

```bash
python3 scripts/weex_vault_zh.py lock --pretty

# For non-Chinese users
python3 scripts/weex_vault_en.py lock --pretty
```

Change the vault passphrase without deleting saved profiles:

```bash
python3 scripts/weex_vault_zh.py change-password --current-password-file /path/to/current-secret.txt --new-password-file /path/to/new-secret.txt --pretty

# For non-Chinese users
python3 scripts/weex_vault_en.py change-password --current-password-file /path/to/current-secret.txt --new-password-file /path/to/new-secret.txt --pretty
```

## Environment Notes

- `manual_once` stores its session descriptor under the local WEEX config directory such as `~/.weex-trader-skill` or `WEEX_TRADER_SKILL_HOME`; it does not depend on a separate Linux session-runtime directory.
- `--password-env` remains available as a one-shot secret transport for setup, unlock, or password rotation; it is not an auto-unlock mode.

## Metadata Behavior

- When the Linux vault is locked, `list` and `show` still return metadata.
- In that state, `has_credentials: null` with `credentials_status: "unknown_locked"` means the metadata exists but secrets are not currently readable.
