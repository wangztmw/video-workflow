"""配置管理：三级优先级——环境变量 > config.json > 硬编码默认值"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_CONFIG_DIR = Path(__file__).parent.parent.parent  # video-workflow/
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"

DEFAULT_CONFIG: dict = {
    "seedance": {
        "api_key": "",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seedance-1-5-pro-251215",
        "video_poll_interval": 10,
        "video_max_wait": 600,
    },
    "agnes": {
        "api_key": "",
        "base_url": "https://apihub.agnes-ai.com/v1",
        "image_model": "agnes-image-2.1-flash",
        "video_model": "agnes-video-v2.0",
        "text_model": "agnes-1.5-pro",
        "video_width": 1152,
        "video_height": 768,
        "video_frame_rate": 24,
        "video_poll_interval": 10,
        "video_max_wait": 600,
    },
    "deepseek": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
        "temperature": 0.8,
        "max_tokens": 4096,
    },
}


def _env_overrides() -> dict:
    overrides: dict = {}
    if os.getenv("AGNES_API_KEY"):
        overrides.setdefault("agnes", {})["api_key"] = os.getenv("AGNES_API_KEY")
    if os.getenv("DEEPSEEK_API_KEY"):
        overrides.setdefault("deepseek", {})["api_key"] = os.getenv("DEEPSEEK_API_KEY")
    return overrides


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | None = None) -> dict:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                config = _deep_merge(config, json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[config] 警告: 读取配置文件失败 ({e})")
    env_overrides = _env_overrides()
    if env_overrides:
        config = _deep_merge(config, env_overrides)
    return config


def save_config(config: dict, config_path: str | None = None) -> None:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
