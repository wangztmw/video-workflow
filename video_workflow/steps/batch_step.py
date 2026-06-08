"""批量视频生成：大故事分段→提交→轮询→下载→拼接"""

from __future__ import annotations

import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .base import PipelineStep
from ..providers.base import VideoParams

if TYPE_CHECKING:
    from ..ucore.context import PipelineContext


@dataclass
class Segment:
    """单个故事片段"""
    index: int
    title: str
    video_prompt: str
    transition_to_next: str = ""
    task_id: str = ""
    video_path: str = ""
    status: str = "pending"  # pending|submitted|completed|failed
    error: str = ""
    poll_count: int = 0

    def to_dict(self):
        return {
            "index": self.index, "title": self.title,
            "video_prompt": self.video_prompt,
            "transition_to_next": self.transition_to_next,
            "task_id": self.task_id, "video_path": self.video_path,
            "status": self.status, "error": self.error,
            "poll_count": self.poll_count,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d.get(k, "") if k in ("task_id", "video_path", "title", "video_prompt", "transition_to_next", "error") else d.get(k, 0) if k == "index" else d.get(k, "pending") if k == "status" else d.get(k, 0) for k in d})


# 更优雅的 from_dict
def _segment_from_dict(d: dict) -> Segment:
    seg = Segment(
        index=d["index"], title=d["title"], video_prompt=d["video_prompt"],
        transition_to_next=d.get("transition_to_next", ""),
    )
    seg.task_id = d.get("task_id", "")
    seg.video_path = d.get("video_path", "")
    seg.status = d.get("status", "pending")
    seg.error = d.get("error", "")
    seg.poll_count = d.get("poll_count", 0)
    return seg


