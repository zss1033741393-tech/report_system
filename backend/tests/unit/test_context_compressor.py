"""测试 ContextCompressor — mock LLM.complete，无网络依赖。"""

import pytest

import agent.context_compressor as cc
from agent.context_compressor import (
    MSG_LIMIT,
    TOKEN_LIMIT,
    compress,
    should_compress,
)
from tests.conftest import FakeLLMService


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def _build_msgs(n: int, role="user") -> list[dict]:
    """生成 n 条消息（交替 user/assistant）。"""
    roles = ["user", "assistant"]
    return [_msg(roles[i % 2], f"消息内容_{i}") for i in range(n)]


class TestShouldCompress:

    def test_below_limits_no_compress(self):
        msgs = [_msg("system", "sys")] + _build_msgs(10)
        assert should_compress(msgs) is False

    def test_exceed_msg_limit_triggers(self):
        msgs = [_msg("system", "sys")] + _build_msgs(MSG_LIMIT + 1)
        assert should_compress(msgs) is True

    def test_exceed_token_limit_triggers(self):
        # 每条约 1000 字，55 条 → ~55000/3.3 ≈ 16666 估算 token > TOKEN_LIMIT=15000
        long_msgs = [_msg("user", "x" * 1000) for _ in range(55)]
        assert should_compress(long_msgs) is True

    def test_system_msg_excluded_from_count(self):
        # 只有 system + 5 条消息，不超过限制
        msgs = [_msg("system", "s" * 5000)] + _build_msgs(5)
        assert should_compress(msgs) is False

    def test_exactly_at_msg_limit_no_compress(self):
        msgs = _build_msgs(MSG_LIMIT)
        assert should_compress(msgs) is False


class TestCompress:

    @pytest.mark.asyncio
    async def test_short_history_unchanged(self):
        """消息数 <= KEEP_RECENT 时不压缩，直接返回原列表。"""
        msgs = [_msg("system", "sys")] + _build_msgs(5)
        fake_llm = FakeLLMService([])
        result = await compress(msgs, fake_llm)
        assert result == msgs

    @pytest.mark.asyncio
    async def test_compress_reduces_message_count(self):
        """压缩后消息数少于原始消息数。"""
        msgs = [_msg("system", "sys")] + _build_msgs(30)
        fake_llm = FakeLLMService([[{"content": "摘要：用户询问了30个问题"}]])
        result = await compress(msgs, fake_llm)
        assert len(result) < len(msgs)

    @pytest.mark.asyncio
    async def test_compress_preserves_system_msg(self):
        """压缩后 system message 保留在首位。"""
        system_content = "你是专业分析助手"
        msgs = [_msg("system", system_content)] + _build_msgs(30)
        fake_llm = FakeLLMService([[{"content": "历史摘要"}]])
        result = await compress(msgs, fake_llm)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == system_content

    @pytest.mark.asyncio
    async def test_compress_injects_summary_as_human(self):
        """摘要注入为 user（HumanMessage），不是 system。"""
        msgs = [_msg("system", "sys")] + _build_msgs(30)
        fake_llm = FakeLLMService([[{"content": "历史摘要内容"}]])
        result = await compress(msgs, fake_llm)
        # 找到摘要注入的消息
        summary_msgs = [m for m in result if "[系统：" in (m.get("content") or "")]
        assert len(summary_msgs) == 1
        assert summary_msgs[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_compress_keeps_recent_messages(self):
        """压缩后保留最近 KEEP_RECENT 条消息。"""
        msgs = [_msg("system", "sys")] + _build_msgs(30)
        recent_contents = [m["content"] for m in msgs[-cc.KEEP_RECENT:]]
        fake_llm = FakeLLMService([[{"content": "摘要"}]])
        result = await compress(msgs, fake_llm)
        result_contents = [m["content"] for m in result]
        for content in recent_contents:
            assert content in result_contents, f"最近消息 '{content}' 未被保留"

    @pytest.mark.asyncio
    async def test_compress_llm_failure_returns_original(self):
        """LLM 摘要失败时，返回原始消息（不抛异常）。"""
        msgs = [_msg("system", "sys")] + _build_msgs(30)

        class FailingLLM:
            async def complete(self, messages, config=None):
                raise RuntimeError("LLM 不可用")

        result = await compress(msgs, FailingLLM())
        assert result == msgs

    @pytest.mark.asyncio
    async def test_compress_no_system_msg(self):
        """没有 system message 时也能正确压缩。"""
        msgs = _build_msgs(30)
        fake_llm = FakeLLMService([[{"content": "摘要"}]])
        result = await compress(msgs, fake_llm)
        assert len(result) < len(msgs)
        # 第一条不应是 system
        assert result[0]["role"] != "system"


class TestFindSafeSplit:

    def test_split_avoids_tool_message_start(self):
        """分割点不应落在 tool message 之前（避免孤立 tool 消息）。"""
        msgs = [
            _msg("user", "问题"),
            _msg("assistant", "工具调用"),
            {"role": "tool", "content": "工具结果", "tool_call_id": "c1"},
            _msg("user", "继续"),
        ]
        from agent.context_compressor import _find_safe_split
        # 目标分割点在 index 2（tool message），应向前移动
        idx = _find_safe_split(msgs, 2)
        assert msgs[idx]["role"] != "tool"
