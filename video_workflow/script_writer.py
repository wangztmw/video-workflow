"""剧本创作：通过DeepSeek将创意转化为结构化剧本"""

from __future__ import annotations

import json
import re
from openai import OpenAI

from .models import Script, Scene
from .config import get_deepseek_config
from .dns_workaround import apply_global_dns_patch

# 剧本创作系统提示
SYSTEM_PROMPT = """你是一个专业的短视频编剧，擅长将简单的创意转化为结构化的视频剧本。

## 你的任务
根据用户提供的创意、风格和目标时长，生成一个完整的分镜剧本。

## 输出格式
必须严格按照以下JSON格式输出，不要输出任何其他内容：
```json
{
  "title": "视频标题（中文，简洁有力）",
  "character_description": "角色一致性描述（英文，50-100词）。详细且精确地描述主角的外貌、体型、毛色/服装、面部特征、标志性细节。这段描述会被注入到每个分镜的image_prompt和video_prompt中，确保所有镜头中的角色形象一致。例如：'A orange tabby cat with golden-yellow eyes, white chin and chest, medium build, short fur with distinct dark orange stripes, pink nose, slightly torn left ear tip. The cat moves with graceful agility and has a curious, alert expression.'",
  "style": "视觉风格",
  "scenes": [
    {
      "index": 0,
      "title": "分镜标题",
      "description": "画面描述（中文）",
      "dialogue": "旁白或台词（中文）",
      "camera_direction": "镜头运动描述",
      "mood": "氛围",
      "duration_seconds": 5.0,
      "image_prompt": "英文图片prompt。必须以character_description开头，再接场景描述。例如：'[角色描述]. Wide shot of the cat on a rooftop...'",
      "video_prompt": "英文视频prompt。必须以character_description开头，再接动态场景。例如：'[角色描述]. The cat walking along a neon-lit alley, camera tracking...'"
    }
  ]
}
```

## 规则
- **角色一致性（最重要）**：先定义精确的character_description，然后每个image_prompt和video_prompt都必须在开头包含同样的character_description
- 每个分镜时长约5秒（4~7秒），scene数量 = target_duration / 5（向上取整）
- image_prompt和video_prompt必须用英文，详细且视觉化
- 角色描述要包含：物种/体型/毛色/眼睛/标志性特征，确保AI每次画出来是同一个人/动物
- 剧本要有叙事弧线：开端→发展→高潮→结尾"""


