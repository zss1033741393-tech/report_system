"""Memory 系统 —— 跨对话记忆（对标 DeerFlow MemoryMiddleware）。

写路径（异步，不阻塞响应）：
  每轮 ReAct 结束后 → MemoryUpdater.enqueue(session_id, messages)
  后台 worker (debounce 30s) → LLM 提取 facts → MemoryStorage.merge()

读路径（每次构建 system_prompt 时）：
  memory = MemoryStorage.load(session_id)
  block = format_memory_for_prompt(memory)
  system_prompt = base_prompt + block
"""
from agent.memory.storage import MemoryStorage
from agent.memory.updater import MemoryUpdater
from agent.memory.prompt import format_memory_for_prompt

__all__ = ["MemoryStorage", "MemoryUpdater", "format_memory_for_prompt"]
