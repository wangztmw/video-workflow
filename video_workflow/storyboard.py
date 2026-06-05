"""分镜精加工：场景扩充、细化、插入新场景"""

from __future__ import annotations

import json
import re
from openai import OpenAI

from .models import Script, Scene
from .config import get_deepseek_config

REFINE_SYSTEM_PROMPT = """你是一个专业的分镜精加工专家。你的任务是根据用户的扩充指令，将一个已有的分镜拆分成多个更详细、更丰富的分镜。

## 输出格式
必须严格按照以下JSON格式输出，只输出JSON，不要其他内容：
```json
{
  "scenes": [
    {
      "title": "细化后的分镜标题",
      "description": "画面描述（中文，比原来更详细）",
      "dialogue": "旁白或台词（中文）",
      "camera_direction": "镜头运动描述",
      "mood": "氛围",
      "duration_seconds": 5.0,
      "image_prompt": "英文图片生成prompt——描述关键帧画面，详细且视觉化",
      "video_prompt": "英文视频生成prompt——描述动态画面，包含动作、运镜、氛围"
    }
  ]
}
```

## 规则
- **角色一致性（最重要）**：如果提供了character_description，每个image_prompt和video_prompt开头必须加上这段角色描述
- 每个细化后的分镜时长约5秒（3~7秒）
- 将原始分镜的内容展开：增加细节、动作、情感层次
- image_prompt和video_prompt必须用英文
- 细化后的分镜之间要有连贯的叙事流
- 数量：一般2~5个细化分镜，根据扩充指令决定"""

ADD_SCENE_SYSTEM_PROMPT = """你是一个专业的短视频编剧。你的任务是在现有剧本的指定位置插入新的分镜。

## 输出格式
必须严格按照以下JSON格式输出，只输出JSON：
```json
{
  "scenes": [
    {
      "title": "新分镜标题",
      "description": "画面描述（中文）",
      "dialogue": "旁白或台词（中文）",
      "camera_direction": "镜头运动描述",
      "mood": "氛围",
      "duration_seconds": 5.0,
      "image_prompt": "英文图片生成prompt",
      "video_prompt": "英文视频生成prompt"
    }
  ]
}
```

## 规则
- 新分镜要与前后分镜的内容和风格保持连贯
- image_prompt和video_prompt必须用英文"""


