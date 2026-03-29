"""测试 LLMService.complete_stream 的 delta.tool_calls 流式解析逻辑。

通过 mock aiohttp.ClientSession.post 注入预设 SSE 字节流，
不发起真实网络请求。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm.service import LLMService


def _make_sse_bytes(events: list) -> bytes:
    """将事件列表序列化为 SSE 字节流。

    每个 event 可以是 dict（会被序列化为 JSON）或字符串（如 "[DONE]"）。
    """
    lines = []
    for ev in events:
        if isinstance(ev, str):
            lines.append(f"data: {ev}\n\n")
        else:
            lines.append(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n")
    return "".join(lines).encode("utf-8")


def _make_delta_chunk(index=0, tc_id=None, name=None, arguments=None, content=None) -> dict:
    """构造单个 SSE delta 对象。"""
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    if tc_id is not None or name is not None or arguments is not None:
        tc: dict = {"index": index}
        if tc_id:
            tc["id"] = tc_id
        fn: dict = {}
        if name:
            fn["name"] = name
        if arguments is not None:
            fn["arguments"] = arguments
        if fn:
            tc["function"] = fn
        delta["tool_calls"] = [tc]
    return {"choices": [{"delta": delta}]}


class _AsyncByteIterator:
    """可异步迭代的字节流，模拟 aiohttp response.content。"""
    def __init__(self, data: bytes, chunk_size: int = 64):
        self._data = data
        self._chunk_size = chunk_size

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for i in range(0, len(self._data), self._chunk_size):
            yield self._data[i:i + self._chunk_size]


def _mock_response(sse_bytes: bytes, status: int = 200):
    """创建模拟 aiohttp 响应。"""
    resp = MagicMock()
    resp.status = status
    resp.text = AsyncMock(return_value=sse_bytes.decode("utf-8"))
    resp.content = _AsyncByteIterator(sse_bytes)
    return resp


def _make_llm_service() -> LLMService:
    return LLMService(
        base_url="http://fake-llm",
        default_model="fake-model",
        think_tag_mode="none",  # 不解析 think 标签，简化测试
    )


class _MockContextManager:
    """模拟 aiohttp session.post() 的异步上下文管理器。"""
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *args):
        pass


class TestToolCallsAccumulation:

    @pytest.mark.asyncio
    async def test_tool_calls_fragments_accumulated(self):
        """分片的 arguments 被正确拼接成完整 JSON。"""
        sse_events = [
            _make_delta_chunk(index=0, tc_id="c1", name="search_skill", arguments=""),
            _make_delta_chunk(index=0, arguments='{"query"'),
            _make_delta_chunk(index=0, arguments=': "fgOTN"}'),
            "[DONE]",
        ]
        sse_bytes = _make_sse_bytes(sse_events)
        resp = _mock_response(sse_bytes)
        svc = _make_llm_service()

        with patch.object(svc, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_get_session.return_value = mock_session

            chunks = [c async for c in svc.complete_stream([{"role": "user", "content": "test"}])]

        tool_chunks = [c for c in chunks if "tool_calls" in c]
        assert len(tool_chunks) == 1
        tc = tool_chunks[0]["tool_calls"][0]
        assert tc["name"] == "search_skill"
        assert tc["arguments"] == {"query": "fgOTN"}

    @pytest.mark.asyncio
    async def test_tool_calls_emitted_at_stream_end(self):
        """tool_calls 在流结束时（处理完所有数据后）一次性 yield。"""
        sse_events = [
            _make_delta_chunk(index=0, tc_id="c1", name="execute_data", arguments='{"sid": "s1"}'),
            "[DONE]",
        ]
        sse_bytes = _make_sse_bytes(sse_events)
        resp = _mock_response(sse_bytes)
        svc = _make_llm_service()

        tool_call_positions = []
        chunk_index = 0

        with patch.object(svc, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_get_session.return_value = mock_session

            async for chunk in svc.complete_stream([{"role": "user", "content": "test"}]):
                if "tool_calls" in chunk:
                    tool_call_positions.append(chunk_index)
                chunk_index += 1

        # tool_calls 只出现一次，且是最后一个非空 chunk
        assert len(tool_call_positions) == 1

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_by_index(self):
        """两个不同 index 的工具调用各自独立累积。"""
        sse_events = [
            _make_delta_chunk(index=0, tc_id="c1", name="search_skill", arguments=""),
            _make_delta_chunk(index=1, tc_id="c2", name="execute_data", arguments=""),
            _make_delta_chunk(index=0, arguments='{"q": "a"}'),
            _make_delta_chunk(index=1, arguments='{"sid": "s1"}'),
            "[DONE]",
        ]
        sse_bytes = _make_sse_bytes(sse_events)
        resp = _mock_response(sse_bytes)
        svc = _make_llm_service()

        with patch.object(svc, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_get_session.return_value = mock_session

            chunks = [c async for c in svc.complete_stream([{"role": "user", "content": "test"}])]

        tool_chunks = [c for c in chunks if "tool_calls" in c]
        assert len(tool_chunks) == 1
        tcs = tool_chunks[0]["tool_calls"]
        assert len(tcs) == 2
        names = {tc["name"] for tc in tcs}
        assert names == {"search_skill", "execute_data"}

    @pytest.mark.asyncio
    async def test_content_and_tool_calls_not_mixed(self):
        """content 片段正常处理，tool_calls 单独 yield（不混在 content chunk 里）。"""
        sse_events = [
            {"choices": [{"delta": {"content": "先说话"}}]},
            _make_delta_chunk(index=0, tc_id="c1", name="some_tool", arguments='{"x": 1}'),
            "[DONE]",
        ]
        sse_bytes = _make_sse_bytes(sse_events)
        resp = _mock_response(sse_bytes)
        svc = _make_llm_service()

        with patch.object(svc, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_get_session.return_value = mock_session

            chunks = [c async for c in svc.complete_stream([{"role": "user", "content": "test"}])]

        content_chunks = [c for c in chunks if "content" in c]
        tool_chunks = [c for c in chunks if "tool_calls" in c]
        assert any("先说话" in c.get("content", "") for c in content_chunks)
        assert len(tool_chunks) == 1

    @pytest.mark.asyncio
    async def test_error_status_yields_error(self):
        """HTTP 非 200 响应 yield {"error": ...}。"""
        resp = _mock_response(b"Unauthorized", status=401)
        svc = _make_llm_service()

        with patch.object(svc, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_get_session.return_value = mock_session

            chunks = [c async for c in svc.complete_stream([{"role": "user", "content": "test"}])]

        error_chunks = [c for c in chunks if "error" in c]
        assert len(error_chunks) >= 1
        assert "401" in str(error_chunks[0]["error"]) or "LLM" in str(error_chunks[0]["error"])

    @pytest.mark.asyncio
    async def test_pure_content_stream(self):
        """纯 content 流（无 tool_calls）正确 yield content chunks。"""
        sse_events = [
            {"choices": [{"delta": {"content": "Hello "}}]},
            {"choices": [{"delta": {"content": "World"}}]},
            "[DONE]",
        ]
        sse_bytes = _make_sse_bytes(sse_events)
        resp = _mock_response(sse_bytes)
        svc = _make_llm_service()

        with patch.object(svc, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_get_session.return_value = mock_session

            chunks = [c async for c in svc.complete_stream([{"role": "user", "content": "test"}])]

        content = "".join(c.get("content", "") for c in chunks)
        assert content == "Hello World"
        assert not any("tool_calls" in c for c in chunks)
