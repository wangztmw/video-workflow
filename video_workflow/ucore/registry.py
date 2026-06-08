"""服务注册表：按配置查找Provider"""

from __future__ import annotations

from typing import Any
from ..providers.base import TextProvider, ImageProvider, VideoProvider


class ServiceRegistry:
    """全局Provider注册表"""

    @staticmethod
    def get_text_provider(config: dict) -> TextProvider:
        ds = config.get("deepseek", {})
        if ds.get("api_key"):
            from ..providers.deepseek_text import DeepSeekTextProvider
            return DeepSeekTextProvider(ds)
        from ..providers.agnes_text import AgnesTextProvider
        print("[registry] DeepSeek Key未配置，使用Agnes文本模型")
        return AgnesTextProvider(config.get("agnes", {}))

    @staticmethod
    def get_image_provider(config: dict) -> ImageProvider:
        from ..providers.agnes_image import AgnesImageProvider
        return AgnesImageProvider(config.get("agnes", {}))

    @staticmethod
    def get_video_provider(config: dict) -> VideoProvider:
        sd = config.get("seedance", {})
        if sd.get("api_key"):
            from ..providers.seedance_video import SeedanceVideoProvider
            return SeedanceVideoProvider(sd)
        from ..providers.agnes_video import AgnesVideoProvider
        return AgnesVideoProvider(config.get("agnes", {}))