class BatchStep(PipelineStep):
    """批量视频生成步骤"""
    name = "batch_video"

    def __init__(self, segments_json: str, project_name: str = "batch", quick_poll: bool = False):
        self.segments_json = Path(segments_json)
        self.project_name = project_name
        self.checkpoint_path: Path | None = None
        self.quick_poll = quick_poll  # 短轮询模式：5分钟一轮，反复运行

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        # 加载分段
        with open(self.segments_json) as f:
            data = json.load(f)

        char_desc = data.get("character_description", "")
        segments = [_segment_from_dict(s) for s in data["segments"]]

        # 注入角色描述到每个prompt
        for seg in segments:
            if char_desc and not seg.video_prompt.startswith(char_desc):
                seg.video_prompt = f"{char_desc}. {seg.video_prompt}"

        # checkpoint路径
        project_dir = Path("projects") / self.project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "videos").mkdir(exist_ok=True)
        self.checkpoint_path = project_dir / "checkpoint.json"

        # 尝试从checkpoint恢复
        segments = self._load_checkpoint(segments)

        provider = ctx.get_video_provider()
        fps = ctx.settings.video_fps

        # === 阶段1: 提交所有任务（带重试） ===
        for seg in segments:
            if seg.status in ("submitted", "completed"):
                continue  # 已处理
            submitted = False
            for attempt in range(10):  # 最多重试10次
                try:
                    params = VideoParams(
                        prompt=seg.video_prompt,
                        width=ctx.settings.video_width,
                        height=ctx.settings.video_height,
                        num_frames=self._dur_to_frames(12, fps),
                        frame_rate=fps,
                    )
                    if seg.transition_to_next and seg.index < len(segments) - 1:
                        params.prompt += f". END: {seg.transition_to_next}"
                    prev = segments[seg.index - 1] if seg.index > 0 else None
                    if prev and prev.transition_to_next:
                        params.prompt += f". START: continuing via {prev.transition_to_next}"

                    print(f"[batch] 提交 [{seg.index}] {seg.title} (尝试{attempt+1}/10)...")
                    tid = provider.submit(params)
                    seg.task_id = tid
                    seg.status = "submitted"
                    self._save_checkpoint(segments, data)
                    submitted = True
                    time.sleep(1)
                    break
                except Exception as e:
                    wait = min(5 * (2 ** attempt), 120)
                    print(f"[batch] [{seg.index}] 失败({attempt+1}/10): {str(e)[:80]}... 等{wait}s")
                    time.sleep(wait)
            if not submitted:
                seg.status = "failed"
                seg.error = "提交重试耗尽"
                self._save_checkpoint(segments, data)

        # === 阶段2: 轮询所有任务 ===
        pending = [s for s in segments if s.status == "submitted"]
        if pending:
            total_pending = len(pending)
            # quick_poll模式：短时间轮询，适合反复运行
            poll_interval = 10
            max_wait = 300 if self.quick_poll else ctx.settings.video_max_wait
            print(f"\n[batch] 轮询 {total_pending} 个任务 (最长{max_wait}s)...")
            elapsed = 0

            while pending and elapsed < max_wait:
                time.sleep(poll_interval)
                elapsed += poll_interval

                for seg in list(pending):
                    seg.poll_count += 1
                    try:
                        status, url = provider.poll(seg.task_id)
                        if status == "completed" and url:
                            save_path = project_dir / "videos" / f"segment_{seg.index:02d}.mp4"
                            try:
                                provider.download(url, save_path)
                                seg.video_path = str(save_path)
                                seg.status = "completed"
                                print(f"[batch] ✅ [{seg.index}] {seg.title}")
                            except Exception as e:
                                seg.status = "failed"
                                seg.error = f"下载失败: {e}"
                                print(f"[batch] ❌ [{seg.index}] 下载失败: {e}")
                            pending.remove(seg)
                            self._save_checkpoint(segments, data)
                        elif status == "failed":
                            seg.status = "failed"
                            seg.error = "API返回failed"
                            print(f"[batch] ❌ [{seg.index}] API失败")
                            pending.remove(seg)
                            self._save_checkpoint(segments, data)
                        elif seg.poll_count % 10 == 0:
                            print(f"[batch] ⏳ [{seg.index}] {status} ({elapsed}s, poll#{seg.poll_count})")
                    except Exception as e:
                        if seg.poll_count % 10 == 0:
                            print(f"[batch] ⏳ [{seg.index}] poll异常: {e}")

            # 超时处理
            for seg in pending:
                if seg.status != "completed":
                    seg.status = "failed"
                    seg.error = "轮询超时"
                    print(f"[batch] ⏰ [{seg.index}] 超时")
            self._save_checkpoint(segments, data)

        # 统计
        completed = sum(1 for s in segments if s.status == "completed")
        failed = sum(1 for s in segments if s.status == "failed")
        print(f"\n[batch] 结果: {completed}/{len(segments)} 完成, {failed} 失败")

        # 写入结果到ctx
        ctx.cache["batch_segments"] = segments
        ctx.cache["batch_project_dir"] = str(project_dir)
        ctx.cache["batch_title"] = data.get("title", "")

        # === 阶段3: 拼接 ===
        if completed >= 2:
            self._stitch(segments, project_dir)
        elif completed == 1:
            print(f"[batch] 只有1个视频完成，跳过拼接")

        return ctx

    def _stitch(self, segments: list[Segment], project_dir: Path):
        """拼接所有完成的视频"""
        from ..utils.stitcher import VideoStitcher
        videos = []
        for seg in segments:
            if seg.video_path and Path(seg.video_path).exists():
                videos.append(Path(seg.video_path))

        if len(videos) < 2:
            return

        output = project_dir / "final_complete.mp4"
        try:
            stitcher = VideoStitcher()
            stitcher.stitch(videos, output)

            # 如果所有视频都完成了，打开
            if len(videos) == len(segments):
                print(f"\n[batch] 完整成片: {output}")
                import platform, subprocess
                if platform.system() == "Darwin":
                    subprocess.run(["open", str(output)])
        except Exception as e:
            print(f"[batch] 拼接失败: {e}")

    def _save_checkpoint(self, segments: list[Segment], data: dict):
        """保存断点"""
        if not self.checkpoint_path:
            return
        state = {
            "title": data.get("title", ""),
            "character_description": data.get("character_description", ""),
            "segments": [s.to_dict() for s in segments],
        }
        tmp = self.checkpoint_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        tmp.replace(self.checkpoint_path)

    def _load_checkpoint(self, segments: list[Segment]) -> list[Segment]:
        """从断点恢复"""
        if not self.checkpoint_path or not self.checkpoint_path.exists():
            return segments

        with open(self.checkpoint_path) as f:
            state = json.load(f)

        saved = {s["index"]: _segment_from_dict(s) for s in state.get("segments", [])}
        for seg in segments:
            if seg.index in saved:
                saved_seg = saved[seg.index]
                seg.task_id = saved_seg.task_id
                seg.video_path = saved_seg.video_path
                seg.status = saved_seg.status
                seg.error = saved_seg.error
                seg.poll_count = saved_seg.poll_count

        restored = sum(1 for s in segments if s.status in ("submitted", "completed"))
        if restored:
            print(f"[batch] checkpoint恢复: {restored} 个任务已处理")
        return segments

    @staticmethod
    def _dur_to_frames(duration: float, fps: int = 24) -> int:
        n = round(duration * fps)
        n = min(n, 441)
        if n % 8 != 1:
            n = ((n - 1) // 8) * 8 + 1
        return max(9, n)
