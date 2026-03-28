"""Memory 更新器 —— 异步调用 LLM 提取对话中的记忆并写入存储。

设计原则：
  - 异步执行，不阻塞对话响应
  - LLM 提取增量信息，不覆盖已有高置信度 facts
  - 写入失败静默降级（记录日志，不影响主流程）
"""

import json
import logging

from agent.memory.prompt import MEMORY_EXTRACT_PROMPT
from agent.memory.storage import MemoryStorage
from llm.config import LLMConfig
from llm.service import LLMService

logger = logging.getLogger(__name__)

MAX_FACTS = 100
FACT_CONFIDENCE_THRESHOLD = 0.7   # 低于此置信度的 fact 不写入


class MemoryUpdater:
    """异步 Memory 更新器。"""

    def __init__(self, llm_service: LLMService, storage: MemoryStorage):
        self._llm = llm_service
        self._storage = storage

    async def update(self, conversation: list[dict]) -> bool:
        """
        从对话片段中提取记忆并增量更新存储。

        Args:
            conversation: [{"role": "user/assistant", "content": "..."}] 格式的消息列表

        Returns:
            是否成功更新（失败时静默降级，返回 False）
        """
        if not conversation:
            return False

        current_memory = self._storage.load()
        conversation_text = self._format_conversation(conversation)

        prompt = MEMORY_EXTRACT_PROMPT.format(
            current_memory_json=json.dumps(current_memory, ensure_ascii=False, indent=2),
            conversation=conversation_text,
        )

        try:
            result = await self._call_llm(prompt)
        except Exception as e:
            logger.warning(f"Memory LLM 提取失败: {e}")
            return False

        if not result:
            return False

        return self._apply_update(current_memory, result)

    def _apply_update(self, current: dict, extracted: dict) -> bool:
        """将 LLM 提取结果增量合并到当前 memory 并写入。"""
        try:
            # 更新 user context（仅覆盖非空字段）
            for section in ("workContext", "topOfMind"):
                new_summary = (
                    extracted.get("user", {})
                    .get(section, {})
                    .get("summary", "")
                    .strip()
                )
                if new_summary:
                    current.setdefault("user", {})[section] = {
                        "summary": new_summary,
                        "updatedAt": self._now(),
                    }

            # 更新 history（仅覆盖非空字段）
            for section in ("recentMonths",):
                new_summary = (
                    extracted.get("history", {})
                    .get(section, {})
                    .get("summary", "")
                    .strip()
                )
                if new_summary:
                    current.setdefault("history", {})[section] = {
                        "summary": new_summary,
                        "updatedAt": self._now(),
                    }

            # 追加高置信度 facts
            new_facts = [
                f for f in extracted.get("facts", [])
                if f.get("confidence", 0) >= FACT_CONFIDENCE_THRESHOLD
                and f.get("content", "").strip()
            ]

            if new_facts:
                self._storage.add_facts(new_facts, MAX_FACTS)
            else:
                self._storage.atomic_update(current)

            logger.info(f"Memory 更新完成，新增 {len(new_facts)} 条 facts")
            return True

        except Exception as e:
            logger.error(f"Memory 合并写入失败: {e}")
            return False

    async def _call_llm(self, prompt: str) -> dict | None:
        """调用 LLM 提取 memory，返回解析后的 dict。"""
        messages = [{"role": "user", "content": prompt}]
        config = LLMConfig(
            temperature=0.3,
            max_tokens=1000,
            extra_payload={"enable_thinking": False},
        )
        result = await self._llm.complete_full(messages, config)
        content = result.get("content", "").strip()

        if not content:
            return None

        # 尝试解析 JSON（可能有 markdown 包裹）
        return self._parse_json_safe(content)

    @staticmethod
    def _parse_json_safe(text: str) -> dict | None:
        """安全解析 JSON，处理 markdown 代码块包裹的情况。"""
        import re
        # 去掉 ```json ... ``` 包裹
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if match:
            text = match.group(1)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取第一个 { ... } 对象
            match = re.search(r"\{[\s\S]+\}", text)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
            logger.warning(f"Memory JSON 解析失败: {text[:200]}")
            return None

    @staticmethod
    def _format_conversation(messages: list[dict]) -> str:
        """将消息列表格式化为文本，便于 LLM 理解。"""
        lines = []
        for m in messages:
            role = "用户" if m.get("role") == "user" else "助手"
            content = str(m.get("content", ""))
            # 截断超长内容（避免超过 LLM context）
            if len(content) > 500:
                content = content[:500] + "…"
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _now() -> str:
        from datetime import datetime
        return datetime.utcnow().isoformat() + "Z"
