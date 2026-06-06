"""DNS workaround：socket层劫持，绕过DNS污染"""

from __future__ import annotations

import socket

AGNES_DNS_OVERRIDE = {"apihub.agnes-ai.com": "104.18.18.62"}

_original_getaddrinfo = socket.getaddrinfo
_patched = False


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host in AGNES_DNS_OVERRIDE:
        host = AGNES_DNS_OVERRIDE[host]
    return _original_getaddrinfo(host, port, family, type, proto, flags)


def apply_dns_patch():
    global _patched
    if not _patched:
        socket.getaddrinfo = _patched_getaddrinfo
        _patched = True


def remove_dns_patch():
    global _patched
    if _patched:
        socket.getaddrinfo = _original_getaddrinfo
        _patched = False
