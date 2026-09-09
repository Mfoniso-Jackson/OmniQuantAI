# Script Operations

Use this reference only when direct local script execution, dependency setup, or repo maintenance is needed instead of the normal natural-language skill flow.

## Python Prerequisites

Profile, vault, private-trading, and API-definition regeneration commands require the hashed dependencies in [requirements.lock](../requirements.lock).

```bash
# Windows
py -3 -m pip install --require-hashes -r requirements.lock

# macOS / Linux
python3 -m pip install --require-hashes -r requirements.lock
```

Before private contract commands, run `scripts/weex_agent_state.py --command skill.preflight ...` and inspect `runtime.host.requirements_ready`, `runtime.host.missing_modules`, and `runtime.env_validation`. The private REST CLIs now stop immediately when those checks fail instead of waiting until profile or order execution.

One-command runtime setup:

```bash
# Windows
py -3 scripts/weex_runtime_setup.py --pretty

# macOS / Linux
python3 scripts/weex_runtime_setup.py --pretty
```

This helper installs `requirements.lock` with hash verification into the current interpreter, attempts `ensurepip` first if `pip` is missing, refreshes `agent-init.json` / `agent-runtime.json`, and reports whether the interpreter is actually ready for private WEEX CLI flows.

Private contract CLIs also auto-attempt this helper when the current interpreter is missing required Python dependencies. Invalid runtime overrides such as a bad `WEEX_API_TIMEOUT` value still stop immediately because the helper does not modify environment variables for you.

Command launcher policy:

- Windows: use `py -3`
- macOS / Linux: use `python3`
- GUI profile management also needs `tkinter`
- On macOS and Windows tool-managed shells, use `scripts/weex_gui_launcher.py` for detached GUI launch after the managed GUI runtime is ready; the launcher verifies the managed runtime and uses it for the child process

## Managed GUI Runtime

On Windows and macOS, the GUI entrypoints must use an explicitly prepared managed Python runtime even when the current interpreter can initialize Tk and has GUI-side dependencies. They do not download or install that runtime implicitly. If an AI assistant sees `explicit_setup_required`, it should explain the pinned uv/Python setup plus checksum/hash verification, ask whether it should install the runtime, and run the `ensure --accept-managed-runtime --pretty` command only after clear confirmation.

Manual repair commands:

```bash
# Windows users: replace python3 with py -3
python3 scripts/weex_gui_bootstrap.py probe --pretty
python3 scripts/weex_gui_bootstrap.py ensure --accept-managed-runtime --pretty
python3 scripts/weex_doctor.py gui
```

Notes:

- the bootstrap stores a user-local runtime under the WEEX config directory such as `~/.weex-trader-skill/gui-runtime`
- explicit `ensure --accept-managed-runtime` downloads a pinned uv installer, verifies its SHA256, provisions a managed CPython 3.12.13 virtual environment, and installs `requirements.lock` with hash verification
- user-facing AI flows should offer to perform this command after confirmation instead of requiring non-technical users to copy and run it themselves
- the profile and vault GUI entrypoints will automatically re-launch themselves inside that managed runtime when they are started directly from a non-managed interpreter
- this managed bootstrap is for the Windows/macOS GUI flows; terminal/private REST commands still run on the interpreter you launched and therefore still need their own preflight/runtime checks
- the profile and vault GUI entrypoints also auto-detach when they are started from a non-interactive/tool-managed shell on macOS or Windows
- explicit detached launch uses a transient `.app` wrapper on macOS and prefers `pythonw.exe` or another hidden background process on Windows
- detached-launch records and logs are stored under `~/.weex-trader-skill/gui-launchers`; the launcher keeps only recent records and trims each `.log` file to 256 KiB
- `scripts/weex_agent_state.py --command skill.preflight ...` only reports when explicit managed-runtime setup is required; it does not download or install runtime files
- use `WEEX_GUI_RUNTIME_DISABLE=1` only when you explicitly want to suppress the bootstrap path
- use `WEEX_GUI_FORCE_FOREGROUND=1` only when you explicitly want the GUI to stay attached to the current shell, which can reintroduce a Terminal/cmd window

Detached GUI launch examples:

```bash
# Windows users: replace python3 with py -3
python3 scripts/weex_gui_launcher.py profile-manager --language zh --pretty
python3 scripts/weex_gui_launcher.py vault-manager --language zh --requested-action setup --pretty
```

Vault `--requested-action` values:

