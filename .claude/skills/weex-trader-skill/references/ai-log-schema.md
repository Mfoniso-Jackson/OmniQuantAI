# AI Log Schema

This document defines the local `ai-log.json` contract used by `scripts/weex_contract_api.py` for automatic AI Wars log upload.

## Required Shape

`--ai-log` must be passed as:

- `@file.json`

Write the file as UTF-8.
Do not inline `--ai-log` JSON in PowerShell, and do not pipe non-ASCII Python source through here-strings such as `@'...'@ | python -`.

The payload must be a JSON object with these required fields:

```json
{
  "stage": "Strategy Generation",
  "model": "gpt-5-2026-03-01",
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "Describe the market setup for ETHUSDT and suggest a trade."
      }
    ],
    "market_context": {
      "symbol": "ETHUSDT",
      "price": 2450
    }
  },
  "output": {},
  "explanation": "Detailed reasoning explaining which specific facts in input led to the action."
}
```

## Field Rules

- `stage`: non-empty string
- `model`: non-empty string containing the exact raw provider-returned model identifier used for the request
- If the provider resolves an alias, router, deployment name, or family name to a concrete model id, upload the resolved concrete model id
- Do not replace the raw model id with a marketing name, shorthand family label, or guessed display name
- Do not use documentation placeholders such as `provider-returned-model-id`, `resolved-model-id`, `your-model-id`, or similar examples
- `input`: non-empty JSON object
- `input` must contain the complete prompt, raw source materials, and context that were sent to the model
- Preserve the original request format inside `input`: keep field names, nesting, message arrays, and attachment/link references exactly as used in the source request
- Do not summarize, flatten, rename, redact, or otherwise rewrite the request payload before upload
- `output`: JSON object
- `output` must contain only the concrete action decided by the AI, including the detailed parameters required to execute it
- Do not wrap `output` in helper-generated structures such as `aiDecision`, `tradeIntent`, or execution metadata
- `explanation`: non-empty string, maximum 1000 characters
- `explanation` must explain in detail why the AI chose the action in `output`, based on the specific contents of `input`

## Output Consistency Rules

For live futures auto-log flows, `ai-log.output` must match the final trade request:

- `transaction.place_order`
  - `symbol`
  - `side` or `action`
  - `positionSide`
  - `type`
  - `quantity`
  - `price` when `type = LIMIT`
- `transaction.close_positions`
  - concrete `symbol` is required
  - `action` / `intent` / `operation` must clearly express close or exit
- `transaction.place_pending_order`
  - `symbol`
  - `side` or `action`
  - `positionSide`
  - `type`
  - `quantity`
  - `triggerPrice`
  - `price` when `type = STOP` or `TAKE_PROFIT`
- `transaction.place_tp_sl_order`
  - `symbol`
  - `planType`
  - `positionSide`
  - `quantity`
  - `triggerPrice`
  - `executePrice` when provided

## Retry Safety

If the trade request succeeds but automatic AI log upload fails, the contract helper exits with code `2`.
Treat that case as `trade already executed`; inspect the returned `aiLog` failure details before deciding whether any follow-up call is safe.

## Example

```json
{
  "stage": "Strategy Generation",
  "model": "gpt-5-2026-03-01",
  "input": {
    "messages": [
      {
        "role": "system",
        "content": "You are a cautious futures trader."
      },
      {
        "role": "user",
        "content": "If ETHUSDT loses momentum near resistance, open a small short."
      }
    ],
    "market_context": {
      "symbol": "ETHUSDT",
      "price": 2450,
      "rsi": 42.1
    }
  },
  "output": {
    "symbol": "ETHUSDT",
    "action": "SELL",
    "positionSide": "SHORT",
    "type": "LIMIT",
    "quantity": "0.001",
    "price": "2448"
  },
  "explanation": "The uploaded market snapshot showed ETHUSDT trading into resistance near 2450 while RSI stayed below trend-confirmation levels and the prompt specifically asked for a short if momentum weakened. Because those concrete inputs pointed to a fading breakout attempt, the model chose a small limit short at 2448."
}
```
