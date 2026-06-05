"""工作流编排：串联创意→剧本→分镜图→视频→精加工的全部步骤"""

from __future__ import annotations

import time
from pathlib import Path

from .config import load_config
from .models import Project, Scene
from .storage import ProjectStorage, slugify
from .script_writer import ScriptWriter
from .image_generator import ImageGenerator
from .video_creator import VideoCreator
from .storyboard import StoryboardRefiner
from .materials import MaterialManager


class VideoPipeline:
    """视频生成工作流编排器"""

    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)
        self.storage = ProjectStorage()
        self._script_writer: ScriptWriter | None = None
        self._image_gen: ImageGenerator | None = None
        self._video_creator: VideoCreator | None = None
        self._refiner: StoryboardRefiner | None = None

        # 全局DNS修复：一次patch，所有网络请求都受益
        try:
            from .dns_workaround import apply_global_dns_patch
            apply_global_dns_patch()
        except Exception:
            pass

    # ---- 懒加载，避免初始化时就需要所有API key ----

    @property
    def script_writer(self) -> ScriptWriter:
        if self._script_writer is None:
            self._script_writer = ScriptWriter(self.config)
        return self._script_writer

    @property
    def image_gen(self) -> ImageGenerator:
        if self._image_gen is None:
            self._image_gen = ImageGenerator(self.config)
        return self._image_gen

    @property
    def video_creator(self) -> VideoCreator:
        if self._video_creator is None:
            self._video_creator = VideoCreator(self.config)
        return self._video_creator

    @property
    def refiner(self) -> StoryboardRefiner:
        if self._refiner is None:
            self._refiner = StoryboardRefiner(self.config)
        return self._refiner

    # ================================================================
    # 完整工作流
    # ================================================================

    def run_full_pipeline(
        self,
        idea: str,
        project_name: str = "",
        style: str = "cinematic",
        target_duration: float = 60.0,
        skip_images: bool = False,
        auto_stitch: bool = True,
    ) -> Project:
        """
        完整工作流：创意 → 剧本 → 分镜图 → 视频 → 拼接

        Args:
            idea: 创意描述
            project_name: 项目名（空则自动生成）
            style: 视觉风格
            target_duration: 目标时长（秒）
            skip_images: 跳过分镜图生成
            auto_stitch: 完成后自动拼接为完整视频
        """
        # Step 0: 创建项目
        name = project_name or slugify(idea)[:40]
        project_dir = self.storage.create_project(name)

        project = Project(name=name)
        project.current_step = "script"
        self.storage.save_state(project)
        print(f"[pipeline] 项目 '{name}' 已创建: {project_dir}")

        # Step 1: 剧本创作
        project = self.step_generate_script(project, idea, style, target_duration)

        # Step 2: 分镜图
        if not skip_images:
            project = self.step_generate_images(project)
        else:
            print("[pipeline] 跳过分镜图生成")
            project.completed_steps.append("images")
            project.current_step = "videos"
            self.storage.save_state(project)

        # Step 3: 视频生成
        project = self.step_generate_videos(project)

        project.current_step = "done"
        project.completed_steps.append("videos")
        self.storage.save_state(project)

        # 自动拼接
        if auto_stitch and project.script and any(
            s.video_path for s in project.script.scenes
        ):
            try:
                self.cmd_stitch(project.name)
            except Exception as e:
                print(f"[pipeline] 自动拼接失败: {e}")

        print(f"\n[pipeline] ========== 工作流完成 ==========")
        self._print_summary(project)

        return project

    # ================================================================
    # 单步操作
    # ================================================================

    def step_generate_script(
        self,
        project: Project,
        idea: str = "",
        style: str = "cinematic",
        target_duration: float = 60.0,
    ) -> Project:
        """生成剧本并保存"""
        print(f"\n[pipeline] === 第1步: 剧本创作 ===")

        script = self.script_writer.generate_script(
            idea=idea or (project.script.idea if project.script else "未指定"),
            style=style or (project.script.style if project.script else "cinematic"),
            target_duration=target_duration or (
                project.script.target_duration if project.script else 60.0
            ),
        )

        project.script = script
        project.completed_steps = ["script"]
        project.current_step = "images"

        # 保存剧本版本和状态
        self.storage.save_script(script, project.name)
        self.storage.save_state(project)

        print(f"[pipeline] 剧本已保存: {script.title}")
        self._print_scene_list(script)
        return project

    def step_generate_images(self, project: Project) -> Project:
        """生成所有分镜图"""
        print(f"\n[pipeline] === 第2步: 分镜图生成 ===")

        if not project.script:
            raise ValueError("项目没有剧本，请先生成剧本")

        images_dir = self.storage.project_dir(project.name) / "images"

        def on_progress(i, total, scene, path):
            print(f"[pipeline] 图片进度: {i+1}/{total} - {scene.title} "
                  f"{'✅' if path else '❌'}")

        self.image_gen.generate_all(
            project.script.scenes,
            save_dir=images_dir,
            on_progress=on_progress,
        )

        project.completed_steps.append("images")
        project.current_step = "videos"
        self.storage.save_state(project)
        return project

    def step_generate_videos(self, project: Project) -> Project:
        """生成所有视频"""
        print(f"\n[pipeline] === 第3步: 视频生成 ===")

        if not project.script:
            raise ValueError("项目没有剧本")

        videos_dir = self.storage.project_dir(project.name) / "videos"

        def on_progress(task_id, status, video_url):
            scene = next(
                (s for s in project.script.scenes if s.video_task_id == task_id),
                None
            )
            label = scene.title if scene else task_id[:12]
            if status == "completed":
                print(f"[pipeline] ✅ {label} 完成")
            elif status == "failed":
                print(f"[pipeline] ❌ {label} 失败")

        tasks = self.video_creator.generate_all(
            project.script.scenes,
            save_dir=videos_dir,
            callback=on_progress,
        )

        # 记录任务到项目
        project.video_tasks.update(tasks)
        self.storage.save_state(project)
        return project

    def step_refine_scene(
        self,
        project: Project,
        scene_index: int,
        instruction: str,
        target_count: int = 3,
    ) -> Project:
        """精加工指定分镜"""
        print(f"\n[pipeline] === 分镜精加工 ===")

        if not project.script:
            raise ValueError("项目没有剧本")

        new_script = self.refiner.refine_script(
            project.script, scene_index, instruction, target_count
        )

        project.script = new_script
        # 精加工后的剧本需要重新生成素材
        project.completed_steps = ["script"]
        project.current_step = "images"
        project.video_tasks = {}
        self.storage.save_script(new_script, project.name)
        self.storage.save_state(project)

        print(f"[pipeline] 精加工完成，新剧本包含{len(new_script.scenes)}个分镜")
        self._print_scene_list(new_script)
        return project

    def resume(self, project_name: str) -> Project:
        """断点续跑"""
        print(f"[pipeline] 续跑项目: {project_name}")

        project = self.storage.load_state(project_name)
        print(f"[pipeline] 当前步骤: {project.current_step}")
        print(f"[pipeline] 已完成: {project.completed_steps}")

        if project.current_step == "images" and "images" not in project.completed_steps:
            project = self.step_generate_images(project)
            project = self.step_generate_videos(project)

        elif project.current_step == "videos" and "videos" not in project.completed_steps:
            # 检查是否有已提交但未完成的任务
            pending = {
                tid: vt for tid, vt in project.video_tasks.items()
                if vt.status in ("submitted", "processing")
            }
            if pending and project.script:
                print(f"[pipeline] 发现{len(pending)}个未完成的任务，续跑中...")
                videos_dir = self.storage.project_dir(project.name) / "videos"
                self.video_creator.resume_pending(
                    project.video_tasks,
                    project.script.scenes,
                    save_dir=videos_dir,
                )
                self.storage.save_state(project)

            # 提交未提交的分镜
            if project.script:
                unsubmitted = [
                    s for s in project.script.scenes
                    if s.status == "pending" and s.video_task_id == ""
                ]
                if unsubmitted:
                    print(f"[pipeline] 提交{len(unsubmitted)}个新分镜...")
                    project = self.step_generate_videos(project)
                else:
                    project.current_step = "done"
                    project.completed_steps.append("videos")
                    self.storage.save_state(project)

        elif project.current_step == "done" or "videos" in project.completed_steps:
            print("[pipeline] 项目已完成，无需续跑")
            if project.script:
                pending = {
                    tid: vt for tid, vt in project.video_tasks.items()
                    if vt.status in ("submitted", "processing")
                }
                if pending:
                    print(f"[pipeline] 但仍有{len(pending)}个任务在运行中，继续轮询...")
                    videos_dir = self.storage.project_dir(project.name) / "videos"
                    self.video_creator.resume_pending(
                        project.video_tasks,
                        project.script.scenes,
                        save_dir=videos_dir,
                    )
                    self.storage.save_state(project)

        print(f"[pipeline] 续跑完成，当前步骤: {project.current_step}")
        self._print_summary(project)
        return project

    # ================================================================
    # CLI命令实现
    # ================================================================

    def cmd_new(self, idea, project_name="", style="cinematic",
                target_duration=60.0, skip_images=False, auto_stitch=True):
        """'new' 命令：创建并运行完整工作流"""
        self.run_full_pipeline(
            idea=idea,
            project_name=project_name,
            style=style,
            target_duration=target_duration,
            skip_images=skip_images,
            auto_stitch=auto_stitch,
        )

    def cmd_script(self, project_name: str, idea_override: str = ""):
        """'script' 命令：为已有项目(重新)生成剧本"""
        project = self.storage.load_state(project_name)
        self.step_generate_script(
            project,
            idea=idea_override or project.script.idea if project.script else "",
        )

    def cmd_images(self, project_name: str, scene_index: int | None = None):
        """'images' 命令：生成分镜图"""
        project = self.storage.load_state(project_name)
        if scene_index is not None and project.script:
            scenes = [project.script.scenes[scene_index]]
        else:
            self.step_generate_images(project)
            return

        images_dir = self.storage.project_dir(project.name) / "images"
        self.image_gen.generate_all(scenes, save_dir=images_dir)
        self.storage.save_state(project)

    def cmd_videos(self, project_name: str, scene_index: int | None = None,
                   no_wait: bool = False):
        """'videos' 命令：生成视频"""
        project = self.storage.load_state(project_name)
        if not project.script:
            raise ValueError("项目没有剧本")

        videos_dir = self.storage.project_dir(project.name) / "videos"

        if scene_index is not None:
            scenes = [project.script.scenes[scene_index]]
        else:
            scenes = project.script.scenes

        tasks = self.video_creator.generate_all(scenes, save_dir=videos_dir, no_wait=no_wait)
        project.video_tasks.update(tasks)
        self.storage.save_state(project)

    def cmd_refine(self, project_name: str, scene_index: int, instruction: str):
        """'refine' 命令：分镜精加工"""
        project = self.storage.load_state(project_name)
        self.step_refine_scene(project, scene_index, instruction)

    def cmd_status(self, project_name: str):
        """'status' 命令：查看项目状态"""
        project = self.storage.load_state(project_name)
        self._print_summary(project)

    def cmd_resume(self, project_name: str):
        """'resume' 命令：断点续跑"""
        self.resume(project_name)

    def cmd_list(self):
        """'list' 命令：列出所有项目"""
        projects = self.storage.list_projects()
        if not projects:
            print("暂无项目")
            return
        print(f"共{len(projects)}个项目:")
        for name in projects:
            try:
                p = self.storage.load_state(name)
                sc = p.script.scene_count if p.script else 0
                vc = sum(
                    1 for vt in p.video_tasks.values()
                    if vt.status == "completed"
                )
                print(f"  {name:30s}  {p.current_step:8s}  {sc}分镜  {vc}视频")
            except Exception:
                print(f"  {name:30s}  (状态加载失败)")

    def cmd_check(self):
        """'check' 命令：环境检查"""
        from .check_env import run_check
        run_check()

    def cmd_stitch(self, project_name: str, output_name: str = "",
                   add_transition: bool = False):
        """'stitch' 命令：拼接分镜视频为完整视频"""
        from .video_stitcher import VideoStitcher

        project = self.storage.load_state(project_name)
        if not project.script:
            raise ValueError("项目没有剧本")

        # 收集已完成视频（按序号排序）
        videos = []
        scene_labels = []
        for scene in sorted(project.script.scenes, key=lambda s: s.index):
            if scene.video_path and Path(scene.video_path).exists():
                videos.append(scene.video_path)
                scene_labels.append(scene.title)
            else:
                print(f"[stitch] 跳过分镜 {scene.index}: {scene.title} (视频未就绪)")

        if not videos:
            raise RuntimeError("没有可拼接的视频")

        print(f"[stitch] 找到 {len(videos)} 个视频")

        output = output_name or f"{project.name}_final.mp4"
        output_path = self.storage.project_dir(project_name) / output

        stitcher = VideoStitcher()
        stitcher.stitch(videos, output_path, add_transitions=add_transition)

        print(f"\n[stitch] 完整视频: {output_path}")
        # 试播一下（Mac用open命令）
        import platform
        if platform.system() == "Darwin":
            print(f"[stitch] 正在打开视频...")
            import subprocess
            subprocess.run(["open", str(output_path)])

    def cmd_materials(self, project_name: str):
        """'materials' 命令：查看素材"""
        project = self.storage.load_state(project_name)
        project_dir = self.storage.project_dir(project_name)
        mgr = MaterialManager(project, project_dir)
        mgr.print_summary()

    # ================================================================
    # 显示辅助
    # ================================================================

    @staticmethod
    def _print_scene_list(script) -> None:
        """打印分镜列表"""
        if not script:
            return
        print(f"\n  剧本: {script.title}")
        print(f"  {'─' * 50}")
        for s in script.scenes:
            print(f"  [{s.index:2d}] {s.title:20s} {s.duration_seconds:4.0f}s  {s.mood}")
        print(f"  {'─' * 50}")
        print(f"  共{len(script.scenes)}个分镜，总时长≈{script.target_duration:.0f}秒\n")

    def _print_summary(self, project: Project) -> None:
        """打印项目摘要"""
        script = project.script
        if not script:
            print(f"项目: {project.name} (无剧本)")
            return

        scenes = script.scenes
        images_ok = sum(1 for s in scenes if s.image_path)
        videos_ok = sum(1 for s in scenes if s.video_path)

        print(f"  项目: {project.name}")
        print(f"  剧本: {script.title}")
        print(f"  分镜: {len(scenes)}个")
        print(f"  图片: {images_ok}/{len(scenes)} 完成")
        print(f"  视频: {videos_ok}/{len(scenes)} 完成")
        print(f"  状态: {project.current_step}")
