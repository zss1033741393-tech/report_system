"""测试 LoopDetector — 纯同步，零外部依赖。"""

import pytest

from agent.loop_detector import HARD_LIMIT, WARN_THRESHOLD, LoopDetector


def _call(name: str, args: dict | None = None) -> dict:
    return {"name": name, "arguments": args or {}}


class TestLoopDetectorBasic:

    def test_ok_no_repeat(self):
        """首次调用，不同工具组合 → 始终返回 ok。"""
        ld = LoopDetector()
        status, msg = ld.check([_call("search_skill", {"q": "a"})])
        assert status == "ok"
        assert msg is None

    def test_different_tools_no_trigger(self):
        """不同工具组合每次不同 → 不触发。"""
        ld = LoopDetector()
        for i in range(10):
            status, _ = ld.check([_call(f"tool_{i}")])
            assert status == "ok"

    def test_warn_at_threshold(self):
        """相同工具调用达到 WARN_THRESHOLD 次 → 返回 warn。"""
        ld = LoopDetector()
        tool_calls = [_call("execute_data", {"sid": "x"})]
        for i in range(WARN_THRESHOLD - 1):
            status, _ = ld.check(tool_calls)
            assert status == "ok", f"第 {i+1} 次不应触发 warn"
        status, msg = ld.check(tool_calls)
        assert status == "warn"
        assert msg is not None and len(msg) > 0

    def test_stop_at_hard_limit(self):
        """相同工具调用达到 HARD_LIMIT 次 → 返回 stop。"""
        ld = LoopDetector()
        tool_calls = [_call("render_report")]
        for i in range(HARD_LIMIT - 1):
            ld.check(tool_calls)
        status, msg = ld.check(tool_calls)
        assert status == "stop"
        assert msg is not None and len(msg) > 0

    def test_hash_order_independent(self):
        """[A, B] 和 [B, A] 应视为相同组合（顺序无关哈希）。"""
        ld = LoopDetector()
        calls_ab = [_call("tool_a"), _call("tool_b")]
        calls_ba = [_call("tool_b"), _call("tool_a")]

        # 两种顺序交替调用 WARN_THRESHOLD 次，应触发 warn
        for i in range(WARN_THRESHOLD):
            if i % 2 == 0:
                ld.check(calls_ab)
            else:
                ld.check(calls_ba)

        # 再调一次（超过阈值）
        status, _ = ld.check(calls_ab)
        assert status in ("warn", "stop"), "顺序无关哈希应将 [A,B] 和 [B,A] 视为同一模式"

    def test_reset_clears_counts(self):
        """reset() 后计数从零重新开始。"""
        ld = LoopDetector()
        tool_calls = [_call("some_tool")]
        for _ in range(HARD_LIMIT):
            ld.check(tool_calls)

        ld.reset()

        # reset 后应从零开始，不立即触发
        for i in range(WARN_THRESHOLD - 1):
            status, _ = ld.check(tool_calls)
            assert status == "ok", f"reset 后第 {i+1} 次不应触发"

    def test_multiple_different_tools_independent_counts(self):
        """不同工具的计数互相独立。"""
        ld = LoopDetector()
        tool_a = [_call("tool_a")]
        tool_b = [_call("tool_b")]

        # tool_a 调用 WARN_THRESHOLD 次
        for _ in range(WARN_THRESHOLD - 1):
            ld.check(tool_a)
        status_a, _ = ld.check(tool_a)
        assert status_a == "warn"

        # tool_b 只调用 1 次，不应触发
        status_b, _ = ld.check(tool_b)
        assert status_b == "ok"

    def test_warn_before_stop_sequence(self):
        """按顺序：ok...ok → warn → warn... → stop。"""
        ld = LoopDetector()
        tool_calls = [_call("loop_tool")]

        results = []
        for _ in range(HARD_LIMIT + 2):
            s, _ = ld.check(tool_calls)
            results.append(s)

        # WARN_THRESHOLD 之前全是 ok
        assert all(s == "ok" for s in results[:WARN_THRESHOLD - 1])
        # WARN_THRESHOLD 到 HARD_LIMIT 之前是 warn
        assert all(s == "warn" for s in results[WARN_THRESHOLD - 1:HARD_LIMIT - 1])
        # HARD_LIMIT 及以后是 stop
        assert all(s == "stop" for s in results[HARD_LIMIT - 1:])
