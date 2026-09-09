#!/bin/bash
# Source this before running any weex-trader-skill / weex-analysis-skill /
# weex-monitor-skill command:
#
#   source scripts/activate_weex_skill_env.sh
#
# Fixes two real issues found while onboarding this project's WEEX API
# credentials, both invisible unless you go looking for them:
#
# 1. IPv4 forcing: api-contract.weex.com publishes both A and AAAA records,
#    but WEEX's account-key IP allowlist only checks the caller's IPv4
#    address. On any host with working IPv6 connectivity, both
#    requests/urllib3 (used by weex/client.py) and plain urllib.request
#    (used by the vendored weex-trader-skill scripts) prefer the IPv6 route
#    by default, so private calls silently go out over an address that was
#    never whitelisted and come back "Invalid IP" -- indistinguishable from
#    an actually-wrong allowlist entry. scripts/ipv4fix/sitecustomize.py
#    patches socket.getaddrinfo process-wide to fix this for every HTTP
#    client, without editing the vendored skill files.
#
# 2. SSL_CERT_FILE: the vendored skill scripts use urllib.request directly,
#    which (unlike requests) does not automatically use certifi's CA bundle
#    on this host, and fails with CERTIFICATE_VERIFY_FAILED otherwise.

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
export PYTHONPATH="${REPO_ROOT}/scripts/ipv4fix${PYTHONPATH:+:${PYTHONPATH}}"
export SSL_CERT_FILE="$(python3 -c 'import certifi; print(certifi.where())')"
