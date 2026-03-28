"""循环检测器 —— 对标 DeerFlow LoopDetectionMiddleware。

使用滑动窗口 + hash 检测 LLM 是否陷入重复调用同一工具组合的循环。
注意：警告注入为 HumanMessage（不是 SystemMessage），因为部分模型
不支持 conversation 中途插入 SystemMessage。
"""

import hashlib
import json
from collections import deque


class LoopDetector:
    """检测 ReAct 循环中的重复工具调用。"""

    WARN_THRESHOLD = 3   # 同一工具组合出现 3 次：注入警告
    HARD_LIMIT = 5       # 出现 5 次：强制停止
    WINDOW_SIZE = 20     # 滑动窗口大小

    WARNING_MSG = (
        "[LOOP DETECTED] 你在重复调用相同的工具组合，没有取得新进展。"
        "请停止重复调用，基于当前已有的结果直接输出最终答案给用户。"
    )

    HARD_STOP_MSG = (
        "[FORCED STOP] 检测到严重循环，强制终止工具调用。"
        "请立即基于当前已有信息输出最终答案，不要再调用任何工具。"
    )

    def __init__(self):
        self._window: deque[str] = deque(maxlen=self.WINDOW_SIZE)
        self._hash_counts: dict[str, int] = {}

    def check(self, tool_calls: list[dict]) -> tuple[str, bool]:
        """
        检查本轮工具调用是否形成循环。

        Args:
            tool_calls: LLM 返回的 tool_calls 列表，每项包含 name 和 args

        Returns:
            (warning_message, should_force_stop)
            warning_message 为空字符串表示无循环
        """
        h = self._hash_tool_calls(tool_calls)
        self._window.append(h)

        # 统计当前滑动窗口内的出现次数
        count = sum(1 for item in self._window if item == h)
        self._hash_counts[h] = count

        if count >= self.HARD_LIMIT:
            return self.HARD_STOP_MSG, True
        elif count >= self.WARN_THRESHOLD:
            return self.WARNING_MSG, False

        return "", False

    def reset(self):
        """重置检测状态（新会话开始时调用）。"""
        self._window.clear()
        self._hash_counts.clear()

    @staticmethod
    def _hash_tool_calls(tool_calls: list[dict]) -> str:
        """
        生成工具调用的 order-independent hash。
        相同的工具集合（不同顺序）视为同一个组合。
        """
        normalized = sorted(
            [
                {
                    "name": tc.get("name", tc.get("function", {}).get("name", "")),
                    "args": tc.get("args", tc.get("function", {}).get("arguments", "")),
                }
                for tc in tool_calls
            ],
            key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False),
        )
        raw = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()[:12]
