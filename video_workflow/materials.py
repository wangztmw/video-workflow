"""素材管理：跟踪和查询项目中所有生成的素材"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Project


class MaterialManager:
    """素材查询和导出"""

    def __init__(self, project: Project, project_dir: str | Path):
        self.project = project
        self.project_dir = Path(project_dir)

    def list_images(self) -> list[dict]:
        """列出所有分镜图"""
        result = []
        if self.project.script:
            for scene in self.project.script.scenes:
                if scene.image_path:
                    result.append({
                        "scene_id": scene.id,
                        "scene_title": scene.title,
                        "path": scene.image_path,
                        "status": scene.status,
                    })
        return result

    def list_videos(self) -> list[dict]:
        """列出所有视频素材"""
        result = []
        if self.project.script:
            for scene in self.project.script.scenes:
                entry = {
                    "scene_id": scene.id,
                    "scene_title": scene.title,
                    "path": scene.video_path,
                    "status": scene.status,
                    "task_id": scene.video_task_id,
                }
                result.append(entry)
        return result

    def list_scripts(self) -> list[dict]:
        """列出所有剧本版本"""
        scripts_dir = self.project_dir / "scripts"
        if not scripts_dir.is_dir():
            return []
        result = []
        for f in sorted(scripts_dir.glob("script_v*.json")):
            import json
            try:
                with open(f, "r") as fp:
                    data = json.load(fp)
                result.append({
                    "version": f.stem,
                    "path": str(f),
                    "title": data.get("title", ""),
                    "scene_count": len(data.get("scenes", [])),
                    "created_at": data.get("created_at", ""),
                })
            except Exception:
                result.append({"version": f.stem, "path": str(f), "error": "读取失败"})
        return result

    def get_scene_material(self, scene_id: str) -> dict | None:
        """获取单个分镜的所有素材"""
        if not self.project.script:
            return None
        for scene in self.project.script.scenes:
            if scene.id == scene_id:
                return {
                    "scene": scene.to_dict(),
                    "has_image": bool(scene.image_path),
                    "has_video": bool(scene.video_path),
                    "video_task": (
                        self.project.video_tasks.get(scene.video_task_id, {}).to_dict()
                        if scene.video_task_id in self.project.video_tasks
                        else None
                    ),
                }
        return None

    def export_summary(self) -> str:
        """生成素材清单的Markdown文本"""
        if not self.project.script:
            return f"# {self.project.name}\n\n暂无剧本\n"

        script = self.project.script
        lines = [
            f"# {script.title}",
            f"",
            f"- **创意**: {script.idea}",
            f"- **风格**: {script.style}",
            f"- **目标时长**: {script.target_duration:.0f}秒",
            f"- **分镜数**: {len(script.scenes)}",
            f"- **创建时间**: {script.created_at}",
            f"",
            "## 素材清单",
            f"",
            "| 序号 | 分镜 | 图片 | 视频 | 状态 |",
            "|------|------|------|------|------|",
        ]

        for scene in script.scenes:
            img = "✅" if scene.image_path else "—"
            vid = "✅" if scene.video_path else "—"
            lines.append(
                f"| {scene.index} | {scene.title} | {img} | {vid} | {scene.status} |"
            )

        lines.extend([
            "",
            "## 分镜详情",
            "",
        ])

        for scene in script.scenes:
            lines.extend([
                f"### {scene.index}. {scene.title} ({scene.duration_seconds:.0f}秒)",
                f"- **画面**: {scene.description}",
                f"- **台词**: {scene.dialogue or '(无)'}",
                f"- **镜头**: {scene.camera_direction}",
                f"- **氛围**: {scene.mood}",
                f"- **图片prompt**: {scene.image_prompt[:100]}...",
                f"- **视频prompt**: {scene.video_prompt[:100]}...",
                f"",
            ])

        return "\n".join(lines)

    def print_summary(self) -> None:
        """在终端打印素材摘要"""
        print(self.export_summary())
