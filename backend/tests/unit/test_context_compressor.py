"""单元测试：ContextCompressor —— 上下文压缩。

覆盖：
  - should_compress() 阈值判断
  - compress() 保留策略（system + tail）
  - 安全分割边界（不切断 tool_call/tool_result pair）
  - LLM 调用失败时无损降级（返回原列表）
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from agent.context_compressor import ContextCompressor, MSG_THRESHOLD, TOKEN_THRESHOLD, KEEP_TAIL


def _sys():
    return {"role": "system", "content": "你是助手"}


def _user(content="用户消息"):
    return {"role": "user", "content": content}


def _assistant(content="回答"):
    return {"role": "assistant", "content": content}


def _assistant_with_tools(tools: list):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": f"id_{t}", "type": "function",
                        "function": {"name": t, "arguments": "{}"}} for t in tools],
    }


def _tool_result(tool_call_id="id_tool", content="结果"):
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def _make_llm(summary="压缩后的摘要"):
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=summary)
    return llm


class TestShouldCompress:
    def test_few_messages_no_compress(self):
        compressor = ContextCompressor(_make_llm())
        msgs = [_sys()] + [_user() for _ in range(10)]
        assert compressor.should_compress(msgs) is False

    def test_over_msg_threshold_triggers(self):
        compressor = ContextCompressor(_make_llm())
        msgs = [_sys()] + [_user() for _ in range(MSG_THRESHOLD + 1)]
        assert compressor.should_compress(msgs) is True

    def test_over_token_threshold_triggers(self):
        compressor = ContextCompressor(_make_llm())
        # token 估算: len(content)//3 + 1，需要 content > TOKEN_THRESHOLD*3 才超过阈值
        long_content = "A" * (TOKEN_THRESHOLD * 4)
        msgs = [_sys(), _user(long_content)]
        assert compressor.should_compress(msgs) is True

    def test_exactly_at_threshold_no_compress(self):
        compressor = ContextCompressor(_make_llm())
        # 实现使用 > MSG_THRESHOLD，所以恰好 MSG_THRESHOLD 条时不触发
        msgs = [_sys()] + [_user() for _ in range(MSG_THRESHOLD - 1)]
        # 共 MSG_THRESHOLD 条，len == 60，60 > 60 为 False
        assert compressor.should_compress(msgs) is False


class TestCompressPreservesSystemAndTail:
    @pytest.mark.asyncio
    async def test_system_message_preserved(self):
        compressor = ContextCompressor(_make_llm())
        msgs = [_sys()] + [_user(f"消息{i}") for i in range(MSG_THRESHOLD + 5)]
        result = await compressor.compress(msgs)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "你是助手"

    @pytest.mark.asyncio
    async def test_tail_messages_preserved(self):
        """末尾 KEEP_TAIL 条消息必须原样保留。"""
        compressor = ContextCompressor(_make_llm())
        tail_msgs = [_user(f"尾部消息{i}") for i in range(KEEP_TAIL)]
        msgs = [_sys()] + [_user(f"旧消息{i}") for i in range(30)] + tail_msgs
        result = await compressor.compress(msgs)
        # 检查尾部消息都在结果里
        result_contents = [m.get("content") for m in result]
        for tm in tail_msgs:
            assert tm["content"] in result_contents

    @pytest.mark.asyncio
    async def test_compressed_has_summary_message(self):
        """压缩结果中应包含一条 user role 的摘要消息。"""
        compressor = ContextCompressor(_make_llm("这是摘要"))
        msgs = [_sys()] + [_user(f"消息{i}") for i in range(30)]
        result = await compressor.compress(msgs)
        summaries = [m for m in result if "摘要" in (m.get("content") or "")]
        assert len(summaries) >= 1

    @pytest.mark.asyncio
    async def test_result_shorter_than_original(self):
        compressor = ContextCompressor(_make_llm())
        msgs = [_sys()] + [_user(f"消息{i}") for i in range(30)]
        result = await compressor.compress(msgs)
        assert len(result) < len(msgs)


class TestSafeSplitBoundary:
    @pytest.mark.asyncio
    async def test_does_not_cut_tool_call_pair(self):
        """不在 tool_call → tool_result pair 中间切割。"""
        compressor = ContextCompressor(_make_llm())
        # 构造一个 tool_call + tool_result pair 在末尾附近
        body = [_user(f"消息{i}") for i in range(25)]
        # 在位置 20 插入一个 tool_call pair
        body.insert(20, _assistant_with_tools(["search_skill"]))
        body.insert(21, _tool_result("id_search_skill", "搜索结果"))
        msgs = [_sys()] + body
        result = await compressor.compress(msgs)
        # 验证 tool_result 不会作为压缩边界：每个 tool_result 前必须有对应的 tool_calls
        tool_roles = [(i, m["role"]) for i, m in enumerate(result)]
        for i, (idx, role) in enumerate(tool_roles):
            if role == "tool":
                # 前面必须有 assistant with tool_calls
                prev_roles = [r for _, r in tool_roles[:i]]
                assert "assistant" in prev_roles


class TestCompressFallback:
    @pytest.mark.asyncio
    async def test_llm_failure_returns_original(self):
        """LLM 调用失败时，返回原始消息列表，不抛异常。"""
        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("LLM 不可用"))
        compressor = ContextCompressor(llm)
        msgs = [_sys()] + [_user(f"消息{i}") for i in range(30)]
        result = await compressor.compress(msgs)
        assert result == msgs  # 原样返回

    @pytest.mark.asyncio
    async def test_too_few_messages_skip_compress(self):
        """消息太少（≤ 2）时直接返回，不调用 LLM。"""
        llm = _make_llm()
        compressor = ContextCompressor(llm)
        msgs = [_sys(), _user("一条消息")]
        result = await compressor.compress(msgs)
        llm.complete.assert_not_called()
        assert result == msgs
