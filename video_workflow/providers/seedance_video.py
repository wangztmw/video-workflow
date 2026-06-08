"""豆包 Seedance 视频生成 — 火山引擎方舟API"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .base import VideoProvider, VideoParams
from ..utils.http import create_session


class SeedanceVideoProvider(VideoProvider):
    """豆包 Seedance 1.5/2.0 视频生成"""

    def __init__(self, config: dict):
        self.api_key = config["api_key"]
        self.base_url = config.get("base_url", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        self.model = config.get("model", "doubao-seedance-1-5-pro-251215")
        self.session = create_session(self.api_key, base_retries=0, timeout=60)

    def submit(self, params: VideoParams) -> str:
        # 构建 content 数组
        content = [{"type": "text", "text": params.prompt}]

        # 参考图（Seedance支持最多9张）
        images = params.reference_images or []
        if params.image and params.image not in images:
            images.insert(0, params.image)
        for img_url in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": img_url},
                "role": "reference_image",
            })

        # 视频参考
        if params.reference_video:
            content.append({
                "type": "video_url",
                "video_url": {"url": params.reference_video},
                "role": "reference_video",
            })

        # 音频参考
        if params.reference_audio:
            content.append({
                "type": "audio_url",
                "audio_url": {"url": params.reference_audio},
                "role": "reference_audio",
            })

        # 分辨率映射
        resolution = "720p"
        if params.width >= 1920:
            resolution = "1080p"
        elif params.width <= 854:
            resolution = "480p"

        # 时长：优先用duration_seconds，否则从帧数推算
        duration = params.duration_seconds or max(4, round(params.num_frames / (params.frame_rate or 24)))

        payload = {
            "model": self.model,
            "content": content,
            "resolution": resolution,
            "duration": duration,
            "generate_audio": True,
            "watermark": False,
        }
        if params.seed is not None:
            payload["seed"] = params.seed

        print(f"[seedance] 提交: {params.prompt[:100]}...")
        print(f"[seedance] 分辨率: {resolution}, 时长: {duration}s, 参考图: {len(images)}张")

        for attempt in range(5):
            resp = self.session.post(
                f"{self.base_url}/contents/generations/tasks",
                json=payload, timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                tid = data.get("id", "")
                if tid:
                    print(f"[seedance] task_id: {tid}")
                    return tid
                raise RuntimeError(f"未返回task_id: {json.dumps(data)[:200]}")
            if resp.status_code == 429 and attempt < 4:
                wait = min(5 * (2 ** attempt), 60)
                print(f"[seedance] 限流，{wait}s后重试({attempt+1}/5)...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"提交失败 (HTTP {resp.status_code}): {resp.text[:300]}")

        raise RuntimeError("重试耗尽")

    def poll(self, task_id: str) -> tuple[str, str | None]:
        resp = self.session.get(
            f"{self.base_url}/contents/generations/tasks/{task_id}", timeout=30,
        )
        if resp.status_code != 200:
            return ("failed", None)
        data = resp.json()
        status = data.get("status", "queued")
        # Seedance 状态映射 → 统一接口
        if status == "succeeded":
            url = (
                data.get("content", {}).get("video_url", "") or ""
            )
            return ("completed", url if url else None)
        elif status in ("failed", "cancelled", "expired"):
            return ("failed", None)
        else:
            return ("processing", None)  # queued / running

    def download(self, url: str, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[seedance] 下载: {url[:80]}...")
        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=300, stream=True)
                resp.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                print(f"[seedance] 已保存: {path}")
                return path
            except Exception as e:
                print(f"[seedance] 下载失败({attempt+1}/3): {e}")
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
            print(f"[seedance] ⏳ {task_id[:20]}... ({elapsed}s/{max_wait}s)")
        raise TimeoutError(f"任务超时: {task_id}")
