"""Force IPv4 DNS resolution for every process in this venv.

WEEX's account-key IP allowlist only checks the caller's IPv4 address, but
api-contract.weex.com also publishes AAAA (IPv6) records. On any host with
working IPv6 connectivity, both `requests`/urllib3 and plain `urllib.request`
prefer the IPv6 route by default, so private WEEX calls silently go out over
an address that was never whitelisted and come back "Invalid IP" -- which
looks identical to an actually-wrong allowlist entry. Patching
socket.getaddrinfo here covers every HTTP client in the venv (including the
vendored weex-trader-skill scripts) without editing third-party skill files.
"""

import socket

_original_getaddrinfo = socket.getaddrinfo


def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_only_getaddrinfo
