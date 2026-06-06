"""Agnes AI 图片生成"""

from __future__ import annotations

import time
from pathlib import Path

import requests

from .base import ImageProvider, ImageResult
from ..utils.http import create_session


class AgnesImageProvider(ImageProvider):
    def __init__(self, config: dict):
        self.api_key = config["api_key"]
        self.base_url = config.get("base_url", "https://apihub.agnes-ai.com/v1").rstrip("/")
        self.model = config.get("image_model", "agnes-image-2.1-flash")
        self.session = create_session(self.api_key)

    def generate(self, prompt: str, size: str = "1152x768", **kwargs) -> ImageResult:
        save_path = kwargs.get("save_path")
        print(f"[agnes_image] 生成: {prompt[:100]}...")

        resp = self.session.post(
            f"{self.base_url}/images/generations",
            json={"model": self.model, "prompt": prompt, "size": size, "n": 1},
            timeout=120,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Agnes图片生成失败 (HTTP {resp.status_code}): {resp.text[:300]}")

        data = resp.json()
        image_url = ""
        if "data" in data and len(data["data"]) > 0:
            image_url = data["data"][0].get("url", "")
        if not image_url:
            image_url = data.get("url", "") or data.get("image_url", "")

        result = ImageResult(url=image_url)

        if save_path:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            img_resp = requests.get(image_url, timeout=120)
            img_resp.raise_for_status()
            with open(save_path, "wb") as f:
                f.write(img_resp.content)
            result.local_path = str(save_path)
            print(f"[agnes_image] 已保存: {save_path}")

        return result
