# WEEX Contract Endpoints

Primary local definitions:

- `references/contract-api-definitions.json`
- `references/contract-api-definitions.md`

Commonly used groups:

- Market: `/capi/v3/market/*`
- Account: `/capi/v3/account/*`
- Transaction: `/capi/v3/*`

List the available contract endpoints:

```bash
python3 scripts/weex_contract_api.py list-endpoints --pretty
```

Call an endpoint by key:

```bash
python3 scripts/weex_contract_api.py call --endpoint <key> --query '{}' --body '{}' --pretty
```

Mutating calls require `--confirm-live`. AI-driven mutating calls that support automatic AI Wars logging require `--ai-log @file.json`.
