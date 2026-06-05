"""CLI入口——视频生成工作流"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-workflow",
        description="AI视频生成工作流：创意 → 剧本 → 分镜图 → 视频 → 精加工",
    )
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # ---- new: 创建新项目 ----
    p_new = sub.add_parser("new", help="从创意创建新项目")
    p_new.add_argument("idea", type=str, help="视频创意描述")
    p_new.add_argument("--name", type=str, default="", help="项目名称（默认自动生成）")
    p_new.add_argument("--style", type=str, default="cinematic", help="视觉风格")
    p_new.add_argument("--duration", type=float, default=60.0, help="目标总时长(秒)")
    p_new.add_argument("--skip-images", action="store_true", help="跳过分镜图生成")
    p_new.add_argument("--no-stitch", action="store_true", help="完成后不自动拼接视频")
    p_new.add_argument("--config", type=str, default=None, help="配置文件路径")

    # ---- run: 一键运行完整流程（同new但不问任何问题） ----
    p_run = sub.add_parser("run", help="一键运行完整流程（同new）")
    p_run.add_argument("idea", type=str, help="视频创意描述")
    p_run.add_argument("--name", type=str, default="", help="项目名称")
    p_run.add_argument("--style", type=str, default="cinematic", help="视觉风格")
    p_run.add_argument("--duration", type=float, default=60.0, help="目标总时长(秒)")
    p_run.add_argument("--skip-images", action="store_true", help="跳过分镜图生成")
    p_run.add_argument("--no-stitch", action="store_true", help="完成后不自动拼接视频")
    p_run.add_argument("--config", type=str, default=None, help="配置文件路径")

    # ---- script: (重新)生成剧本 ----
    p_script = sub.add_parser("script", help="为已有项目(重新)生成剧本")
    p_script.add_argument("project", type=str, help="项目名称")
    p_script.add_argument("--idea", type=str, default="", help="覆盖原始创意")
    p_script.add_argument("--config", type=str, default=None, help="配置文件路径")

    # ---- images: 生成分镜图 ----
    p_images = sub.add_parser("images", help="生成分镜图")
    p_images.add_argument("project", type=str, help="项目名称")
    p_images.add_argument("--scene", type=int, default=None, help="只生成指定序号的分镜")
    p_images.add_argument("--config", type=str, default=None, help="配置文件路径")

    # ---- videos: 生成视频 ----
    p_videos = sub.add_parser("videos", help="生成视频")
    p_videos.add_argument("project", type=str, help="项目名称")
    p_videos.add_argument("--scene", type=int, default=None, help="只生成指定序号的分镜")
    p_videos.add_argument("--no-wait", action="store_true", help="提交任务后不等待完成")
    p_videos.add_argument("--config", type=str, default=None, help="配置文件路径")

    # ---- refine: 分镜精加工 ----
    p_refine = sub.add_parser("refine", help="分镜精加工：扩充/细化指定场景")
    p_refine.add_argument("project", type=str, help="项目名称")
    p_refine.add_argument("--scene", type=int, required=True, help="要精加工的分镜序号")
    p_refine.add_argument("--instruction", type=str, required=True, help="精加工指令（如'加入追逐戏，增加紧张感'）")
    p_refine.add_argument("--config", type=str, default=None, help="配置文件路径")

    # ---- status: 查看项目状态 ----
    p_status = sub.add_parser("status", help="查看项目状态")
    p_status.add_argument("project", type=str, help="项目名称")
    p_status.add_argument("--config", type=str, default=None, help="配置文件路径")

    # ---- resume: 断点续跑 ----
    p_resume = sub.add_parser("resume", help="断点续跑中断的工作流")
    p_resume.add_argument("project", type=str, help="项目名称")
    p_resume.add_argument("--config", type=str, default=None, help="配置文件路径")

    # ---- list: 列出所有项目 ----
    sub.add_parser("list", help="列出所有项目")

    # ---- check: 环境检查 ----
    p_check = sub.add_parser("check", help="检查环境配置和API连通性")
    p_check.add_argument("--config", type=str, default=None, help="配置文件路径")

    # ---- stitch: 拼接视频 ----
    p_stitch = sub.add_parser("stitch", help="将分镜视频拼接成完整视频")
    p_stitch.add_argument("project", type=str, help="项目名称")
    p_stitch.add_argument("--output", type=str, default="", help="输出文件名（默认: {项目名}_final.mp4）")
    p_stitch.add_argument("--transition", action="store_true", help="添加淡入淡出转场")
    p_stitch.add_argument("--config", type=str, default=None, help="配置文件路径")

    # ---- materials: 查看素材 ----
    p_materials = sub.add_parser("materials", help="查看项目素材清单")
    p_materials.add_argument("project", type=str, help="项目名称")
    p_materials.add_argument("--config", type=str, default=None, help="配置文件路径")

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    # 延迟导入——避免启动时加载所有模块
    from .pipeline import VideoPipeline

    pipeline = VideoPipeline(config_path=getattr(args, 'config', None))

    try:
        if args.command == "new":
            pipeline.cmd_new(
                idea=args.idea,
                project_name=args.name,
                style=args.style,
                target_duration=args.duration,
                skip_images=args.skip_images,
                auto_stitch=not args.no_stitch,
            )
        elif args.command == "run":
            pipeline.cmd_new(
                idea=args.idea,
                project_name=args.name,
                style=args.style,
                target_duration=args.duration,
                skip_images=args.skip_images,
                auto_stitch=not args.no_stitch,
            )
        elif args.command == "script":
            pipeline.cmd_script(args.project, idea_override=args.idea)
        elif args.command == "images":
            pipeline.cmd_images(args.project, scene_index=args.scene)
        elif args.command == "videos":
            pipeline.cmd_videos(args.project, scene_index=args.scene, no_wait=args.no_wait)
        elif args.command == "refine":
            pipeline.cmd_refine(args.project, scene_index=args.scene, instruction=args.instruction)
        elif args.command == "status":
            pipeline.cmd_status(args.project)
        elif args.command == "resume":
            pipeline.cmd_resume(args.project)
        elif args.command == "list":
            pipeline.cmd_list()
        elif args.command == "stitch":
            pipeline.cmd_stitch(args.project, output_name=args.output, add_transition=args.transition)
        elif args.command == "materials":
            pipeline.cmd_materials(args.project)
        elif args.command == "check":
            pipeline.cmd_check()
        else:
            parser.print_help()
            return 1
        return 0
    except KeyboardInterrupt:
        print("\n[workflow] 用户中断，状态已保存。用 'resume' 命令继续。")
        return 130
    except Exception as e:
        print(f"[workflow] 错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
