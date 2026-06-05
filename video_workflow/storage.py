"""项目存储管理：目录结构、state.json读写、素材组织"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Project, Script

DEFAULT_PROJECTS_DIR = Path(__file__).parent.parent / "projects"


def slugify(name: str) -> str:
    """将中文名称转为安全的目录名"""
    import re
    # 保留中文字符、字母、数字、连字符
    s = re.sub(r'[^\w一-鿿-]', '-', name.strip())
    s = re.sub(r'-+', '-', s)
    return s.strip('-').lower() or "untitled"


class ProjectStorage:
    """管理项目目录和状态文件"""

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else DEFAULT_PROJECTS_DIR

    # ---- 项目生命周期 ----

    def create_project(self, name: str) -> Path:
        """创建项目目录结构，返回项目目录路径"""
        slug = slugify(name)
        project_dir = self.base_dir / slug
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "scripts").mkdir(exist_ok=True)
        (project_dir / "images").mkdir(exist_ok=True)
        (project_dir / "videos").mkdir(exist_ok=True)
        return project_dir

    def project_dir(self, name: str) -> Path:
        """获取项目目录路径（不创建）"""
        slug = slugify(name)
        return self.base_dir / slug

    def project_exists(self, name: str) -> bool:
        return self.project_dir(name).is_dir()

    # ---- 状态持久化 ----

    def save_state(self, project: Project) -> None:
        """原子写入state.json"""
        project_dir = self.project_dir(project.name)
        state_path = project_dir / "state.json"
        tmp_path = project_dir / "state.json.tmp"

        data = project.to_dict()
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, state_path)  # 原子替换

    def load_state(self, project_name: str) -> Project:
        """加载state.json"""
        from .models import Project as P

        project_dir = self.project_dir(project_name)
        state_path = project_dir / "state.json"
        if not state_path.exists():
            raise FileNotFoundError(f"项目状态文件不存在: {state_path}")

        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return P.from_dict(data)

    # ---- 剧本版本管理 ----

    def save_script(self, script: Script, project_name: str) -> Path:
        """保存剧本为版本化JSON文件，返回文件路径"""
        project_dir = self.project_dir(project_name)
        scripts_dir = project_dir / "scripts"
        # 找到下一个版本号
        existing = sorted(scripts_dir.glob("script_v*.json"))
        version = len(existing) + 1
        path = scripts_dir / f"script_v{version}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(script.to_dict(), f, indent=2, ensure_ascii=False)
        return path

    def load_script(self, project_name: str, version: int | None = None) -> Script:
        """加载指定版本的剧本，None则加载最新"""
        from .models import Script as S

        project_dir = self.project_dir(project_name)
        scripts_dir = project_dir / "scripts"
        if version:
            path = scripts_dir / f"script_v{version}.json"
        else:
            existing = sorted(scripts_dir.glob("script_v*.json"))
            if not existing:
                raise FileNotFoundError(f"项目 {project_name} 没有保存的剧本")
            path = existing[-1]  # 最新版本

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return S.from_dict(data)

    # ---- 素材路径 ----

    def image_path(self, project_name: str, scene_id: str) -> Path:
        return self.project_dir(project_name) / "images" / f"{scene_id}.png"

    def video_path(self, project_name: str, scene_id: str) -> Path:
        return self.project_dir(project_name) / "videos" / f"{scene_id}.mp4"

    # ---- 工具方法 ----

    def list_projects(self) -> list[str]:
        """列出所有项目名"""
        if not self.base_dir.is_dir():
            return []
        projects = []
        for d in sorted(self.base_dir.iterdir()):
            if d.is_dir() and (d / "state.json").exists():
                projects.append(d.name)
        return projects

    def delete_project(self, name: str) -> None:
        """删除项目目录"""
        project_dir = self.project_dir(name)
        if project_dir.is_dir():
            shutil.rmtree(project_dir)
