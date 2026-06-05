"""DNS workaround: override hostname resolution for HTTP clients.

某些网络环境下 Agnes AI 的 API 域名可能被 DNS 污染，这个模块提供
多种方式绕过 DNS 污染，确保能正确访问 Agnes AI API。

支持:
- requests 库: DNSOverrideAdapter (Session级别的URL重写)
- httpx/openai 库: socket monkey-patch (全局级别的DNS解析劫持)
"""

from __future__ import annotations

import socket
import urllib3
import requests
from contextlib import contextmanager
from requests.adapters import HTTPAdapter


# 预置的 DNS 覆盖（Agnes AI 的真实 Cloudflare IP）
AGNES_DNS_OVERRIDE = {
    "apihub.agnes-ai.com": "104.18.18.62",
}

# 记录原始的getaddrinfo，避免重复patch
_original_getaddrinfo = socket.getaddrinfo
_patched = False


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """替换socket.getaddrinfo，对特定域名返回真实IP"""
    overrides = AGNES_DNS_OVERRIDE
    if host in overrides:
        host = overrides[host]
    return _original_getaddrinfo(host, port, family, type, proto, flags)


def apply_global_dns_patch():
    """全局应用DNS patch（影响所有socket连接，包括httpx/openai SDK）"""
    global _patched
    if not _patched:
        socket.getaddrinfo = _patched_getaddrinfo
        _patched = True


def remove_global_dns_patch():
    """移除全局DNS patch"""
    global _patched
    if _patched:
        socket.getaddrinfo = _original_getaddrinfo
        _patched = False


@contextmanager
def dns_patch_context():
    """上下文管理器：临时应用DNS patch"""
    apply_global_dns_patch()
    try:
        yield
    finally:
        remove_global_dns_patch()


class DNSOverrideAdapter(HTTPAdapter):
    """
    HTTPAdapter that overrides DNS resolution for specific hosts via URL rewriting.

    用法：
        session = requests.Session()
        adapter = DNSOverrideAdapter({"apihub.agnes-ai.com": "104.18.18.62"})
        session.mount("https://", adapter)
    """

    def __init__(self, host_to_ip: dict[str, str] | None = None, **kwargs):
        self._host_to_ip = host_to_ip or {}
        super().__init__(**kwargs)

    def send(self, request, **kwargs):
        url_parts = urllib3.util.parse_url(request.url)
        hostname = url_parts.host
        if hostname and hostname in self._host_to_ip:
            real_ip = self._host_to_ip[hostname]
            new_url = request.url.replace(
                f"{url_parts.scheme}://{hostname}",
                f"{url_parts.scheme}://{real_ip}",
                1
            )
            request.url = new_url
            request.headers["Host"] = hostname

        return super().send(request, **kwargs)

    def add_override(self, hostname: str, ip: str):
        self._host_to_ip[hostname] = ip


def create_session_with_dns_override(
    api_key: str,
    host_to_ip: dict[str, str] | None = None,
) -> requests.Session:
    """创建一个带有DNS覆盖的requests Session"""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })

    overrides = dict(AGNES_DNS_OVERRIDE)
    if host_to_ip:
        overrides.update(host_to_ip)

    adapter = DNSOverrideAdapter(overrides)
    session.mount("https://", adapter)
    return session
