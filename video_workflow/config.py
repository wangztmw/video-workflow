"""配置管理：三级优先级——环境变量 > config.json > 硬编码默认值"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_CONFIG_DIR = Path(__file__).parent.parent  # video-workflow/
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"

# 默认配置（最低优先级）
DEFAULT_CONFIG: dict = {
    "agnes": {
        "api_key": "",  # 请在config.json或环境变量AGNES_API_KEY中设置
        "base_url": "https://apihub.agnes-ai.com/v1",
        "image_model": "agnes-image-2.1-flash",
        "video_model": "agnes-video-v2.0",
        "text_model": "agnes-1.5-pro",
        # 视频默认参数
        "video_width": 1152,
        "video_height": 768,
        "video_frame_rate": 24,
        "video_poll_interval": 10,     # 轮询间隔(秒)
        "video_max_wait": 600,         # 最大等待(秒)
    },
    "deepseek": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "temperature": 0.8,
        "max_tokens": 4096,
    },
}


def _env_overrides() -> dict:
    """从环境变量提取配置覆盖"""
    overrides: dict = {}
    if os.getenv("AGNES_API_KEY"):
        overrides.setdefault("agnes", {})["api_key"] = os.getenv("AGNES_API_KEY")
    if os.getenv("DEEPSEEK_API_KEY"):
        overrides.setdefault("deepseek", {})["api_key"] = os.getenv("DEEPSEEK_API_KEY")
    return overrides


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个dict，override的值覆盖base"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | None = None) -> dict:
    """
    加载配置，优先级：环境变量 > config.json > 默认值

    Args:
        config_path: JSON配置文件路径，None则用默认路径

    Returns:
        合并后的配置dict
    """
    # Tier 3: 硬编码默认值
    config = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy

    # Tier 2: JSON配置文件
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                file_config = json.load(f)
            config = _deep_merge(config, file_config)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[config] 警告: 读取配置文件失败 ({e})，使用默认配置")

    # Tier 1: 环境变量（最高优先级）
    env_overrides = _env_overrides()
    if env_overrides:
        config = _deep_merge(config, env_overrides)

    return config


def save_config(config: dict, config_path: str | None = None) -> None:
    """保存配置到JSON文件"""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_agnes_config(config: dict) -> dict:
    """提取并验证Agnes AI配置"""
    agnes = config.get("agnes", {})
    if not agnes.get("api_key"):
        raise ValueError("Agnes API Key 未设置！请在 config.json 或环境变量 AGNES_API_KEY 中设置")
    return agnes


def get_deepseek_config(config: dict) -> dict:
    """提取并验证DeepSeek配置"""
    ds = config.get("deepseek", {})
    if not ds.get("api_key"):
        raise ValueError("DeepSeek API Key 未设置！请在 config.json 或环境变量 DEEPSEEK_API_KEY 中设置")
    return ds