- `setup`: open the vault UI focused on initialization; if the vault is currently uninitialized, the window immediately starts the passphrase flow
- `unlock`: open the vault UI focused on unlocking; if the vault is currently locked, the window immediately starts the passphrase flow
- `status`: open the vault UI focused on reviewing the current state only; it does not unlock or lock by itself
- `lock`: open the vault UI focused on the lock workflow; it does not lock by itself until the user presses the button in the window

Windows/macOS vault command routing:

- `python3 scripts/weex_vault.py` with no subcommand opens the vault UI
- bare `setup` and bare `unlock` also open the vault UI by default
- `status`, `lock`, `mode`, `change-password`, and any command that includes extra CLI flags stay in the terminal unless you explicitly use `scripts/weex_gui_launcher.py vault-manager ...`
- use `--cli` when you explicitly want the terminal flow for `setup` or `unlock` on Windows/macOS

## Command Context

Run the shell commands below from the skill root.

If you stay outside the skill root, prefix repo-relative paths with the full skill path. For example:

```text
py -3 E:\path\to\weex-trader-skill\scripts\weex_contract_api.py --help
python3 /path/to/weex-trader-skill/scripts/weex_contract_api.py --help
```

The examples below are written as single-line commands so they can be pasted into PowerShell, bash, or zsh without changing the line continuation style.

## Quick Start

Public contract market data works without any API credentials:

```bash
# Windows users: replace python3 with py -3
python3 scripts/weex_contract_api.py ticker --symbol BTCUSDT --pretty
```

List bundled contract endpoints:

```bash
# Windows users: replace python3 with py -3
python3 scripts/weex_contract_api.py list-endpoints --pretty
```

## Trading Commands

Representative real contract order:

```bash
# Windows users: replace python3 with py -3
python3 scripts/weex_contract_api.py --profile main place-order --symbol ETHUSDT --side SELL --position-side SHORT --type LIMIT --quantity 0.001 --price 10000 --time-in-force GTC --confirm-live --pretty
```

For raw contract calls, `--profile is a global argument`; place it before `call`, then use `--endpoint <key>` for the official endpoint key. Some official query endpoints use POST and are therefore protected as mutating by the local guard even when the business action is a query; preview the request with `--dry-run` first, then pass `--confirm-live` only when you intentionally want to send that POST request.

Use `--dry-run` when you need to inspect the signed request without sending a mutating request:

```bash
# Windows users: replace python3 with py -3
python3 scripts/weex_contract_api.py --profile main place-order --symbol BTCUSDT --side BUY --position-side LONG --type MARKET --quantity 0.001 --confirm-live --dry-run --pretty
```

## AI Wars UploadAiLog

AI Wars automatic upload is available for real contract endpoints that represent AI-driven execution decisions:

- `transaction.place_order`
- `transaction.close_positions`
- `transaction.place_pending_order`
- `transaction.place_tp_sl_order`

For those endpoints, write the real AI decision context as UTF-8 JSON and pass it as `--ai-log @file.json`. The file must contain `stage`, `model`, `input`, `output`, and `explanation`. The `model` value must be the exact raw provider-returned model identifier, `input` must preserve the complete original prompt/source/context object, and `output` must match the final request body. Do not inline this JSON in shell commands.

The helper uploads the AI log only after the primary live trade response is business-successful. If the trade succeeds but UploadAiLog fails, the command exits with code `2`; inspect the `aiLog` object in the JSON output because the trade may already be executed.

```bash
# Windows users: replace python3 with py -3
python3 scripts/weex_contract_api.py --profile main --dump-ai-log-request-dir /tmp/weex-ai-captures place-order --symbol ETHUSDT --side SELL --position-side SHORT --type LIMIT --quantity 0.001 --price 2500 --time-in-force GTC --ai-log @/tmp/eth-ai-log.json --dry-run --confirm-live --pretty
```

Direct AI endpoint inspection:

```bash
# Windows users: replace python3 with py -3
python3 scripts/weex_ai_api.py list-endpoints --pretty
python3 scripts/weex_ai_api.py upload-ai-log --stage "Strategy Generation" --model "gpt-5-2026-03-01" --input @/tmp/ai-input.json --output @/tmp/ai-output.json --explanation "The model selected this action from the supplied market context." --dry-run --pretty
```

Current convenience wrappers:

- Contract: `ticker`, `poll-ticker`, `place-order`, `cancel-order`
- AI Wars: `list-endpoints`, `upload-ai-log`, `call`

For broader contract cancel/query/history flows, use the generic `call` command with the bundled endpoint catalog.

## Aggregation And Trade Guard

Private normalized payloads collect real contract data only.

