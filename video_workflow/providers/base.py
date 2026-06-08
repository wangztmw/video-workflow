"""Provider抽象接口"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ImageResult:
    url: str = ""
    local_path: str = ""


@dataclass
class VideoParams:
    prompt: str = ""
    width: int = 1152
    height: int = 768
    num_frames: int = 113
    frame_rate: int = 24
    seed: int | None = None
    image: str = ""          # 图生视频：参考图URL
    keyframes: list[dict] | None = None  # 关键帧模式
    duration_seconds: int = 0            # 直接指定秒数（Seedance）
    reference_images: list[str] | None = None   # 多图参考（最多9张）
    reference_video: str = ""            # 视频参考
    reference_audio: str = ""            # 音频参考


class TextProvider(ABC):
    """文本生成"""
    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        ...


class ImageProvider(ABC):
    """图片生成"""
    @abstractmethod
    def generate(self, prompt: str, size: str = "1152x768", **kwargs) -> ImageResult:
        ...


class VideoProvider(ABC):
    """视频生成"""
    @abstractmethod
    def submit(self, params: VideoParams) -> str:
        """提交任务 → task_id"""
        ...

    @abstractmethod
    def poll(self, task_id: str) -> tuple[str, str | None]:
        """查询 → (status, video_url)"""
        ...

    @abstractmethod
    def download(self, url: str, path: Path) -> Path:
        """下载视频到本地"""
        ...

    @abstractmethod
    def full_cycle(self, params: VideoParams, save_path: Path,
                   poll_interval: int = 10, max_wait: int = 600) -> Path:
        """完整生命周期：submit → poll → download"""
        ...
