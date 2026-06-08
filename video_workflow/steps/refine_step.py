"""Step: 分镜精加工"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from .base import PipelineStep
from ..ucore_type.project import Script, Scene

if TYPE_CHECKING:
    from ..ucore.context import PipelineContext

REFINE_PROMPT = """你是分镜精加工专家。根据扩充指令，将一个分镜拆分成多个更详细的分镜。

输出格式（严格JSON）：
{"scenes": [{"title":"","description":"","dialogue":"","camera_direction":"","mood":"","duration_seconds":5.0,"image_prompt":"英文","video_prompt":"英文","characters":[],"location":""}]}

规则：
- 如果提供了character_description，每个image_prompt和video_prompt必须以此开头
- 细化后每个分镜3~7秒
- prompts必须用英文"""


class RefineStep(PipelineStep):
    name = "refine"

    def __init__(self, scene_index: int, instruction: str, target_count: int = 3):
        self.scene_index = scene_index
        self.instruction = instruction
        self.target_count = target_count

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.script or self.scene_index >= len(ctx.script.scenes):
            raise ValueError(f"分镜序号 {self.scene_index} 无效")

        original = ctx.script.scenes[self.scene_index]
        char_desc = ctx.script.character_description
        provider = ctx.get_text_provider()

        scene_json = json.dumps({
            "title": original.title, "description": original.description,
            "dialogue": original.dialogue, "camera_direction": original.camera_direction,
            "mood": original.mood, "duration_seconds": original.duration_seconds,
        }, ensure_ascii=False, indent=2)

        user_prompt = (
            f"原始分镜：\n{scene_json}\n\n"
            f"扩充指令：{self.instruction}\n"
            f"拆分成约{self.target_count}个分镜。\n"
            f"角色一致性描述：{char_desc or '(无)'}"
        )

        print(f"[refine] 精加工: {original.title}")
        raw = provider.generate(system_prompt=REFINE_PROMPT, user_prompt=user_prompt)
        refined = self._parse_scenes(raw, original.id, char_desc)

        if not refined:
            raw = provider.generate(system_prompt=REFINE_PROMPT,
                                    user_prompt=user_prompt + "\n【重要】请只输出JSON！")
            refined = self._parse_scenes(raw, original.id, char_desc)

        if not refined:
            raise ValueError("精加工失败：无法解析JSON")

        # 构建新剧本
        new_script = Script(
            title=ctx.script.title + " (精加工)",
            idea=ctx.script.idea, style=ctx.script.style,
            character_description=char_desc,
            refined_from=ctx.script.id,
        )
        before = ctx.script.scenes[:self.scene_index]
        after = ctx.script.scenes[self.scene_index + 1:]
        all_scenes = before + refined + after
        for i, s in enumerate(all_scenes):
            s.index = i
            s.status = "pending"
            s.image_path = s.video_path = s.video_task_id = ""
        new_script.scenes = all_scenes
        new_script.target_duration = sum(s.duration_seconds for s in all_scenes)

        ctx.script = new_script
        ctx.completed_steps = ["script"]  # 重置后续步骤
        print(f"[refine] 新剧本: {new_script.scene_count}个分镜")
        return ctx

    def _parse_scenes(self, raw: str, base_id: str, char_desc: str) -> list[Scene]:
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
        json_str = m.group(1) if m else ""
        if not json_str:
            s, e = raw.find('{'), raw.rfind('}')
            if s != -1 and e > s:
                json_str = raw[s:e + 1]
        if not json_str:
            return []

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return []

        scenes = []
        for i, sd in enumerate(data.get("scenes", [])):
            img = sd.get("image_prompt", "")
            vid = sd.get("video_prompt", "")
            if char_desc:
                if not img.startswith(char_desc):
                    img = f"{char_desc}. {img}"
                if not vid.startswith(char_desc):
                    vid = f"{char_desc}. {vid}"
            scenes.append(Scene(
                id=f"{base_id}_r{i}", index=0,
                title=sd.get("title", ""), description=sd.get("description", ""),
                dialogue=sd.get("dialogue", ""), camera_direction=sd.get("camera_direction", ""),
                mood=sd.get("mood", ""),
                duration_seconds=float(sd.get("duration_seconds", 5.0)),
                image_prompt=img, video_prompt=vid,
                characters=sd.get("characters", []), location=sd.get("location", ""),
            ))
        return scenes
