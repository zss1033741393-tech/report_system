"""单元测试：LoopDetector —— 循环工具调用检测。

覆盖：
  - 正常状态（返回 0）
  - WARN_THRESHOLD 触发（返回 1）
  - HARD_LIMIT 触发（返回 2）
  - reset() 重置计数
  - order-independent hash（相同工具集，不同顺序）
  - 边界：空 tool_calls
"""
import pytest
from agent.loop_detector import LoopDetector, WARN_THRESHOLD, HARD_LIMIT


def _tc(name: str, args: dict = None) -> dict:
    return {"id": f"id_{name}", "name": name, "args": args or {}}


class TestLoopDetectorNormal:
    def test_first_call_returns_zero(self):
        ld = LoopDetector()
        assert ld.check([_tc("get_session_status")]) == 0

    def test_different_tools_each_call_returns_zero(self):
        ld = LoopDetector()
        tools = ["get_session_status", "search_skill", "execute_data", "render_report"]
        for t in tools:
            assert ld.check([_tc(t)]) == 0

    def test_empty_tool_calls_returns_zero(self):
        ld = LoopDetector()
        assert ld.check([]) == 0


class TestLoopDetectorWarn:
    def test_warn_threshold_triggered(self):
        ld = LoopDetector()
        call = [_tc("search_skill", {"query": "fgOTN"})]
        # 前 WARN_THRESHOLD-1 次 → 0
        for _ in range(WARN_THRESHOLD - 1):
            assert ld.check(call) == 0
        # 第 WARN_THRESHOLD 次 → 1
        assert ld.check(call) == 1

    def test_warn_message_not_empty(self):
        ld = LoopDetector()
        msg = ld.get_warning_message(1)
        assert len(msg) > 0
        assert "循环" in msg or "LOOP" in msg.upper()


class TestLoopDetectorHardStop:
    def test_hard_limit_triggered(self):
        ld = LoopDetector()
        call = [_tc("execute_data")]
        for _ in range(HARD_LIMIT - 1):
            ld.check(call)
        assert ld.check(call) == 2

    def test_hard_stop_message_not_empty(self):
        ld = LoopDetector()
        msg = ld.get_warning_message(2)
        assert "强制" in msg or "FORCED" in msg.upper() or "STOP" in msg.upper()


class TestLoopDetectorReset:
    def test_reset_clears_counts(self):
        ld = LoopDetector()
        call = [_tc("clip_outline")]
        for _ in range(HARD_LIMIT):
            ld.check(call)
        ld.reset()
        # 重置后重新计数
        assert ld.check(call) == 0

    def test_reset_then_warn_again(self):
        ld = LoopDetector()
        call = [_tc("inject_params")]
        for _ in range(WARN_THRESHOLD):
            ld.check(call)
        ld.reset()
        for _ in range(WARN_THRESHOLD - 1):
            assert ld.check(call) == 0
        assert ld.check(call) == 1


class TestLoopDetectorHash:
    def test_order_independent_hash(self):
        """相同工具集，调用顺序不同，hash 应相等 → 累计相同。"""
        ld = LoopDetector()
        call_ab = [_tc("tool_a"), _tc("tool_b")]
        call_ba = [_tc("tool_b"), _tc("tool_a")]
        # 连续调用同一集合（不同顺序）
        for _ in range(WARN_THRESHOLD - 1):
            ld.check(call_ab)
        # 顺序反转但视为同一序列
        assert ld.check(call_ba) == 1

    def test_different_args_same_tool_different_hash(self):
        """相同工具名但不同 args → 视为不同调用，不触发循环。"""
        ld = LoopDetector()
        for i in range(HARD_LIMIT + 2):
            result = ld.check([_tc("search_skill", {"query": f"query_{i}"})])
            assert result == 0  # 每次 args 不同，hash 不同，不累积

    def test_same_name_same_args_triggers_loop(self):
        """相同工具 + 相同 args → 触发循环检测。"""
        ld = LoopDetector()
        call = [_tc("search_skill", {"query": "容量分析", "session_id": "s1"})]
        for _ in range(WARN_THRESHOLD - 1):
            ld.check(call)
        assert ld.check(call) == 1
