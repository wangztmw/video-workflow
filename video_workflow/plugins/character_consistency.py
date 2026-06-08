"""角色一致性插件：注入character_description到所有prompt"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import Plugin

if TYPE_CHECKING:
    from ..ucore.context import PipelineContext


class CharacterConsistencyPlugin(Plugin):
    name = "character_consistency"

    def after_step(self, step_name: str, ctx: PipelineContext) -> PipelineContext:
        if step_name == "script" and ctx.script:
            ctx.cache["character_desc"] = ctx.script.character_description
        return ctx

    def transform_prompt(self, step_name: str, prompt: str, ctx: PipelineContext) -> str:
        if step_name in ("image", "video"):
            char_desc = ctx.cache.get("character_desc", "")
            if char_desc and not prompt.startswith(char_desc):
                return f"{char_desc}. {prompt}"
        return prompt

    def transform_payload(self, step_name: str, payload: Any, ctx: PipelineContext) -> Any:
        if step_name == "video_payload" and hasattr(payload, 'prompt'):
            char_desc = ctx.cache.get("character_desc", "")
            if char_desc and not payload.prompt.startswith(char_desc):
                payload.prompt = f"{char_desc}. {payload.prompt}"
        return payload
