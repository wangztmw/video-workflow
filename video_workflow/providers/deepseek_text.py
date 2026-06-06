"""DeepSeek 文本生成"""

from __future__ import annotations

from openai import OpenAI

from .base import TextProvider


class DeepSeekTextProvider(TextProvider):
    def __init__(self, config: dict):
        self.client = OpenAI(
            api_key=config["api_key"],
            base_url=config.get("base_url", "https://api.deepseek.com"),
        )
        self.model = config.get("model", "deepseek-v4-pro")

    def generate(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=kwargs.get("temperature", 0.8),
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        return resp.choices[0].message.content or ""