class ScriptWriter:
    """通过DeepSeek API生成结构化剧本（无DeepSeek key时自动回退Agnes文本模型）"""

    def __init__(self, config: dict):
        # 优先使用DeepSeek，无key时回退到Agnes文本模型
        try:
            ds_config = get_deepseek_config(config)
            self.api_key = ds_config["api_key"]
            self.base_url = ds_config["base_url"]
            self.model = ds_config.get("model", "deepseek-chat")
            self.provider = "deepseek"
        except ValueError:
            # 回退到Agnes AI文本模型
            from .config import get_agnes_config
            agnes_config = get_agnes_config(config)
            self.api_key = agnes_config["api_key"]
            self.base_url = agnes_config["base_url"]
            self.model = agnes_config.get("text_model", "agnes-2.0-flash")
            self.provider = "agnes"
            print(f"[script_writer] DeepSeek Key未配置，回退使用Agnes AI ({self.model})")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        # DNS workaround for Agnes API domain
        self._apply_dns_workaround()

        ds_config_fallback = config.get("deepseek", {})
        self.temperature = ds_config_fallback.get("temperature", 0.8)
        self.max_tokens = ds_config_fallback.get("max_tokens", 4096)

    def _apply_dns_workaround(self):
        """对Agnes API域名应用DNS patch（httpx/openai SDK需要通过socket层修复）"""
        try:
            from urllib.parse import urlparse
            hostname = urlparse(self.base_url).hostname
            if hostname and hostname in {"apihub.agnes-ai.com"}:
                apply_global_dns_patch()
        except Exception:
            pass

    def generate_script(
        self,
        idea: str,
        style: str = "cinematic",
        target_duration: float = 60.0,
    ) -> Script:
        """
        将创意转化为结构化剧本

        Args:
            idea: 视频创意（中文）
            style: 视觉风格（如 cinematic, anime, cyberpunk, 水墨画）
            target_duration: 目标总时长（秒）

        Returns:
            包含完整分镜的Script对象

        Raises:
            ValueError: DeepSeek返回的内容无法解析为有效JSON
        """
        scene_count = max(2, round(target_duration / 5))

        user_prompt = f"""请为以下创意编写一个视频剧本：

创意：{idea}
视觉风格：{style}
目标总时长：{target_duration}秒
大约{scene_count}个分镜

请严格按照JSON格式输出。"""

        print(f"[script_writer] 正在调用 {self.provider} ({self.model})...")
        print(f"[script_writer] 创意: {idea}")
        print(f"[script_writer] 风格: {style}, 目标时长: {target_duration}s, 约{scene_count}个分镜")

        # 第一次尝试
        content = self._call_deepseek(user_prompt)

        # 尝试解析JSON
        script = self._parse_response(content, idea, style, target_duration)
        if script is not None:
            print(f"[script_writer] 剧本生成成功: '{script.title}', {script.scene_count}个分镜")
            return script

        # 重试：追加更严格的格式要求
        print("[script_writer] 首次解析失败，重试中...")
        retry_prompt = user_prompt + "\n\n【重要提醒】请只输出JSON，不要包含任何其他文字。确保JSON格式完全正确。"
        content2 = self._call_deepseek(retry_prompt)
        script2 = self._parse_response(content2, idea, style, target_duration)
        if script2 is not None:
            print(f"[script_writer] 重试成功: '{script2.title}', {script2.scene_count}个分镜")
            return script2

        raise ValueError(
            f"DeepSeek两次返回都无法解析为有效JSON。\n"
            f"第一次返回(前200字): {content[:200]}\n"
            f"第二次返回(前200字): {content2[:200]}"
        )

    def _call_deepseek(self, user_prompt: str) -> str:
        """调用DeepSeek API，返回文本内容"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""

    def _parse_response(
        self, content: str, idea: str, style: str, target_duration: float
    ) -> Script | None:
        """尝试从LLM返回内容中提取JSON并解析为Script"""
        # 提取JSON块（可能被```json包裹）
        json_str = self._extract_json(content)
        if not json_str:
            return None

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        # 验证必要字段
        if "scenes" not in data or not isinstance(data["scenes"], list):
            return None

        script = Script(
            title=data.get("title", "未命名"),
            idea=idea,
            style=style,
            target_duration=target_duration,
            character_description=data.get("character_description", ""),
        )

        char_desc = script.character_description

        for i, sdata in enumerate(data["scenes"]):
            img_prompt = sdata.get("image_prompt", "")
            vid_prompt = sdata.get("video_prompt", "")

            # 确保角色描述在prompt开头（如果还没包含）
            if char_desc and not img_prompt.startswith(char_desc):
                img_prompt = f"{char_desc}. {img_prompt}"
            if char_desc and not vid_prompt.startswith(char_desc):
                vid_prompt = f"{char_desc}. {vid_prompt}"

            scene = Scene(
                index=sdata.get("index", i),
                title=sdata.get("title", f"分镜{i+1}"),
                description=sdata.get("description", ""),
                dialogue=sdata.get("dialogue", ""),
                camera_direction=sdata.get("camera_direction", ""),
                mood=sdata.get("mood", ""),
                duration_seconds=float(sdata.get("duration_seconds", 5.0)),
                image_prompt=img_prompt,
                video_prompt=vid_prompt,
            )
            script.scenes.append(scene)

        return script

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """从文本中提取JSON——处理被```json包裹的情况"""
        # 尝试匹配 ```json ... ```
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            return m.group(1).strip()

        # 尝试匹配 { ... }（找最外层的花括号）
        # 找第一个 { 和最后一个 }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]

        return None
