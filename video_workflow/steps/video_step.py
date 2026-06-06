"""Step: 视频生成 —— 批量提交+轮询"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .base import PipelineStep
from ..providers.base import VideoParams

if TYPE_CHECKING:
    from ..core.context import PipelineContext


class VideoStep(PipelineStep):
    name = "video"

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.script:
            raise ValueError("请先生成剧本")

        provider = ctx.get_video_provider()

        # 收集待处理的场景
        pending = []
        for scene in ctx.script.scenes:
            if scene.status == "video_ready" and scene.video_path:
                print(f"[video] 跳过: {scene.title}")
                continue
            prompt = scene.video_prompt or scene.image_prompt or scene.description
            if not prompt:
                continue
            params = VideoParams(
                prompt=prompt,
                width=ctx.settings.video_width,
                height=ctx.settings.video_height,
                num_frames=self._dur_to_frames(scene.duration_seconds, ctx.settings.video_fps),
                frame_rate=ctx.settings.video_fps,
            )
            params = ctx.apply_plugin_transforms("video_payload", params)
            pending.append((scene, params))

        if not pending:
            print("[video] 所有分镜已完成")
            return ctx

        # 第一步：批量提交
        tasks = {}  # task_id -> (scene, save_path)
        for scene, params in pending:
            try:
                tid = provider.submit(params)
                tasks[tid] = (scene, str(ctx.video_path(scene.id)))
                scene.video_task_id = tid
                scene.status = "video_submitted"
                ctx.save()
                time.sleep(0.5)  # 提交间隔
            except Exception as e:
                print(f"[video] 提交失败 {scene.title}: {e}")
                scene.status = "failed"
                ctx.save()

        if not tasks:
            return ctx

        # 第二步：轮询所有任务
        print(f"[video] 等待 {len(tasks)} 个任务...")
        poll_interval = ctx.settings.video_poll_interval
        max_wait = ctx.settings.video_max_wait
        elapsed = 0

        while tasks and elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval

            for tid in list(tasks.keys()):
                scene, save_path = tasks[tid]
                try:
                    status, url = provider.poll(tid)
                    if status == "completed" and url:
                        provider.download(url, save_path)
                        scene.video_path = save_path
                        scene.status = "video_ready"
                        print(f"[video] ✅ {scene.title}")
                        del tasks[tid]
                        ctx.save()
                    elif status == "failed":
                        scene.status = "failed"
                        print(f"[video] ❌ {scene.title}")
                        del tasks[tid]
                        ctx.save()
                    else:
                        print(f"[video] ⏳ {scene.title}: {status} ({elapsed}s)")
                except Exception as e:
                    print(f"[video] 轮询异常 {scene.title}: {e}")

        # 超时的标记失败
        for tid, (scene, _) in tasks.items():
            if scene.status != "video_ready":
                scene.status = "failed"
                print(f"[video] ⏰ 超时: {scene.title}")
        ctx.save()
        return ctx

    @staticmethod
    def _dur_to_frames(duration: float, fps: int = 24) -> int:
        n = round(duration * fps)
        n = min(n, 441)
        if n % 8 != 1:
            n = ((n - 1) // 8) * 8 + 1
        return max(9, n)

    def can_skip(self, ctx: PipelineContext) -> bool:
        if not ctx.script:
            return False
        return all(s.status == "video_ready" for s in ctx.script.scenes)
