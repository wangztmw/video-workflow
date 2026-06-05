"""视频生成：通过Agnes AI异步视频API生成视频片段"""

from __future__ import annotations

import json
import time
import requests
from pathlib import Path

from .models import Scene, VideoTask
from .config import get_agnes_config


def _clamp_frames(num_frames: int) -> int:
    """确保帧数合法：≤441且满足8n+1"""
    n = min(num_frames, 441)
    if n % 8 != 1:
        n = ((n - 1) // 8) * 8 + 1
    return max(9, n)  # 最少9帧


def frames_for_duration(duration_seconds: float, frame_rate: int = 24) -> int:
    """根据时长计算合法的帧数"""
    raw = round(duration_seconds * frame_rate)
    return _clamp_frames(raw)


class VideoCreator:
    """Agnes AI 视频生成器——异步任务模型"""

    def __init__(self, config: dict):
        agnes = get_agnes_config(config)
        self.api_key = agnes["api_key"]
        self.base_url = agnes["base_url"].rstrip("/")
        self.model = agnes.get("video_model", "agnes-video-v2.0")
        self.width = agnes.get("video_width", 1152)
        self.height = agnes.get("video_height", 768)
        self.frame_rate = agnes.get("video_frame_rate", 24)
        self.poll_interval = agnes.get("video_poll_interval", 10)
        self.max_wait = agnes.get("video_max_wait", 600)

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

        # DNS workaround: 某些网络环境下Agnes域名可能被DNS污染
        self._apply_dns_workaround()

    # ---- 核心API调用 ----

    def _apply_dns_workaround(self):
        """如果DNS无法解析域名，使用全局socket补丁"""
        try:
            from .dns_workaround import apply_global_dns_patch
            apply_global_dns_patch()
        except Exception:
            pass  # DNS workaround is optional

    def submit_video_task(
        self,
        scene: Scene,
        width: int | None = None,
        height: int | None = None,
        num_frames: int | None = None,
        frame_rate: int | None = None,
    ) -> str:
        """
        提交视频生成任务

        Args:
            scene: 分镜对象
            width, height: 分辨率
            num_frames: 帧数（自动按duration计算）
            frame_rate: 帧率

        Returns:
            task_id

        Raises:
            RuntimeError: API调用失败
        """
        prompt = scene.video_prompt or scene.image_prompt or scene.description
        if not prompt:
            raise ValueError(f"分镜 {scene.id} 没有可用的视频prompt")

        width = width or self.width
        height = height or self.height
        frame_rate = frame_rate or self.frame_rate
        if num_frames is None:
            num_frames = frames_for_duration(scene.duration_seconds, frame_rate)

        print(f"[video] 提交任务: {scene.title} ({scene.id})")
        print(f"[video] 分辨率: {width}x{height}, {num_frames}帧 @{frame_rate}fps, 约{num_frames/frame_rate:.1f}秒")
        print(f"[video] Prompt: {prompt[:150]}...")

        payload = {
            "model": self.model,
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
        }

        # 自动重试（429限流时等待后重试）
        import time as _time
        max_retries = 5
        for attempt in range(max_retries):
            resp = self.session.post(
                f"{self.base_url}/videos",
                json=payload,
                timeout=30,
            )

            if resp.status_code == 200:
                data = resp.json()
                task_id = data.get("task_id", "")
                if task_id:
                    print(f"[video] 任务已提交: {task_id}")
                    return task_id
                raise RuntimeError(f"视频API未返回task_id: {json.dumps(data, ensure_ascii=False)[:500]}")

            if resp.status_code == 429 and attempt < max_retries - 1:
                wait = min(5 * (2 ** attempt), 60)  # 5s, 10s, 20s, 40s, 60s
                print(f"[video] 限流(429)，{wait}秒后重试({attempt+1}/{max_retries})...")
                _time.sleep(wait)
                continue

            raise RuntimeError(
                f"视频任务提交失败 (HTTP {resp.status_code}): {resp.text[:500]}"
            )

        raise RuntimeError("视频任务提交失败：重试耗尽")

    def poll_task(self, task_id: str) -> tuple[str, str]:
        """
        查询视频任务状态

        Args:
            task_id: 任务ID

        Returns:
            (status, video_url_or_empty_string)
            status: "processing" | "completed" | "failed"
        """
        resp = self.session.get(
            f"{self.base_url}/videos/{task_id}",
            timeout=30,
        )

        if resp.status_code != 200:
            return ("failed", "")

        data = resp.json()
        status = data.get("status", "processing")

        # 已知Bug: Agnes在remixed_from_video_id字段中返回视频URL
        video_url = (
            data.get("remixed_from_video_id") or
            data.get("video_url") or
            data.get("url") or
            ""
        )

        return (status, video_url)

    def download_video(self, video_url: str, save_path: str | Path) -> str:
        """下载视频到本地"""
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"[video] 下载视频: {video_url[:80]}...")
        for attempt in range(3):
            try:
                resp = requests.get(video_url, timeout=300, stream=True)
                if resp.status_code == 200:
                    with open(save_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    print(f"[video] 视频已保存: {save_path}")
                    return str(save_path)
                else:
                    print(f"[video] 下载失败 (HTTP {resp.status_code})，尝试{attempt+1}/3")
            except requests.RequestException as e:
                print(f"[video] 下载异常 ({e})，尝试{attempt+1}/3")

            if attempt < 2:
                time.sleep(2 ** attempt)  # 2s, 4s

        raise RuntimeError(f"视频下载失败，重试3次后仍失败: {video_url}")

    # ---- 高级接口 ----

    def generate_one(
        self,
        scene: Scene,
        save_path: str | Path,
        callback=None,
    ) -> VideoTask:
        """
        完整生命周期：提交→轮询→下载

        Args:
            scene: 分镜
            save_path: 保存路径
            callback: 回调(task_id, status, video_url_or_none)

        Returns:
            VideoTask（包含完整追踪信息）
        """
        # 提交
        task_id = self.submit_video_task(scene)
        scene.video_task_id = task_id
        scene.status = "video_submitted"

        video_task = VideoTask(
            task_id=task_id,
            scene_id=scene.id,
            status="submitted",
        )

        if callback:
            callback(task_id, "submitted", None)

        # 轮询
        elapsed = 0
        while elapsed < self.max_wait:
            time.sleep(self.poll_interval)
            elapsed += self.poll_interval
            video_task.poll_count += 1

            status, video_url = self.poll_task(task_id)
            video_task.status = status

            if callback:
                callback(task_id, status, video_url if status == "completed" else None)

            if status == "completed":
                if video_url:
                    video_task.video_url = video_url
                    # 下载
                    local_path = self.download_video(video_url, save_path)
                    video_task.local_path = local_path
                    scene.video_path = local_path
                    scene.status = "video_ready"
                    print(f"[video] ✅ 完成: {scene.title} ({scene.id})")
                else:
                    video_task.status = "failed"
                    video_task.error_message = "任务completed但未返回视频URL"
                    scene.status = "failed"
                    print(f"[video] ❌ {scene.title}: 任务completed但无视频URL")
                return video_task

            elif status == "failed":
                video_task.error_message = "Agnes返回failed状态"
                scene.status = "failed"
                print(f"[video] ❌ 失败: {scene.title} ({scene.id})")
                return video_task

            else:  # processing
                print(f"[video] ⏳ {scene.id} 处理中... ({elapsed}s/{self.max_wait}s)")
                continue

        # 超时
        video_task.status = "failed"
        video_task.error_message = f"超时({self.max_wait}s)"
        scene.status = "failed"
        print(f"[video] ⏰ 超时: {scene.id} ({self.max_wait}s)")
        return video_task

    def generate_all(
        self,
        scenes: list[Scene],
        save_dir: str | Path,
        no_wait: bool = False,
        callback=None,
    ) -> dict[str, VideoTask]:
        """
        批量生成视频

        Args:
            scenes: 分镜列表（跳过已完成的）
            save_dir: 保存目录
            no_wait: True则提交后立即返回，不轮询
            callback: 回调(task_id, status, video_url_or_none)

        Returns:
            {task_id: VideoTask}
        """
        save_dir = Path(save_dir)
        all_tasks: dict[str, VideoTask] = {}

        # 第一步：提交所有任务
        pending_scenes = [
            s for s in scenes if s.status not in ("video_ready",)
        ]

        print(f"[video] 共{len(scenes)}个分镜，{len(pending_scenes)}个待生成")

        for scene in pending_scenes:
            try:
                task_id = self.submit_video_task(scene)
                scene.video_task_id = task_id
                scene.status = "video_submitted"
                all_tasks[task_id] = VideoTask(
                    task_id=task_id,
                    scene_id=scene.id,
                    status="submitted",
                )
                time.sleep(0.5)  # 提交间隔
            except Exception as e:
                print(f"[video] 提交失败 {scene.id}: {e}")
                scene.status = "failed"

        if no_wait:
            print(f"[video] 已提交{len(all_tasks)}个任务，跳过等待")
            return all_tasks

        # 第二步：轮询所有任务直到完成
        print(f"[video] 等待{len(all_tasks)}个任务完成...")
        while all_tasks:
            for task_id, vtask in list(all_tasks.items()):
                if vtask.status in ("completed", "failed"):
                    continue

                status, video_url = self.poll_task(task_id)
                vtask.status = status
                vtask.poll_count += 1

                if callback:
                    callback(task_id, status, video_url if status == "completed" else None)

                if status == "completed" and video_url:
                    vtask.video_url = video_url
                    # 找到对应的scene
                    scene = next((s for s in scenes if s.video_task_id == task_id), None)
                    save_path = save_dir / f"{vtask.scene_id}.mp4"
                    try:
                        local_path = self.download_video(video_url, save_path)
                        vtask.local_path = local_path
                        if scene:
                            scene.video_path = local_path
                            scene.status = "video_ready"
                        print(f"[video] ✅ 完成: {vtask.scene_id}")
                    except Exception as e:
                        vtask.status = "failed"
                        vtask.error_message = f"下载失败: {e}"
                        if scene:
                            scene.status = "failed"
                        print(f"[video] ❌ 下载失败: {vtask.scene_id}")

                elif status == "failed":
                    scene = next((s for s in scenes if s.video_task_id == task_id), None)
                    if scene:
                        scene.status = "failed"
                    vtask.error_message = "Agnes返回failed"
                    print(f"[video] ❌ 任务失败: {vtask.scene_id}")

                else:
                    print(f"[video] ⏳ {vtask.scene_id}: {status} (已轮询{vtask.poll_count}次)")

            # 移除已完成的
            done = [tid for tid, vt in all_tasks.items() if vt.status in ("completed", "failed")]
            for tid in done:
                del all_tasks[tid]

            if not all_tasks:
                break
            time.sleep(self.poll_interval)

        print(f"[video] 批量生成完成")
        return all_tasks

    def resume_pending(
        self,
        video_tasks: dict[str, VideoTask],
        scenes: list[Scene],
        save_dir: str | Path,
        callback=None,
    ) -> dict[str, VideoTask]:
        """
        续跑：轮询之前已提交但未完成的任务，并下载已完成的

        Args:
            video_tasks: 已有的任务字典
            scenes: 分镜列表
            save_dir: 保存目录
            callback: 进度回调

        Returns:
            更新后的任务字典
        """
        save_dir = Path(save_dir)
        pending = {
            tid: vt for tid, vt in video_tasks.items()
            if vt.status in ("submitted", "processing")
        }
        completed_but_no_file = {
            tid: vt for tid, vt in video_tasks.items()
            if vt.status == "completed" and not vt.local_path and vt.video_url
        }

        print(f"[video] 续跑: {len(pending)}个待完成, {len(completed_but_no_file)}个待下载")

        # 下载已完成但未保存的
        for tid, vt in completed_but_no_file.items():
            save_path = save_dir / f"{vt.scene_id}.mp4"
            try:
                local_path = self.download_video(vt.video_url, save_path)
                vt.local_path = local_path
                scene = next((s for s in scenes if s.video_task_id == tid), None)
                if scene:
                    scene.video_path = local_path
                    scene.status = "video_ready"
                print(f"[video] ✅ 补下载完成: {vt.scene_id}")
            except Exception as e:
                vt.status = "failed"
                vt.error_message = f"补下载失败: {e}"
                print(f"[video] ❌ 补下载失败: {vt.scene_id}")

        # 轮询待完成的任务
        while pending:
            for tid, vt in list(pending.items()):
                status, video_url = self.poll_task(tid)
                vt.status = status
                vt.poll_count += 1

                if callback:
                    callback(tid, status, video_url if status == "completed" else None)

                if status == "completed" and video_url:
                    vt.video_url = video_url
                    save_path = save_dir / f"{vt.scene_id}.mp4"
                    try:
                        local_path = self.download_video(video_url, save_path)
                        vt.local_path = local_path
                        scene = next((s for s in scenes if s.video_task_id == tid), None)
                        if scene:
                            scene.video_path = local_path
                            scene.status = "video_ready"
                        print(f"[video] ✅ 续跑完成: {vt.scene_id}")
                    except Exception as e:
                        vt.status = "failed"
                        vt.error_message = f"下载失败: {e}"
                        print(f"[video] ❌ 下载失败: {vt.scene_id}")
                elif status == "failed":
                    vt.error_message = "Agnes返回failed"
                    print(f"[video] ❌ 任务失败: {vt.scene_id}")
                else:
                    print(f"[video] ⏳ {vt.scene_id}: {status} (轮询{vt.poll_count}次)")

            # 移除已完成的
            done = [tid for tid, vt in pending.items() if vt.status in ("completed", "failed")]
            for tid in done:
                del pending[tid]

            if not pending:
                break
            time.sleep(self.poll_interval)

        # 合并回原始字典
        video_tasks.update({tid: vt for tid, vt in pending.items()})
        return video_tasks
