"""数据模型：Scene, Script, VideoTask, Project"""

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
    index: int = 0
    title: str = ""
    description: str = ""
    dialogue: str = ""
    camera_direction: str = ""
    mood: str = ""
    duration_seconds: float = 5.0
    image_prompt: str = ""
    video_prompt: str = ""
    video_task_id: str = ""
    video_path: str = ""
    image_path: str = ""
    status: str = "pending"
    transition: str = ""             # 从前一幕到本幕的过渡描述
    # 素材绑定（新增）
    characters: list[str] = field(default_factory=list)
    location: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Scene:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid_keys})


@dataclass
class Script:
    """完整剧本"""
    id: str = field(default_factory=_uid)
    title: str = ""
    idea: str = ""
    style: str = "cinematic"
    target_duration: float = 60.0
    scenes: list[Scene] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    refined_from: str = ""
    character_description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scenes"] = [s.to_dict() for s in self.scenes]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Script:
        scenes_data = d.pop("scenes", [])
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        script = cls(**{k: v for k, v in d.items() if k in valid_keys})
        script.scenes = [Scene.from_dict(s) for s in scenes_data]
        return script

    @property
    def scene_count(self) -> int:
        return len(self.scenes)

    def pending_scenes(self) -> list[Scene]:
        return [s for s in self.scenes if s.status not in ("video_ready",)]


@dataclass
class VideoTask:
    """视频生成任务追踪"""
    task_id: str = ""
    scene_id: str = ""
    status: str = "submitted"
    video_url: str = ""
    local_path: str = ""
    submitted_at: str = field(default_factory=_now)
    poll_count: int = 0
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VideoTask:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid_keys})


@dataclass
class Project:
    """项目状态"""
    name: str = ""
    script: Script | None = None
    video_tasks: dict[str, VideoTask] = field(default_factory=dict)
    completed_steps: list[str] = field(default_factory=list)
    current_step: str = "init"
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
        p = cls(
            name=d.get("name", ""),
            completed_steps=d.get("completed_steps", []),
            current_step=d.get("current_step", "init"),
            created_at=d.get("created_at", _now()),
        )
        if d.get("script"):
            p.script = Script.from_dict(d["script"])
        p.video_tasks = {tid: VideoTask.from_dict(t) for tid, t in d.get("video_tasks", {}).items()}
        return p
