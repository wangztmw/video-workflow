"""Plugin 抽象基类"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..ucore.context import PipelineContext


class Plugin:
    name: str = ""

    def before_step(self, step_name: str, ctx: PipelineContext) -> PipelineContext:
        """步骤执行前"""
        return ctx

    def after_step(self, step_name: str, ctx: PipelineContext) -> PipelineContext:
        """步骤执行后"""
        return ctx

    def transform_payload(self, step_name: str, payload: Any, ctx: PipelineContext) -> Any:
        """修改API请求payload"""
        return payload

    def transform_prompt(self, step_name: str, prompt: str, ctx: PipelineContext) -> str:
        """修改prompt文本"""
        return prompt
