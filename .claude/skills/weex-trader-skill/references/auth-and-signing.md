# Auth and Signing

REST base URL:

- contract: `https://api-contract.weex.com`
- custom base URLs must use `https://` and a host under `weex.com` or `weex.tech`

Private headers:

- `ACCESS-KEY`
- `ACCESS-PASSPHRASE`
- `ACCESS-TIMESTAMP` (ms)
- `ACCESS-SIGN`

Signing message:

- no query: `timestamp + METHOD + requestPath + body`
- with query: `timestamp + METHOD + requestPath + "?" + queryString + body`

Signature:

- `Base64(HMAC_SHA256(secret, message))`

Recommended credential source:

- profile metadata in `~/.weex-trader-skill/profiles.meta.json`
- secrets in the Application Vault

Optional environment overrides:

- `WEEX_TRADER_SKILL_HOME`: override the runtime state directory for profiles, vault files, and agent cache
- `WEEX_API_TIMEOUT`: override HTTP timeout in seconds for API calls
- `WEEX_CONTRACT_API_BASE`: override the contract REST host after host policy validation

Credential source policy:

- prefer saved profiles
- private commands require a saved profile
- if private credentials are missing, fail fast and ask the user to configure or fix a profile
- for server automation, save or rotate profile secrets with `--secrets-stdin-json` or `--api-key-env` / `--api-secret-env` / `--api-passphrase-env` instead of raw argv secrets
- public endpoints and endpoint-listing commands do not require a valid default profile
- an explicitly requested `--profile` must still resolve successfully
