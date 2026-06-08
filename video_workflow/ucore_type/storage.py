"""项目存储：目录结构 + state.json 原子写入"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .project import Project, Script

DEFAULT_PROJECTS_DIR = Path(__file__).parent.parent.parent / "projects"


def slugify(name: str) -> str:
    s = re.sub(r'[^\w一-鿿-]', '-', name.strip())
    s = re.sub(r'-+', '-', s)
    return s.strip('-').lower() or "untitled"


class ProjectStorage:
    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else DEFAULT_PROJECTS_DIR

    def create_project(self, name: str) -> Path:
        project_dir = self.base_dir / slugify(name)
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "scripts").mkdir(exist_ok=True)
        (project_dir / "images").mkdir(exist_ok=True)
        (project_dir / "videos").mkdir(exist_ok=True)
        return project_dir

    def project_dir(self, name: str) -> Path:
        return self.base_dir / slugify(name)

    def project_exists(self, name: str) -> bool:
        return self.project_dir(name).is_dir()

    def save_state(self, project: Project) -> None:
        project_dir = self.project_dir(project.name)
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "scripts").mkdir(exist_ok=True)
        (project_dir / "images").mkdir(exist_ok=True)
        (project_dir / "videos").mkdir(exist_ok=True)
        tmp_path = project_dir / "state.json.tmp"
        state_path = project_dir / "state.json"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(project.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, state_path)

    def load_state(self, project_name: str) -> Project:
        from .project import Project as P
        state_path = self.project_dir(project_name) / "state.json"
        if not state_path.exists():
            raise FileNotFoundError(f"项目状态文件不存在: {state_path}")
        with open(state_path, "r", encoding="utf-8") as f:
            return P.from_dict(json.load(f))

    def save_script(self, script: Script, project_name: str) -> Path:
        scripts_dir = self.project_dir(project_name) / "scripts"
        existing = sorted(scripts_dir.glob("script_v*.json"))
        version = len(existing) + 1
        path = scripts_dir / f"script_v{version}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(script.to_dict(), f, indent=2, ensure_ascii=False)
        return path

    def image_path(self, project_name: str, scene_id: str) -> Path:
        return self.project_dir(project_name) / "images" / f"{scene_id}.png"

    def video_path(self, project_name: str, scene_id: str) -> Path:
        return self.project_dir(project_name) / "videos" / f"{scene_id}.mp4"

    def list_projects(self) -> list[str]:
        if not self.base_dir.is_dir():
            return []
        return sorted(
            d.name for d in self.base_dir.iterdir()
            if d.is_dir() and (d / "state.json").exists()
        )

    def delete_project(self, name: str) -> None:
        project_dir = self.project_dir(name)
        if project_dir.is_dir():
            shutil.rmtree(project_dir)
