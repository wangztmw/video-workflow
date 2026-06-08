"""PipelineContext：贯穿整个Pipeline的共享状态容器"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core_type.project import Script
from ..core_type.storage import ProjectStorage, slugify
from ..utils.config import load_config


@dataclass
class ProjectSettings:
    """项目设置"""
    style: str = "cinematic"
    target_duration: float = 60.0
    video_width: int = 1152
    video_height: int = 768
    video_fps: int = 24
    video_poll_interval: int = 10
    video_max_wait: int = 600


class PipelineContext:
    """Pipeline共享上下文——数据在步骤间流转"""

    def __init__(self, idea: str = "", project_name: str = "", config_path: str | None = None):
        # 输入
        self.idea = idea
        self.project_name = project_name or slugify(idea)[:40]

        # 配置
        self.config = load_config(config_path)

        # 设置
        self.settings = ProjectSettings()
        agnes = self.config.get("agnes", {})
        self.settings.video_width = agnes.get("video_width", 1152)
        self.settings.video_height = agnes.get("video_height", 768)
        self.settings.video_fps = agnes.get("video_frame_rate", 24)
        self.settings.video_poll_interval = agnes.get("video_poll_interval", 10)
        self.settings.video_max_wait = agnes.get("video_max_wait", 600)

        # 运行时状态
        self.script: Script | None = None
        self.completed_steps: list[str] = []
        self.cache: dict[str, Any] = {}

        # 存储
        self._storage = ProjectStorage()
        self._project_dir: Path | None = None

    # ---- Provider获取（通过注册表） ----

    def get_text_provider(self):
        from .registry import ServiceRegistry
        return ServiceRegistry.get_text_provider(self.config)

    def get_image_provider(self):
        from .registry import ServiceRegistry
        return ServiceRegistry.get_image_provider(self.config)

    def get_video_provider(self):
        from .registry import ServiceRegistry
        return ServiceRegistry.get_video_provider(self.config)

    # ---- 目录管理 ----

    @property
    def project_dir(self) -> Path:
        if self._project_dir is None:
            self._project_dir = self._storage.create_project(self.project_name)
        return self._project_dir

    def image_path(self, scene_id: str) -> Path:
        return self._storage.image_path(self.project_name, scene_id)

    def video_path(self, scene_id: str) -> Path:
        return self._storage.video_path(self.project_name, scene_id)

    # ---- 状态持久化 ----

    def save(self):
        from ..core_type.project import Project, VideoTask
        project = Project(
            name=self.project_name,
            script=self.script,
            video_tasks={},
            completed_steps=self.completed_steps,
            current_step=self.completed_steps[-1] if self.completed_steps else "init",
        )
        self._storage.save_state(project)
        if self.script:
            self._storage.save_script(self.script, self.project_name)

    def load(self, project_name: str):
        """从state.json恢复"""
        project = self._storage.load_state(project_name)
        self.project_name = project.name
        self.script = project.script
        self.completed_steps = list(project.completed_steps)
        if self.script:
            self.idea = self.script.idea
            self.settings.style = self.script.style
        self._project_dir = self._storage.project_dir(project_name)

    def mark_completed(self, step_name: str):
        if step_name not in self.completed_steps:
            self.completed_steps.append(step_name)

    # ---- 插件集成 ----

    def apply_plugin_transforms(self, transform_type: str, payload: Any) -> Any:
        """让所有插件有机会修改payload"""
        # 由Pipeline调用时注入plugins列表
        plugins = self.cache.get("_plugins", [])
        for p in plugins:
            payload = p.transform_payload(transform_type, payload, self)
        return payload

    def get_character_override(self, char_name: str) -> str:
        """获取素材库中角色的prompt覆盖"""
        bindings = self.cache.get("material_bindings", {})
        char_data = bindings.get("characters", {}).get(char_name, {})
        return char_data.get("appearance", "")

    def material_bindings(self) -> dict:
        return self.cache.get("material_bindings", {})
