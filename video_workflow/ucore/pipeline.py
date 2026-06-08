"""Pipeline引擎：按序执行步骤，管理插件生命周期"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..steps.base import PipelineStep
    from ..plugins.base import Plugin
    from .context import PipelineContext


class Pipeline:
    """工作流引擎"""

    def __init__(self, steps: list[PipelineStep] | None = None):
        self.steps: list[PipelineStep] = steps or []
        self.plugins: list[Plugin] = []

    def add_step(self, step: PipelineStep):
        self.steps.append(step)

    def use(self, plugin: Plugin):
        self.plugins.append(plugin)

    def run(self, ctx: PipelineContext) -> PipelineContext:
        # 注入plugins引用到ctx，供transform调用
        ctx.cache["_plugins"] = self.plugins

        for step in self.steps:
            if step.can_skip(ctx):
                print(f"[pipeline] 跳过: {step.name}")
                continue

            print(f"\n[pipeline] === {step.name} ===")

            # 插件钩子：步骤前
            for p in self.plugins:
                ctx = p.before_step(step.name, ctx)

            # 执行步骤
            ctx = step.execute(ctx)

            # 插件钩子：步骤后
            for p in self.plugins:
                ctx = p.after_step(step.name, ctx)

        return ctx

    def resume(self, ctx: PipelineContext) -> PipelineContext:
        """断点续跑：跳过已完成的步骤"""
        ctx.cache["_plugins"] = self.plugins
        for step in self.steps:
            if step.can_skip(ctx):
                print(f"[pipeline] 跳过(已完成): {step.name}")
                continue
            print(f"\n[pipeline] === {step.name} (续跑) ===")
            for p in self.plugins:
                ctx = p.before_step(step.name, ctx)
            ctx = step.execute(ctx)
            for p in self.plugins:
                ctx = p.after_step(step.name, ctx)
        return ctx
