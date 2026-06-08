"""Step: 创意 → 剧本"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from .base import PipelineStep
from ..ucore_type.project import Script, Scene

if TYPE_CHECKING:
    from ..ucore.context import PipelineContext

SYSTEM_PROMPT = """你是一个专业的短视频导演，擅长设计流畅的镜头语言和场景过渡。

## 输出格式（严格JSON，不要其他内容）
{
  "title": "视频标题（中文）",
  "character_description": "角色一致性描述（英文，50-100词）",
  "scenes": [{
    "index": 0, "title": "分镜标题",
    "description": "画面描述（中文）", "dialogue": "台词（中文）",
    "camera_direction": "镜头运动", "mood": "氛围",
    "duration_seconds": 5.0,
    "characters": ["角色名"], "location": "场景名",
    "image_prompt": "英文图片prompt",
    "video_prompt": "英文视频prompt",
    "transition_from_previous": "从前一个分镜到本分镜的过渡描述（英文）。描述摄像机如何自然衔接，如：'camera tilts up to rain sky, then tilts back down to reveal...'。第一个分镜写'none'。"
  }]
}

## 规则
- 角色一致性：先定义character_description，每个prompt以此开头
- 场景过渡（关键）：相邻分镜之间必须有自然的视觉过渡。用摄像机运动（tilt/pan/push/dolly）、环境遮挡（rain/fog/smoke/leaves）、或匹配动作（角色跨出门→下一幕跨入新场景）来连接
- video_prompt必须包含过渡描述：每个视频的结尾要引出下一个场景的视觉元素，开头要承接上一幕的视觉残留
- 例如分镜1结尾："camera tilts up toward the rain sky, filling the frame with falling raindrops"
- 例如分镜2开头："camera tilts down from the rain sky, revealing the same character now standing in a temple courtyard"
- 每个分镜4~7秒
- 标注每个分镜的characters和location"""


class ScriptStep(PipelineStep):
    name = "script"

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        provider = ctx.get_text_provider()
        idea = ctx.idea
        style = ctx.settings.style
        target_dur = ctx.settings.target_duration
        scene_count = max(2, round(target_dur / 5))

        print(f"[script] 调用 {provider.__class__.__name__}...")
        print(f"[script] 创意: {idea}")

        raw = provider.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=f"创意：{idea}\n风格：{style}\n目标时长：{target_dur}秒\n约{scene_count}个分镜",
        )

        script = self._parse(raw, idea, style, target_dur)
        if script is None:
            print("[script] 首次解析失败，重试...")
            raw2 = provider.generate(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=f"创意：{idea}\n风格：{style}\n目标时长：{target_dur}秒\n【重要】请只输出JSON！",
            )
            script = self._parse(raw2, idea, style, target_dur)

        if script is None:
            raise ValueError("两次尝试均无法解析剧本JSON")

        ctx.script = script
        print(f"[script] 剧本: '{script.title}', {script.scene_count}个分镜")
        return ctx

    def _parse(self, raw: str, idea: str, style: str, target_dur: float) -> Script | None:
        json_str = self._extract_json(raw)
        if not json_str:
            return None
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None
        if "scenes" not in data:
            return None

        script = Script(
            title=data.get("title", "未命名"),
            idea=idea, style=style, target_duration=target_dur,
            character_description=data.get("character_description", ""),
        )
        char_desc = script.character_description

        for i, sd in enumerate(data["scenes"]):
            img = sd.get("image_prompt", "")
            vid = sd.get("video_prompt", "")
            if char_desc:
                if not img.startswith(char_desc):
                    img = f"{char_desc}. {img}"
                if not vid.startswith(char_desc):
                    vid = f"{char_desc}. {vid}"

            scene = Scene(
                index=sd.get("index", i),
                title=sd.get("title", f"分镜{i+1}"),
                description=sd.get("description", ""),
                dialogue=sd.get("dialogue", ""),
                camera_direction=sd.get("camera_direction", ""),
                mood=sd.get("mood", ""),
                duration_seconds=float(sd.get("duration_seconds", 5.0)),
                image_prompt=img, video_prompt=vid,
                characters=sd.get("characters", []),
                location=sd.get("location", ""),
                transition=sd.get("transition_from_previous", ""),
            )
            script.scenes.append(scene)

        return script

    @staticmethod
    def _extract_json(text: str) -> str | None:
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            return m.group(1).strip()
        start, end = text.find('{'), text.rfind('}')
        if start != -1 and end > start:
            return text[start:end + 1]
        return None
