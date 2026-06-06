"""Step: 创意 → 剧本"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from .base import PipelineStep
from ..models.project import Script, Scene

if TYPE_CHECKING:
    from ..core.context import PipelineContext

SYSTEM_PROMPT = """你是一个专业的短视频编剧，擅长将简单的创意转化为结构化的视频剧本。

## 输出格式（严格JSON，不要其他内容）
{
  "title": "视频标题（中文）",
  "character_description": "角色一致性描述（英文，50-100词）。详细描述主角外貌、体型、服装、面部特征、标志性细节。例如：'An orange tabby cat with golden eyes, white chest, short fur with dark stripes, pink nose, slightly torn left ear tip.'",
  "scenes": [{
    "index": 0, "title": "分镜标题",
    "description": "画面描述（中文）", "dialogue": "台词（中文）",
    "camera_direction": "镜头运动", "mood": "氛围",
    "duration_seconds": 5.0,
    "characters": ["角色名"], "location": "场景名",
    "image_prompt": "英文图片prompt（必须以character_description开头）",
    "video_prompt": "英文视频prompt（必须以character_description开头）"
  }]
}

## 规则
- 角色一致性（最重要）：先定义character_description，每个prompt以此开头
- 每个分镜4~7秒，scene数量 = target_duration / 5
- image_prompt和video_prompt必须英文
- 标注每个分镜的characters和location（用于素材匹配）
- 叙事弧线：开端→发展→高潮→结尾"""


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
