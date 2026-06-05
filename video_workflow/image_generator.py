"""分镜图生成：通过Agnes AI文生图API为每个分镜生成故事板图片"""

from __future__ import annotations

import time
import requests
from pathlib import Path

from .models import Scene
from .config import get_agnes_config


class ImageGenerator:
    """Agnes AI 文生图"""

    def __init__(self, config: dict):
        agnes = get_agnes_config(config)
        self.api_key = agnes["api_key"]
        self.base_url = agnes["base_url"].rstrip("/")
        self.model = agnes.get("image_model", "agnes-image-2.1-flash")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

        # DNS workaround
        try:
            from .dns_workaround import apply_global_dns_patch
            apply_global_dns_patch()
        except Exception:
            pass

    def generate_scene_image(
        self,
        scene: Scene,
        save_path: str | Path,
        size: str = "1152x768",
    ) -> str:
        """
        为一个分镜生成故事板图片

        Args:
            scene: 分镜对象（使用scene.image_prompt作为prompt）
            save_path: 保存路径
            size: 图片尺寸

        Returns:
            保存的图片文件路径

        Raises:
            RuntimeError: 图片生成或下载失败
        """
        prompt = scene.image_prompt or scene.video_prompt or scene.description
        if not prompt:
            raise ValueError(f"分镜 {scene.id} 没有可用的图片prompt")

        print(f"[image_gen] 生成分镜图: {scene.title} ({scene.id})")
        print(f"[image_gen] Prompt: {prompt[:120]}...")

        # 调用Agnes文生图API
        resp = self.session.post(
            f"{self.base_url}/images/generations",
            json={
                "model": self.model,
                "prompt": prompt,
                "size": size,
                "n": 1,
            },
            timeout=120,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Agnes图片生成失败 (HTTP {resp.status_code}): {resp.text[:500]}"
            )

        data = resp.json()
        # 提取图片URL——兼容多种返回格式
        image_url = ""
        if "data" in data and len(data["data"]) > 0:
            image_url = data["data"][0].get("url", "")
        if not image_url:
            image_url = data.get("url", "") or data.get("image_url", "")

        if not image_url:
            raise RuntimeError(f"Agnes图片API未返回URL: {json.dumps(data, ensure_ascii=False)[:500]}")

        # 下载图片
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        img_resp = requests.get(image_url, timeout=120)
        if img_resp.status_code != 200:
            raise RuntimeError(f"图片下载失败 (HTTP {img_resp.status_code})")

        with open(save_path, "wb") as f:
            f.write(img_resp.content)

        scene.image_path = str(save_path)
        scene.status = "image_ready"
        print(f"[image_gen] 图片已保存: {save_path}")
        return str(save_path)

    def generate_all(
        self,
        scenes: list[Scene],
        save_dir: str | Path,
        on_progress=None,
    ) -> list[tuple[Scene, str | None]]:
        """
        批量为所有分镜生成图片

        Args:
            scenes: 分镜列表
            save_dir: 保存目录
            on_progress: 回调 (index, total, scene, result_path_or_error)

        Returns:
            [(scene, image_path_or_None), ...]
        """
        save_dir = Path(save_dir)
        results = []
        total = len(scenes)

        for i, scene in enumerate(scenes):
            if scene.status == "image_ready" and scene.image_path:
                print(f"[image_gen] 跳过已有图片: {scene.title}")
                results.append((scene, scene.image_path))
                if on_progress:
                    on_progress(i, total, scene, scene.image_path)
                continue

            path = save_dir / f"{scene.id}.png"
            try:
                result_path = self.generate_scene_image(scene, str(path))
                results.append((scene, result_path))
                if on_progress:
                    on_progress(i, total, scene, result_path)
            except Exception as e:
                print(f"[image_gen] 分镜 {scene.id} 图片生成失败: {e}")
                scene.status = "failed"
                results.append((scene, None))
                if on_progress:
                    on_progress(i, total, scene, None)

            # 请求间隔，避免触发限流
            if i < total - 1:
                time.sleep(1)

        return results


