"""状态自动保存插件：每个步骤完成后自动持久化"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Plugin

if TYPE_CHECKING:
    from ..ucore.context import PipelineContext


class StateAutoSavePlugin(Plugin):
    name = "state_autosave"

    def after_step(self, step_name: str, ctx: PipelineContext) -> PipelineContext:
        ctx.mark_completed(step_name)
        ctx.save()
        return ctx
