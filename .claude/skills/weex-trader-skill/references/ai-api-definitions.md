# WEEX AI API Definitions

Generated from live V3 docs on 2026-03-25.

Total endpoints: **1**

| Key | Method | Path | Auth |
|---|---|---|---|
| `ai.trade.upload_ai_log` | `POST` | `/capi/v3/order/uploadAiLog` | `True` |

## ai.trade.upload_ai_log — Upload AI log

- Method: `POST`
- Path: `/capi/v3/order/uploadAiLog`
- Category: `trade`
- Requires Auth: `True`
- Weight(IP/UID): `1 / 1`
- Source: https://www.weex.com/api-doc/ai/UploadAiLog

### Important Rules

- BUIDLs entering the live trading phase must provide an AI log (ai_log) containing:
- Model version
- Input and output data
- Order execution details
- The AI log is required to verify AI involvement and compliance.
- If you fail to provide valid proof of AI involvement, we will disqualify your team and remove it from the rankings.
- Only approved UIDs on the official allowlist may submit AI log data.

### Request Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `orderId` | `Long` | `No` | The order ID returned from your WEEX order API |
| `stage` | `String` | `Yes` | The trading stage where AI participated (e.g., "Strategy Generation") |
| `model` | `String` | `Yes` | The name or version of the AI model used (e.g., "GPT-4-turbo") |
| `input` | `JSON` | `Yes` | The prompt, query, or input text given to the AI model. If the input includes attachments (e.g., files, images), please provide links |
| `output` | `JSON` | `Yes` | The AI model's generated output, including predictions or decision recommendations. For inference models, show the inference process |
| `explanation` | `String` | `Yes` | A concise explanation summarizing the AI's analysis and reasoning in natural language. Maximum length: 1000 characters |

### Response Parameters

| Name | Type | Description |
|---|---|---|
| `code` | `Integer` | Request status code, 0 indicates success |
| `msg` | `String` | Request result description, "success" indicates success |
| `data` | `String` | Returned business data, "upload success" indicates upload successful |
