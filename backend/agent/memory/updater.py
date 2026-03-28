"""Memory Updater —— 异步后台 LLM 提取，对标 DeerFlow MemoryMiddleware 的写路径。

设计：
- run_in_background() 启动后台 asyncio Task
- debounce 30s：同一 session 在 30s 内多次触发只执行一次
- LLM 提取后调用 MemoryStorage.merge() 原子更新
- 提取失败不影响主流程（静默 warning）
"""
import asyncio
import json
import logging
from typing import Optional

from agent.memory.prompt import EXTRACT_PROMPT
from agent.memory.storage import MemoryStorage

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 30
MAX_CONV_CHARS = 6000   # 提取输入最大字符数（避免 LLM 超限）


class MemoryUpdater:

    def __init__(self, llm_service, config, storage: MemoryStorage):
        self._llm = llm_service
        self._config = config
        self._storage = storage
        # {session_id: asyncio.Task}
        self._pending: dict[str, asyncio.Task] = {}

    def enqueue(self, session_id: str, messages: list[dict]):
        """将本轮对话加入异步提取队列（debounce 30s）。

        如果同一 session 已有 pending task，先取消旧的，再创建新的。
        """
        # 取消旧 task
        old_task = self._pending.get(session_id)
        if old_task and not old_task.done():
            old_task.cancel()

        # 创建新 task（带 debounce）
        task = asyncio.create_task(
            self._debounced_update(session_id, messages)
        )
        self._pending[session_id] = task

        def _cleanup(t):
            if self._pending.get(session_id) is t:
                del self._pending[session_id]

        task.add_done_callback(_cleanup)

    async def _debounced_update(self, session_id: str, messages: list[dict]):
        """等待 debounce 时间后执行提取。"""
        await asyncio.sleep(DEBOUNCE_SECONDS)
        try:
            await self._extract_and_save(session_id, messages)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Memory update failed ({session_id}): {e}")

    async def _extract_and_save(self, session_id: str, messages: list[dict]):
        """调用 LLM 提取记忆并合并保存。"""
        conversation_text = _format_conversation(messages)
        if not conversation_text.strip():
            return

        current_memory = self._storage.load(session_id)
        current_memory_str = json.dumps(current_memory, ensure_ascii=False, indent=2)

        prompt = EXTRACT_PROMPT.format(
            conversation=conversation_text[:MAX_CONV_CHARS],
            current_memory=current_memory_str[:1000],
        )

        try:
            raw = await self._llm.complete(
                [{"role": "user", "content": prompt}],
                self._config,
            )
            new_memory = self._llm._parse_json(raw)
        except Exception as e:
            logger.warning(f"Memory LLM extraction failed ({session_id}): {e}")
            return

        if not isinstance(new_memory, dict):
            return

        merged = self._storage.merge(session_id, new_memory)
        facts_count = len(merged.get("facts", []))
        logger.info(f"Memory updated ({session_id}): {facts_count} facts")


def _format_conversation(messages: list[dict]) -> str:
    """将消息列表格式化为可读文本，供 LLM 提取。"""
    parts = []
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content") or ""
        if role == "tool":
            continue   # 跳过工具结果，避免噪音
        if m.get("tool_calls"):
            tc_names = [tc.get("name", "?") for tc in (m.get("tool_calls") or [])]
            parts.append(f"[助手] 调用工具: {', '.join(tc_names)}")
        elif role == "user":
            parts.append(f"[用户] {str(content)[:500]}")
        elif role == "assistant":
            parts.append(f"[助手] {str(content)[:500]}")
    return "\n".join(parts)
