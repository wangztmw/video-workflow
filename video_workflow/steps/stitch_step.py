"""Step: 视频拼接"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .base import PipelineStep
from ..utils.stitcher import VideoStitcher

if TYPE_CHECKING:
    from ..core.context import PipelineContext


class StitchStep(PipelineStep):
    name = "stitch"

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.script:
            return ctx

        videos = []
        for scene in sorted(ctx.script.scenes, key=lambda s: s.index):
            if scene.video_path and Path(scene.video_path).exists():
                videos.append(Path(scene.video_path))
            else:
                print(f"[stitch] 跳过: {scene.title} (视频未就绪)")

        if not videos:
            print("[stitch] 没有可拼接的视频")
            return ctx

        output = ctx.project_dir / f"{ctx.project_name}_final.mp4"
        stitcher = VideoStitcher()
        stitcher.stitch(videos, output)
        ctx.cache["final_video"] = str(output)
        return ctx
