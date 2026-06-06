"""CLI：argparse + 命令路由"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..core.context import PipelineContext
from ..core.pipeline import Pipeline
from ..core.registry import ServiceRegistry

from ..steps.script_step import ScriptStep
from ..steps.image_step import ImageStep
from ..steps.video_step import VideoStep
from ..steps.stitch_step import StitchStep
from ..steps.refine_step import RefineStep

from ..plugins.character_consistency import CharacterConsistencyPlugin
from ..plugins.state_autosave import StateAutoSavePlugin

from ..utils.dns import apply_dns_patch
from ..utils.stitcher import VideoStitcher
from ..models.storage import ProjectStorage


def _default_pipeline(skip_images: bool = False) -> Pipeline:
    steps = [ScriptStep()]
    if not skip_images:
        steps.append(ImageStep())
    steps.extend([VideoStep(), StitchStep()])
    p = Pipeline(steps)
    p.use(CharacterConsistencyPlugin())
    p.use(StateAutoSavePlugin())
    return p


# ================================================================
# 命令实现
# ================================================================

def cmd_new(idea: str, project_name: str = "", style: str = "cinematic",
            duration: float = 60.0, skip_images: bool = False, config_path: str | None = None):
    apply_dns_patch()
    ctx = PipelineContext(idea=idea, project_name=project_name, config_path=config_path)
    ctx.settings.style = style
    ctx.settings.target_duration = duration

    pipeline = _default_pipeline(skip_images)
    ctx = pipeline.run(ctx)
    _print_summary(ctx)


def cmd_resume(project_name: str, config_path: str | None = None):
    apply_dns_patch()
    ctx = PipelineContext(config_path=config_path)
    ctx.load(project_name)
    print(f"[resume] 项目: {project_name}, 已完成: {ctx.completed_steps}")

    pipeline = _default_pipeline()
    ctx = pipeline.resume(ctx)
    _print_summary(ctx)


def cmd_refine(project_name: str, scene_index: int, instruction: str, config_path: str | None = None):
    apply_dns_patch()
    ctx = PipelineContext(config_path=config_path)
    ctx.load(project_name)

    step = RefineStep(scene_index, instruction)
    ctx = step.execute(ctx)
    ctx.mark_completed("script")
    ctx.save()
    _print_summary(ctx)


def cmd_stitch(project_name: str, output_name: str = "", add_transition: bool = False,
               config_path: str | None = None):
    apply_dns_patch()
    ctx = PipelineContext(config_path=config_path)
    ctx.load(project_name)

    if not ctx.script:
        raise ValueError("项目没有剧本")

    videos = []
    for scene in sorted(ctx.script.scenes, key=lambda s: s.index):
        if scene.video_path and Path(scene.video_path).exists():
            videos.append(Path(scene.video_path))
        else:
            print(f"[stitch] 跳过: {scene.title} (视频未就绪)")

    if not videos:
        raise RuntimeError("没有可拼接的视频")

    output = output_name or f"{project_name}_final.mp4"
    output_path = ctx.project_dir / output

    stitcher = VideoStitcher()
    stitcher.stitch(videos, output_path, fade=add_transition)

    print(f"\n[stitch] 完整视频: {output_path}")
    import platform, subprocess
    if platform.system() == "Darwin":
        subprocess.run(["open", str(output_path)])


def cmd_script(project_name: str, idea_override: str = "", config_path: str | None = None):
    apply_dns_patch()
    ctx = PipelineContext(config_path=config_path)
    try:
        ctx.load(project_name)
    except FileNotFoundError:
        ctx.project_name = project_name
    if idea_override:
        ctx.idea = idea_override

    step = ScriptStep()
    ctx = step.execute(ctx)
    ctx.mark_completed("script")
    ctx.save()
    _print_summary(ctx)


def cmd_images(project_name: str, scene_index: int | None = None, config_path: str | None = None):
    apply_dns_patch()
    ctx = PipelineContext(config_path=config_path)
    ctx.load(project_name)

    if scene_index is not None and ctx.script:
        # 只生成指定分镜
        ctx.script.scenes = [ctx.script.scenes[scene_index]]

    step = ImageStep()
    ctx = step.execute(ctx)
    ctx.save()


def cmd_videos(project_name: str, scene_index: int | None = None, config_path: str | None = None):
    apply_dns_patch()
    ctx = PipelineContext(config_path=config_path)
    ctx.load(project_name)

    if scene_index is not None and ctx.script:
        ctx.script.scenes = [ctx.script.scenes[scene_index]]

    step = VideoStep()
    ctx = step.execute(ctx)
    ctx.save()


def cmd_status(project_name: str, config_path: str | None = None):
    apply_dns_patch()
    ctx = PipelineContext(config_path=config_path)
    ctx.load(project_name)
    _print_summary(ctx)


def cmd_list():
    storage = ProjectStorage()
    projects = storage.list_projects()
    if not projects:
        print("暂无项目")
        return
    print(f"共{len(projects)}个项目:")
    for name in projects:
        try:
            p = storage.load_state(name)
            sc = p.script.scene_count if p.script else 0
            vc = sum(1 for t in p.video_tasks.values() if t.status == "completed")
            print(f"  {name:30s}  {p.current_step:8s}  {sc}分镜  {vc}视频")
        except Exception:
            print(f"  {name:30s}  (状态加载失败)")


def cmd_materials(project_name: str, config_path: str | None = None):
    apply_dns_patch()
    ctx = PipelineContext(config_path=config_path)
    ctx.load(project_name)
    if not ctx.script:
        print("暂无剧本")
        return

    script = ctx.script
    print(f"# {script.title}\n")
    print(f"- **创意**: {script.idea}")
    print(f"- **风格**: {script.style}")
    print(f"- **分镜数**: {len(script.scenes)}")
    print(f"- **角色描述**: {script.character_description[:100]}...")

    print("\n| 序号 | 分镜 | 图片 | 视频 | 状态 |")
    print("|------|------|------|------|------|")
    for scene in script.scenes:
        img = "✅" if scene.image_path else "—"
        vid = "✅" if scene.video_path else "—"
        print(f"| {scene.index} | {scene.title} | {img} | {vid} | {scene.status} |")

    print("\n## 分镜详情\n")
    for scene in script.scenes:
        print(f"### {scene.index}. {scene.title} ({scene.duration_seconds:.0f}秒)")
        print(f"- 画面: {scene.description}")
        print(f"- 台词: {scene.dialogue or '(无)'}")
        print(f"- 角色: {', '.join(scene.characters) or '(未标注)'}")
        print(f"- 场景: {scene.location or '(未标注)'}")
        print()


def cmd_check(config_path: str | None = None):
    import socket
    from ..utils.config import load_config
    config = load_config(config_path)

    print("=" * 50)
    print("Video Workflow 环境检查")
    print("=" * 50)

    print("\n[DNS]")
    for host in ["apihub.agnes-ai.com", "api.deepseek.com"]:
        try:
            ips = socket.getaddrinfo(host, 443)
            for entry in ips:
                ip = entry[4][0]
                if ip in ("127.0.0.1", "::1", "0.0.0.0"):
                    print(f"  ❌ {host} -> {ip} (DNS污染)")
                else:
                    print(f"  ✅ {host} -> {ip}")
                break
        except Exception as e:
            print(f"  ⚠️ {host}: {e}")

    print("\n[API Key]")
    for service in ["agnes", "deepseek"]:
        key = config.get(service, {}).get("api_key", "")
        if key and len(key) > 10:
            print(f"  ✅ {service}: {key[:8]}...{key[-4:]}")
        else:
            print(f"  ❌ {service}: 未设置")

    print("=" * 50)


def _print_summary(ctx: PipelineContext):
    if not ctx.script:
        print(f"项目: {ctx.project_name} (无剧本)")
        return
    s = ctx.script
    imgs = sum(1 for sc in s.scenes if sc.image_path)
    vids = sum(1 for sc in s.scenes if sc.video_path)
    print(f"\n[pipeline] ==========")
    print(f"  项目: {ctx.project_name}")
    print(f"  剧本: {s.title}")
    print(f"  分镜: {len(s.scenes)} | 图片: {imgs} | 视频: {vids}")
    print(f"  步骤: {ctx.completed_steps}")


# ================================================================
# argparse
# ================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="video-workflow", description="AI视频生成工作流")
    sub = p.add_subparsers(dest="command")

    p_new = sub.add_parser("new")
    p_new.add_argument("idea"); p_new.add_argument("--name", default="")
    p_new.add_argument("--style", default="cinematic"); p_new.add_argument("--duration", type=float, default=60.0)
    p_new.add_argument("--skip-images", action="store_true"); p_new.add_argument("--no-stitch", action="store_true")
    p_new.add_argument("--config", default=None)

    p_run = sub.add_parser("run")
    p_run.add_argument("idea"); p_run.add_argument("--name", default="")
    p_run.add_argument("--style", default="cinematic"); p_run.add_argument("--duration", type=float, default=60.0)
    p_run.add_argument("--skip-images", action="store_true"); p_run.add_argument("--no-stitch", action="store_true")
    p_run.add_argument("--config", default=None)

    p_script = sub.add_parser("script"); p_script.add_argument("project")
    p_script.add_argument("--idea", default=""); p_script.add_argument("--config", default=None)

    p_imgs = sub.add_parser("images"); p_imgs.add_argument("project")
    p_imgs.add_argument("--scene", type=int, default=None); p_imgs.add_argument("--config", default=None)

    p_vid = sub.add_parser("videos"); p_vid.add_argument("project")
    p_vid.add_argument("--scene", type=int, default=None); p_vid.add_argument("--no-wait", action="store_true")
    p_vid.add_argument("--config", default=None)

    p_ref = sub.add_parser("refine"); p_ref.add_argument("project")
    p_ref.add_argument("--scene", type=int, required=True); p_ref.add_argument("--instruction", required=True)
    p_ref.add_argument("--config", default=None)

    p_st = sub.add_parser("status"); p_st.add_argument("project"); p_st.add_argument("--config", default=None)
    p_res = sub.add_parser("resume"); p_res.add_argument("project"); p_res.add_argument("--config", default=None)
    sub.add_parser("list")

    p_stitch = sub.add_parser("stitch"); p_stitch.add_argument("project")
    p_stitch.add_argument("--output", default=""); p_stitch.add_argument("--transition", action="store_true")
    p_stitch.add_argument("--config", default=None)

    p_mat = sub.add_parser("materials"); p_mat.add_argument("project"); p_mat.add_argument("--config", default=None)

    p_chk = sub.add_parser("check"); p_chk.add_argument("--config", default=None)
    return p


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    try:
        cfg = getattr(args, 'config', None)
        if args.command in ("new", "run"):
            cmd_new(args.idea, args.name, args.style, args.duration,
                    args.skip_images, cfg)
        elif args.command == "script":
            cmd_script(args.project, args.idea, cfg)
        elif args.command == "images":
            cmd_images(args.project, args.scene, cfg)
        elif args.command == "videos":
            cmd_videos(args.project, args.scene, cfg)
        elif args.command == "refine":
            cmd_refine(args.project, args.scene, args.instruction, cfg)
        elif args.command == "status":
            cmd_status(args.project, cfg)
        elif args.command == "resume":
            cmd_resume(args.project, cfg)
        elif args.command == "list":
            cmd_list()
        elif args.command == "stitch":
            cmd_stitch(args.project, args.output, args.transition, cfg)
        elif args.command == "materials":
            cmd_materials(args.project, cfg)
        elif args.command == "check":
            cmd_check(cfg)
        return 0
    except KeyboardInterrupt:
        print("\n[workflow] 用户中断")
        return 130
    except Exception as e:
        print(f"[workflow] 错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
