"""Step: 分镜图生成"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import PipelineStep

if TYPE_CHECKING:
    from ..core.context import PipelineContext


class ImageStep(PipelineStep):
    name = "image"

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.script:
            raise ValueError("请先生成剧本")

        provider = ctx.get_image_provider()

        for scene in ctx.script.scenes:
            if scene.status == "image_ready" and scene.image_path:
                print(f"[image] 跳过: {scene.title}")
                continue

            prompt = scene.image_prompt or scene.video_prompt or scene.description
            if not prompt:
                print(f"[image] 跳过 {scene.title}: 无prompt")
                continue

            # 插件可能在ctx.cache里放了素材URL
            prompt = self._inject_material_prompt(scene, ctx)

            try:
                result = provider.generate(
                    prompt=prompt,
                    save_path=str(ctx.image_path(scene.id)),
                )
                scene.image_path = result.local_path
                scene.status = "image_ready"
            except Exception as e:
                print(f"[image] 失败 {scene.title}: {e}")
                scene.status = "failed"

        return ctx

    def _inject_material_prompt(self, scene, ctx: PipelineContext) -> str:
        """注入素材库的角色/场景描述"""
        prompt = scene.image_prompt or scene.video_prompt
        # 从素材绑定中获取prompt增强
        for char_name in scene.characters:
            override = ctx.get_character_override(char_name)
            if override and override not in prompt:
                prompt = f"{override}. {prompt}"
        return prompt
