"""LoopDetector —— 对标 DeerFlow LoopDetectionMiddleware。

滑动窗口 hash 检测重复工具调用序列。
- WARN_THRESHOLD: 出现 N 次后注入 HumanMessage 警告
- HARD_LIMIT: 出现 N 次后强制结束（剥离 tools，强制输出文本）
- WINDOW_SIZE: 最近 N 条 tool_calls 消息参与检测

注意：警告注入为 user role 消息（不能是 system），
避免 Anthropic/部分模型不支持 conversation 中途 system message 的问题。
"""
import hashlib
import json
import logging
from collections import deque

logger = logging.getLogger(__name__)

WARN_THRESHOLD = 3
HARD_LIMIT = 5
WINDOW_SIZE = 20

WARNING_MSG = (
    "[LOOP DETECTED] 你在重复调用相同工具。"
    "请停止循环，汇总当前已有结果，直接输出最终答案。"
)
HARD_STOP_MSG = (
    "[FORCED STOP] 检测到超过 5 次重复工具调用，强制结束循环。"
    "请立即输出当前已有的所有结果作为最终答案，不要再调用任何工具。"
)


class LoopDetector:

    def __init__(
        self,
        warn_threshold: int = WARN_THRESHOLD,
        hard_limit: int = HARD_LIMIT,
        window_size: int = WINDOW_SIZE,
    ):
        self._warn = warn_threshold
        self._hard = hard_limit
        self._window = window_size
        # 滑动窗口：存储最近 N 次 tool_calls 的 hash
        self._recent: deque[str] = deque(maxlen=window_size)
        # 每个 hash 的出现次数
        self._counts: dict[str, int] = {}
        self._current_hash: str = ""

    def check(self, tool_calls: list[dict]) -> int:
        """
        检测当前 tool_calls 是否构成循环。

        返回:
          0 — 正常
          1 — 警告（WARN_THRESHOLD 次）
          2 — 强制停止（HARD_LIMIT 次）
        """
        if not tool_calls:
            return 0

        h = self._hash_tool_calls(tool_calls)
        self._current_hash = h

        # 维护滑动窗口
        if len(self._recent) == self._window:
            oldest = self._recent[0]
            self._counts[oldest] = max(0, self._counts.get(oldest, 0) - 1)
        self._recent.append(h)
        self._counts[h] = self._counts.get(h, 0) + 1

        count = self._counts[h]
        if count >= self._hard:
            logger.warning(f"LoopDetector: HARD STOP (hash={h}, count={count})")
            return 2
        if count >= self._warn:
            logger.warning(f"LoopDetector: WARN (hash={h}, count={count})")
            return 1
        return 0

    def get_warning_message(self, level: int) -> str:
        """根据检测级别返回注入消息。"""
        if level >= 2:
            return HARD_STOP_MSG
        return WARNING_MSG

    def reset(self):
        self._recent.clear()
        self._counts.clear()
        self._current_hash = ""

    @staticmethod
    def _hash_tool_calls(tool_calls: list[dict]) -> str:
        """order-independent hash，对标 DeerFlow _hash_tool_calls。"""
        normalized = sorted(
            [{"name": tc.get("name", ""), "args": tc.get("args", {})}
             for tc in tool_calls],
            key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False),
        )
        raw = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()[:12]
