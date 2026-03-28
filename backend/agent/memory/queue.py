"""Memory 队列 —— 异步防抖更新队列。

每轮对话结束后，将消息入队；后台 worker 以 debounce 30s 触发 LLM 提取，
确保不阻塞对话响应，且高频对话不会产生过多 LLM 调用。
"""

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 30    # 入队后等待 N 秒再触发（防抖）
MAX_MESSAGES_PER_SESSION = 20   # 每次提取最多取最近 N 条消息


class MemoryQueue:
    """
    会话级防抖 Memory 更新队列。

    每个 session_id 独立计时，入队后 DEBOUNCE_SECONDS 秒内无新消息则触发更新。
    """

    def __init__(self, updater):
        """
        Args:
            updater: MemoryUpdater 实例
        """
        self._updater = updater
        # session_id → 消息列表
        self._pending: dict[str, list[dict]] = defaultdict(list)
        # session_id → asyncio.Task（防抖定时器）
        self._timers: dict[str, asyncio.Task] = {}

    def enqueue(self, session_id: str, messages: list[dict]):
        """
        将本轮对话消息入队，重置该会话的防抖定时器。

        Args:
            session_id: 会话 ID
            messages: 本轮新增消息列表（user + assistant），OpenAI dict 格式
        """
        # 追加消息，保留最近 N 条
        self._pending[session_id].extend(messages)
        if len(self._pending[session_id]) > MAX_MESSAGES_PER_SESSION:
            self._pending[session_id] = self._pending[session_id][-MAX_MESSAGES_PER_SESSION:]

        # 取消旧定时器，重置防抖
        old_task = self._timers.get(session_id)
        if old_task and not old_task.done():
            old_task.cancel()

        # 启动新定时器
        self._timers[session_id] = asyncio.create_task(
            self._delayed_update(session_id)
        )

    def enqueue_sync(self, session_id: str, messages: list[dict]):
        """
        同步安全版本的入队（在非 async 上下文中调用）。
        内部检测是否有运行中的 event loop，有则 schedule，无则直接忽略（降级）。
        """
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self.enqueue, session_id, messages)
        except RuntimeError:
            # 无运行中的 event loop，静默忽略（不影响主流程）
            logger.debug(f"Memory enqueue skipped (no event loop): {session_id}")

    async def _delayed_update(self, session_id: str):
        """防抖定时器：等待 DEBOUNCE_SECONDS 后触发 LLM 提取。"""
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            return  # 被新消息取消，正常退出

        messages = self._pending.pop(session_id, [])
        self._timers.pop(session_id, None)

        if not messages:
            return

        logger.info(f"[Memory] 触发更新: session={session_id}, messages={len(messages)}")
        try:
            await self._updater.update(messages)
        except Exception as e:
            logger.warning(f"[Memory] 后台更新失败 (session={session_id}): {e}")

    def flush_all(self):
        """立即取消所有定时器（服务关闭时调用）。"""
        for task in self._timers.values():
            if not task.done():
                task.cancel()
        self._timers.clear()
        self._pending.clear()