```bash
# Windows users: replace python3 with py -3
python3 scripts/weex_trade_data_aggregator.py collect-account-risk --profile main --market futures --symbol BTCUSDT --pretty
python3 scripts/weex_trade_data_aggregator.py collect-order-risk --profile main --market futures --order-json '{"symbol":"BTCUSDT","side":"BUY","position_side":"LONG","order_type":"MARKET","quantity":"0.001"}' --pretty
python3 scripts/weex_trade_data_aggregator.py collect-replay --profile main --market futures --symbol BTCUSDT --period 7d --confirm-live --pretty
python3 scripts/weex_trade_data_aggregator.py collect-profile --profile main --market futures --period 30d --confirm-live --pretty
```

`collect-replay` and `collect-profile` include contract bills. That WEEX query is business read-only but uses HTTP POST, so both commands require `--confirm-live` before any account fetch begins. Omitting the flag fails closed without a network request. `collect-account-risk` and `collect-order-risk` do not expose that flag because their current collection paths use only GET requests.

Futures REST `quantity` is always sent in base-asset units. Structured callers may use `quantity_unit=BASE_ASSET` or `quantity_unit=CONTRACTS`; contract counts require the symbol's official `contractVal` and are converted exactly once before risk preview and submission. A base-asset quantity must never be multiplied by `contractVal` again.

`weex_trade_guard.py` binds profile, market, order preview, and alerts into the pending intent risk signature. Preview first, then confirm with the latest preview output.
Private account, order, cancel, TP/SL, and order-query outputs include `user_environment_prefix` whenever the command has environment context. Use that prefix as audit context only; do not add environment-switching prompts.

```bash
# Windows users: replace python3 with py -3
python3 scripts/weex_trade_guard.py preview-order --profile main --market futures --order-json '{"symbol":"BTCUSDT","side":"BUY","position_side":"LONG","order_type":"MARKET","quantity":"0.001"}' --language en --pretty
python3 scripts/weex_trade_guard.py confirm-order --intent-id <intent_id> --risk-signature <risk_signature> --confirm-live --pretty
```

## Automated Strategy Authorization

The automatic authorization facade is real-contract-only (`FUTURES`) and requires a saved profile. It rejects raw credentials, non-contract markets, practice-environment trading, arbitrary state paths, direct database fields, and caller-supplied trusted facts. The local state kernel owns strategy identity, authorization, quota, events, snapshots, and restore gates; all live state transitions require `--confirm-live`.

Use `scripts/weex_auto_trade.py` for registration, authorization, `submit-auto`, recovery, event inspection, snapshots, and reconciliation. Every automatic WEEX write must carry an AI Log whose `output` matches the final order body. Missing or mismatched logs fail closed before request preparation. `transaction.place_orders_batch` has no supported AI Log contract and returns `AI_LOG_CONTRACT_UNAVAILABLE` before state reservation, provider calls, or network access; use separate single-leg calls when each action has its own matching log.

Never derive `max_total_amount` from frequency, validity, target amount, `max_single_amount`, balance, or expected order count. An omitted cumulative quota requires a separate user choice, and the exact value must be present in the final confirmation. Real-trading automation may run only after one atomic update writes `ACTIVE` and an `UNTIL` no later than the authorization expiry; if that update cannot be atomic, keep it `PAUSED`.

Example authorization request:

```json
{"profile":"main","strategy_id":"<strategy_id>","trade_types":["FUTURES"],"symbols":["BTCUSDT"],"all_symbols":false,"max_single_amount":"200","max_total_amount":"2000","valid_hours":"720"}
```

```bash
python3 scripts/weex_auto_trade.py ensure-authorization --input @ensure-authorization.json --pretty
python3 scripts/weex_auto_trade.py grant-authorization --input @grant-authorization.json --confirm-live --pretty
```

The automatic operation catalog is limited to `transaction.place_order`, `transaction.place_pending_order`, and `transaction.place_tp_sl_order`. Full-position TP/SL, stale or degraded official facts, scope/quota violations, state conflicts, unknown operations, and uncertain submission results return to manual review without retry. A primary trade that succeeds while UploadAiLog fails also returns `REVIEW_REQUIRED` with the known order ID and `AI_LOG_UPLOAD_FAILED`; do not retry the trade. Accepted conservative quota is not changed by later reconciliation.

## Regenerate Definitions

To rebuild local contract REST definitions from the current WEEX V3 docs:

```bash
# Windows users: replace python3 with py -3
python3 scripts/generate_weex_api_definitions.py --product contract
```
