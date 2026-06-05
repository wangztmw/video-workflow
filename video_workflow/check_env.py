"""环境检查：验证API连接和配置是否正确"""

from __future__ import annotations

import socket
import sys


def check_dns(hostname: str, expected_ip_hint: str = "") -> bool:
    """检查域名DNS解析是否正常"""
    try:
        ips = socket.getaddrinfo(hostname, 443)
        for entry in ips:
            ip = entry[4][0]
            if ip in ("127.0.0.1", "::1", "0.0.0.0"):
                print(f"  ❌ DNS污染: {hostname} -> {ip} (被劫持到本地)")
                hint = expected_ip_hint or "请手动查询真实IP"
                print(f"     修复: sudo bash -c 'echo \"{hint} {hostname}\" >> /etc/hosts'")
                return False
            else:
                print(f"  ✅ DNS正常: {hostname} -> {ip}")
                return True
    except Exception as e:
        print(f"  ⚠️ DNS查询失败: {hostname} - {e}")
        return False
    return False


def check_api_key(key: str, name: str) -> bool:
    """检查API Key是否已设置"""
    if key and len(key) > 10:
        print(f"  ✅ {name} Key: {key[:8]}...{key[-4:]}")
        return True
    else:
        print(f"  ❌ {name} Key未设置")
        return False


def run_check(config_path: str | None = None):
    """运行环境检查"""
    from .config import load_config
    config = load_config(config_path)

    print("=" * 50)
    print("Video Workflow 环境检查")
    print("=" * 50)

    # DNS检查
    print("\n[DNS 解析]")
    check_dns("apihub.agnes-ai.com", "104.18.18.62")
    check_dns("api.deepseek.com")

    # API Key检查
    print("\n[API Key]")
    agnes_config = config.get("agnes", {})
    check_api_key(agnes_config.get("api_key", ""), "Agnes AI")
    check_api_key(config.get("deepseek", {}).get("api_key", ""), "DeepSeek")

    # 连通性检查
    print("\n[连通性]")
    try:
        import requests
        headers = {"Authorization": f"Bearer {agnes_config.get('api_key', '')}"}
        r = requests.get(
            f"{agnes_config.get('base_url', '').rstrip('/')}/chat/completions",
            headers=headers,
            timeout=10
        )
        # 非200也没关系，只要连上了
        print(f"  ✅ Agnes API 可连接 (HTTP {r.status_code})")
    except Exception as e:
        print(f"  ❌ Agnes API 连接失败: {e}")
        print(f"     如果DNS检查也失败，请先修复DNS问题：")
        print(f"     sudo bash -c 'echo \"104.18.18.62 apihub.agnes-ai.com\" >> /etc/hosts'")

    print("\n" + "=" * 50)
    print("检查完成。如有❌项，请按提示修复。")
    print("=" * 50)


if __name__ == "__main__":
    run_check()
