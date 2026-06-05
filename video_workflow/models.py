"""数据模型：剧本、分镜、视频任务、项目"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Scene:
    """单个分镜"""
    id: str = field(default_factory=lambda: f"scene_{_uid()}")
    index: int = 0                     # 在剧本中的序号
    title: str = ""                    # 分镜标题
    description: str = ""              # 画面描述（中文）
    dialogue: str = ""                 # 旁白/台词
    camera_direction: str = ""         # 镜头运动
    mood: str = ""                     # 氛围
    duration_seconds: float = 5.0      # 时长(秒)
    image_prompt: str = ""             # 英文图生图prompt
    video_prompt: str = ""             # 英文视频prompt
    video_task_id: str = ""            # Agnes任务ID
    video_path: str = ""               # 本地视频路径
    image_path: str = ""               # 本地图片路径
    status: str = "pending"            # pending|image_ready|video_submitted|video_ready|failed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Scene:
        # 过滤掉不存在于dataclass中的key
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class Script:
    """完整剧本"""
    id: str = field(default_factory=_uid)
    title: str = ""                    # 视频标题
    idea: str = ""                     # 原始创意
    style: str = "cinematic"           # 视觉风格
    target_duration: float = 60.0      # 目标总时长(秒)
    scenes: list[Scene] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    refined_from: str = ""             # 父剧本ID（精加工来源）
    character_description: str = ""    # 角色一致性描述（英文，注入所有prompt）

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scenes"] = [s.to_dict() for s in self.scenes]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Script:
        scenes_data = d.pop("scenes", [])
        script = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        script.scenes = [Scene.from_dict(s) for s in scenes_data]
        return script

    @property
    def scene_count(self) -> int:
        return len(self.scenes)


@dataclass
class VideoTask:
    """视频生成任务追踪"""
    task_id: str = ""
    scene_id: str = ""
    status: str = "submitted"          # submitted|processing|completed|failed
    video_url: str = ""               # 远端URL
    local_path: str = ""              # 本地路径
    submitted_at: str = field(default_factory=_now)
    poll_count: int = 0
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VideoTask:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class Project:
    """项目状态——state.json的完整表示"""
    name: str = ""
    script: Script | None = None
    video_tasks: dict[str, VideoTask] = field(default_factory=dict)  # task_id -> VideoTask
    completed_steps: list[str] = field(default_factory=list)          # ["script", "images", "videos"]
    current_step: str = "init"         # init|script|images|videos|done
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "script": self.script.to_dict() if self.script else None,
            "video_tasks": {tid: t.to_dict() for tid, t in self.video_tasks.items()},
            "completed_steps": self.completed_steps,
            "current_step": self.current_step,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Project:
        project = cls(
            name=d.get("name", ""),
            completed_steps=d.get("completed_steps", []),
            current_step=d.get("current_step", "init"),
            created_at=d.get("created_at", _now()),
        )
        if d.get("script"):
            project.script = Script.from_dict(d["script"])
        tasks = d.get("video_tasks", {})
        project.video_tasks = {tid: VideoTask.from_dict(t) for tid, t in tasks.items()}
        return project
