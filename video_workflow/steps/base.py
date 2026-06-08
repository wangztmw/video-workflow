"""PipelineStep 抽象基类"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ucore.context import PipelineContext


class PipelineStep(ABC):
    name: str = ""

    @abstractmethod
    def execute(self, ctx: PipelineContext) -> PipelineContext:
        ...

    def can_skip(self, ctx: PipelineContext) -> bool:
        return self.name in ctx.completed_steps