class StoryboardRefiner:
    """分镜精加工：通过DeepSeek进行场景扩充和细化（无DeepSeek key时回退Agnes）"""

    def __init__(self, config: dict):
        try:
            ds_config = get_deepseek_config(config)
            self.api_key = ds_config["api_key"]
            self.base_url = ds_config["base_url"]
            self.model = ds_config.get("model", "deepseek-chat")
            self.provider = "deepseek"
        except ValueError:
            from .config import get_agnes_config
            agnes_config = get_agnes_config(config)
            self.api_key = agnes_config["api_key"]
            self.base_url = agnes_config["base_url"]
            self.model = agnes_config.get("text_model", "agnes-2.0-flash")
            self.provider = "agnes"
            print(f"[refine] DeepSeek Key未配置，回退使用Agnes AI ({self.model})")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        # DNS workaround for Agnes API domain
        try:
            from urllib.parse import urlparse
            from .dns_workaround import apply_global_dns_patch
            hostname = urlparse(self.base_url).hostname
            if hostname and hostname in {"apihub.agnes-ai.com"}:
                apply_global_dns_patch()
        except Exception:
            pass

        self.temperature = config.get("deepseek", {}).get("temperature", 0.8)

    def refine_scene(
        self,
        scene: Scene,
        expansion_instruction: str,
        target_count: int = 3,
        character_description: str = "",
    ) -> list[Scene]:
        """
        将一个分镜拆分成多个细化分镜
        """
        print(f"[refine] 精加工分镜: {scene.title} ({scene.id})")
        print(f"[refine] 扩充指令: {expansion_instruction}")

        scene_json = json.dumps({
            "title": scene.title,
            "description": scene.description,
            "dialogue": scene.dialogue,
            "camera_direction": scene.camera_direction,
            "mood": scene.mood,
            "duration_seconds": scene.duration_seconds,
        }, ensure_ascii=False, indent=2)

        user_prompt = f"""原始分镜：
{scene_json}

扩充指令：{expansion_instruction}

请将以上分镜拆分成约{target_count}个更详细的分镜。

角色一致性描述（所有image_prompt和video_prompt必须以此开头）：
{character_description or '(无)'}"""

        content = self._call_deepseek(REFINE_SYSTEM_PROMPT, user_prompt)
        scenes = self._parse_scenes(content, scene.id, character_description)

        if scenes:
            print(f"[refine] 精加工完成: {len(scenes)}个细化分镜")
            return scenes

        # 重试
        print("[refine] 首次解析失败，重试中...")
        content2 = self._call_deepseek(
            REFINE_SYSTEM_PROMPT,
            user_prompt + "\n\n【重要】请只输出JSON，不要包含其他内容。"
        )
        scenes2 = self._parse_scenes(content2, scene.id, character_description)
        if scenes2:
            print(f"[refine] 重试成功: {len(scenes2)}个细化分镜")
            return scenes2

        raise ValueError(f"分镜精加工失败：DeepSeek两次返回都无法解析")

    def add_scenes(
        self,
        script: Script,
        insertion_point: int,
        scene_count: int = 2,
        context: str = "",
    ) -> list[Scene]:
        """
        在剧本的指定位置插入新分镜

        Args:
            script: 当前剧本
            insertion_point: 插入位置（在此分镜之后插入）
            scene_count: 插入几个新分镜
            context: 额外上下文

        Returns:
            新插入的Scene列表
        """
        # 获取前后文
        prev_scene = None
        next_scene = None
        if 0 <= insertion_point < len(script.scenes):
            prev_scene = script.scenes[insertion_point]
        if insertion_point + 1 < len(script.scenes):
            next_scene = script.scenes[insertion_point + 1]

        prev_text = ""
        if prev_scene:
            prev_text = f"前一个分镜：{prev_scene.title} - {prev_scene.description}"
        next_text = ""
        if next_scene:
            next_text = f"后一个分镜：{next_scene.title} - {next_scene.description}"

        user_prompt = f"""{prev_text}
{next_text}

请在这两个分镜之间插入{scene_count}个新的分镜。
额外要求：{context}

新分镜要承接前一分镜的情绪和内容，平滑过渡到后一分镜。"""

        print(f"[refine] 在位置{insertion_point}后插入{scene_count}个新分镜")
        content = self._call_deepseek(ADD_SCENE_SYSTEM_PROMPT, user_prompt)
        scenes = self._parse_scenes(content, f"insert_{insertion_point}")

        if scenes:
            print(f"[refine] 插入完成: {len(scenes)}个新分镜")
            return scenes

        # 重试
        content2 = self._call_deepseek(
            ADD_SCENE_SYSTEM_PROMPT,
            user_prompt + "\n\n【重要】请只输出JSON。"
        )
        scenes2 = self._parse_scenes(content2, f"insert_{insertion_point}")
        if scenes2:
            return scenes2

        raise ValueError("插入分镜失败：DeepSeek两次返回都无法解析")

    def refine_script(
        self,
        script: Script,
        scene_index: int,
        instruction: str,
        target_count: int = 3,
    ) -> Script:
        """
        精加工剧本的某个分镜，返回新版本的剧本

        用细化后的分镜替换原分镜，生成新剧本
        """
        if scene_index < 0 or scene_index >= len(script.scenes):
            raise ValueError(f"分镜序号 {scene_index} 超出范围 (0~{len(script.scenes)-1})")

        original = script.scenes[scene_index]
        refined = self.refine_scene(
            original, instruction, target_count,
            character_description=script.character_description,
        )

        # 创建新剧本
        new_script = Script(
            title=script.title + " (精加工)",
            idea=script.idea,
            style=script.style,
            target_duration=sum(s.duration_seconds for s in script.scenes),
            refined_from=script.id,
        )

        # 重建分镜列表：保留前面 + 替换 + 保留后面
        before = script.scenes[:scene_index]
        after = script.scenes[scene_index + 1:]

        all_scenes = before + refined + after
        for i, s in enumerate(all_scenes):
            s.index = i
            s.status = "pending"  # 新剧本的分镜需要重新生成素材
            s.image_path = ""
            s.video_path = ""
            s.video_task_id = ""

        new_script.scenes = all_scenes
        new_script.target_duration = sum(s.duration_seconds for s in all_scenes)

        print(f"[refine] 新剧本: {new_script.title}, {len(all_scenes)}个分镜, "
              f"总时长≈{new_script.target_duration:.0f}秒")
        return new_script

    # ---- 内部方法 ----

    def _call_deepseek(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _parse_scenes(content: str, base_id: str, character_description: str = "") -> list[Scene]:
        """从LLM返回内容中解析Scene列表"""
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if m:
            json_str = m.group(1).strip()
        else:
            start = content.find('{')
            end = content.rfind('}')
            if start == -1 or end <= start:
                return []
            json_str = content[start:end + 1]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return []

        scenes_data = data.get("scenes", [])
        if not isinstance(scenes_data, list) or not scenes_data:
            return []

        scenes = []
        for i, sd in enumerate(scenes_data):
            img = sd.get("image_prompt", "")
            vid = sd.get("video_prompt", "")
            # 注入角色描述确保一致性
            if character_description:
                if not img.startswith(character_description):
                    img = f"{character_description}. {img}"
                if not vid.startswith(character_description):
                    vid = f"{character_description}. {vid}"

            scene = Scene(
                id=f"{base_id}_r{i}",
                index=0,
                title=sd.get("title", ""),
                description=sd.get("description", ""),
                dialogue=sd.get("dialogue", ""),
                camera_direction=sd.get("camera_direction", ""),
                mood=sd.get("mood", ""),
                duration_seconds=float(sd.get("duration_seconds", 5.0)),
                image_prompt=img,
                video_prompt=vid,
            )
            scenes.append(scene)

        return scenes
