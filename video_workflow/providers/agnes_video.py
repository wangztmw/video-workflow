"""Agnes AI 视频生成 — 异步任务模型"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .base import VideoProvider, VideoParams
from ..utils.http import create_session


def _clamp_frames(n: int) -> int:
    n = min(n, 441)
    if n % 8 != 1:
        n = ((n - 1) // 8) * 8 + 1
    return max(9, n)


class AgnesVideoProvider(VideoProvider):
    def __init__(self, config: dict):
        self.api_key = config["api_key"]
        self.base_url = config.get("base_url", "https://apihub.agnes-ai.com/v1").rstrip("/")
        self.model = config.get("video_model", "agnes-video-v2.0")
        self.default_width = config.get("video_width", 1152)
        self.default_height = config.get("video_height", 768)
        self.default_fps = config.get("video_frame_rate", 24)
        self.poll_interval = config.get("video_poll_interval", 10)
        self.max_wait = config.get("video_max_wait", 600)
        self.session = create_session(self.api_key, base_retries=0, timeout=60)

    def submit(self, params: VideoParams) -> str:
        payload = {
            "model": self.model,
            "prompt": params.prompt,
            "width": params.width or self.default_width,
            "height": params.height or self.default_height,
            "num_frames": _clamp_frames(params.num_frames),
            "frame_rate": params.frame_rate or self.default_fps,
        }
        if params.seed is not None:
            payload["seed"] = params.seed
        if params.image:
            payload["image"] = params.image
        if params.keyframes:
            payload["mode"] = "keyframes"
            payload["keyframes"] = params.keyframes

        print(f"[agnes_video] 提交: {params.prompt[:100]}...")

        for attempt in range(5):
            resp = self.session.post(f"{self.base_url}/videos", json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                tid = data.get("task_id", "")
                if tid:
                    print(f"[agnes_video] task_id: {tid}")
                    return tid
                raise RuntimeError(f"未返回task_id: {json.dumps(data)[:200]}")
            if resp.status_code == 429 and attempt < 4:
                wait = min(5 * (2 ** attempt), 60)
                print(f"[agnes_video] 限流，{wait}s后重试({attempt+1}/5)...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"提交失败 (HTTP {resp.status_code}): {resp.text[:300]}")

        raise RuntimeError("重试耗尽")

    def poll(self, task_id: str) -> tuple[str, str | None]:
        resp = self.session.get(f"{self.base_url}/videos/{task_id}", timeout=30)
        if resp.status_code != 200:
            return ("failed", None)
        data = resp.json()
        status = data.get("status", "processing")
        url = (data.get("remixed_from_video_id") or
               data.get("video_url") or
               data.get("url") or "")
        return (status, url if url else None)

    def download(self, url: str, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[agnes_video] 下载: {url[:80]}...")
        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=300, stream=True)
                resp.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                print(f"[agnes_video] 已保存: {path}")
                return path
            except Exception as e:
                print(f"[agnes_video] 下载失败({attempt+1}/3): {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"下载失败: {url}")

    def full_cycle(self, params: VideoParams, save_path: Path,
                   poll_interval: int = 10, max_wait: int = 600) -> Path:
        task_id = self.submit(params)
        elapsed = 0
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            status, url = self.poll(task_id)
            if status == "completed" and url:
                return self.download(url, save_path)
            elif status == "failed":
                raise RuntimeError(f"任务失败: {task_id}")
            print(f"[agnes_video] ⏳ {task_id[:12]}... {status} ({elapsed}s/{max_wait}s)")
        raise TimeoutError(f"任务超时: {task_id}")
