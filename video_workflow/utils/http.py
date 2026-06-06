"""通用HTTP客户端：重试、超时、错误处理"""

from __future__ import annotations

import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def create_session(
    api_key: str = "",
    base_retries: int = 3,
    timeout: int = 30,
) -> requests.Session:
    """创建带重试和超时的requests Session"""
    session = requests.Session()
    if api_key:
        session.headers.update({"Authorization": f"Bearer {api_key}"})
    session.headers.setdefault("Content-Type", "application/json")

    if base_retries > 0:
        retry = Retry(
            total=base_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
    return session


def retry_with_backoff(
    fn, max_retries: int = 5, base_delay: float = 5.0, max_delay: float = 60.0
):
    """带指数退避的重试装饰器逻辑"""
    last_error = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                print(f"[http] 重试 {attempt+1}/{max_retries}，等待{delay:.0f}s...")
                time.sleep(delay)
    raise last_error
