"""循环检测器 —— 对标 DeerFlow LoopDetectionMiddleware。

滑动窗口检测重复工具调用组合：
  WARN_THRESHOLD = 3   → 注入警告 HumanMessage
  HARD_LIMIT = 5       → 强制停止（返回 "stop" 信号）
  WINDOW_SIZE = 20     → 滑动窗口大小

注意：警告/停止消息注入为 HumanMessage（不是 SystemMessage），
兼容 Anthropic 不允许对话中途插入 SystemMessage 的限制（DeerFlow issue #1299）。
"""

import hashlib
import json
import logging
from collections import deque

logger = logging.getLogger(__name__)

WARN_THRESHOLD = 3
HARD_LIMIT = 5
WINDOW_SIZE = 20

WARN_MESSAGE = (
    "[检测到循环] 你正在重复调用相同的工具组合，这表明当前方法无法解决问题。"
    "请停止重复调用，基于已有结果输出最终答案，即使结果不完整。"
)

STOP_MESSAGE = (
    "[强制停止] 已检测到严重循环（相同工具调用出现 5 次以上）。"
    "请立即停止工具调用，输出当前已有的结果作为最终答案。"
)


def _hash_tool_calls(tool_calls: list[dict]) -> str:
    """顺序无关的工具调用组合哈希。"""
    normalized = sorted(
        [{"name": tc.get("name", ""), "args": tc.get("arguments", {})} for tc in tool_calls],
        key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False),
    )
    raw = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


class LoopDetector:
    def __init__(self):
        self._window: deque[str] = deque(maxlen=WINDOW_SIZE)
        self._counts: dict[str, int] = {}

    def check(self, tool_calls: list[dict]) -> tuple[str, str | None]:
        """
        检查当前工具调用是否触发循环检测。

        返回：
          ("ok", None)       → 正常
          ("warn", message)  → 注入警告，继续执行
          ("stop", message)  → 强制停止
        """
        h = _hash_tool_calls(tool_calls)
        self._window.append(h)
        self._counts[h] = self._counts.get(h, 0) + 1
        count = self._counts[h]

        if count >= HARD_LIMIT:
            names = [tc.get("name", "?") for tc in tool_calls]
            logger.warning(f"LoopDetector: HARD STOP, tool_calls={names}, count={count}")
            return "stop", STOP_MESSAGE

        if count >= WARN_THRESHOLD:
            names = [tc.get("name", "?") for tc in tool_calls]
            logger.warning(f"LoopDetector: WARN, tool_calls={names}, count={count}")
            return "warn", WARN_MESSAGE

        return "ok", None

    def reset(self):
        self._window.clear()
        self._counts.clear()
