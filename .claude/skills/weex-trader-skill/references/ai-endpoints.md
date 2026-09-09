# WEEX AI Endpoints (Compact)

Primary local definitions:
- `references/ai-api-definitions.json`
- `references/ai-api-definitions.md`

Docs roots:
- https://www.weex.com/api-doc/ai/intro
- https://www.weex.com/api-doc/ai/orderAPI

Base URL:
- `https://api-contract.weex.com`

Current local AI endpoint:
- `POST /capi/v3/order/uploadAiLog`
- https://www.weex.com/api-doc/ai/UploadAiLog

Local upload contract note:
- `model` must be the exact raw provider-returned model identifier used for the request
- If an alias or deployment name resolves to a concrete model id, upload the resolved concrete id instead of the alias
- `input` must be a non-empty JSON object containing the complete prompt, raw source materials, and context in the original request format
- Keep the original field names and structure; do not summarize or reshape the request payload before upload
- `output` should contain only the concrete AI action and its execution parameters
- `explanation` should describe in detail why the AI chose that action

Quick commands:

```bash
python3 scripts/weex_ai_api.py list-endpoints --pretty
python3 scripts/weex_ai_api.py call --endpoint ai.trade.upload_ai_log --body '{"stage":"Decision Making","model":"provider-returned-model-id","input":{"messages":[{"role":"user","content":"Summarize last 6h BTC/ETH correlation and give a directional signal."}],"marketContext":{"window":"6h","correlation":"0.42","btcStrength":"high","ethStrength":"weak"}},"output":{"symbol":"ETHUSDT","action":"SELL","positionSide":"SHORT","type":"MARKET","quantity":"0.001"},"explanation":"The prompt asked for a directional trade signal, and the supplied raw market context showed weakening BTC/ETH correlation with BTC strength materially exceeding ETH strength. Based on those specific inputs, the model chose a market short on ETHUSDT with a small fixed quantity."}' --dry-run --pretty
```

Convenience wrapper:

```bash
python3 scripts/weex_ai_api.py upload-ai-log \
  --stage "Strategy Generation" \
  --model "provider-returned-model-id" \
  --input '{"messages":[{"role":"system","content":"You are an AI trading analyst. Use the provided market context exactly as supplied."},{"role":"user","content":"Predict BTC/USDT price trend for the next 3 hours."}],"marketContext":{"RSI_14":36.8,"EMA_20":68950.4,"FundingRate":-0.0021,"OpenInterest":512.3}}' \
  --output '{"signal":"Buy","confidence":0.82,"target_price":69300,"reason":"Negative funding + rising open interest implies short squeeze potential."}' \
  --explanation "Low RSI and price near the EMA20 suggest weakening downside momentum. Negative funding with rising open interest points to short-side pressure and potential squeeze risk, indicating a bullish bias for BTC over the next three hours." \
  --dry-run --pretty
```
