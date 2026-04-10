"""测试 LLMService 非流式调用（stream=False）。

通过 mock aiohttp.ClientSession.post 注入 OpenAI 标准非流式响应 JSON，
验证 _do_non_stream 正确转换为与流式相同的 yield 格式。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm.config import LLMConfig
from llm.service import LLMService


# ─── Mock 工具 ────────────────────────────────────────────────────────────────

def _make_non_stream_response(message: dict, status: int = 200) -> MagicMock:
    """构造非流式 OpenAI 兼容响应。"""
    body = {"choices": [{"message": message, "finish_reason": "stop"}]}
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=body)
    resp.text = AsyncMock(return_value=json.dumps(body))
    return resp


class _MockContextManager:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *args):
        pass


def _make_svc(think_tag_mode: str = "none") -> LLMService:
    return LLMService(
        base_url="http://fake-llm",
        default_model="fake-model",
        think_tag_mode=think_tag_mode,
    )


def _non_stream_config(**overrides) -> LLMConfig:
    defaults = {"stream": False}
    defaults.update(overrides)
    return LLMConfig(**defaults)


async def _collect(svc, messages, config, tools=None):
    chunks = []
    async for c in svc.complete_stream(messages, config, tools=tools):
        chunks.append(c)
    return chunks


# ─── 纯文本响应 ───────────────────────────────────────────────────────────────

class TestNonStreamContent:

    @pytest.mark.asyncio
    async def test_plain_content(self):
        """非流式纯文本响应正确 yield {"content": ...}。"""
        resp = _make_non_stream_response({"role": "assistant", "content": "你好，世界"})
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "hi"}], cfg)

        content = "".join(c.get("content", "") for c in chunks)
        assert content == "你好，世界"
        assert not any("tool_calls" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_payload_stream_false(self):
        """config.stream=False 时 HTTP payload 中 stream 字段为 False。"""
        resp = _make_non_stream_response({"role": "assistant", "content": "ok"})
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        # 检查 post 调用的 payload
        call_kwargs = mock_session.post.call_args
        payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        assert payload["stream"] is False


# ─── 工具调用 ─────────────────────────────────────────────────────────────────

class TestNonStreamToolCalls:

    @pytest.mark.asyncio
    async def test_tool_calls_parsed(self):
        """非流式工具调用响应正确解析为 {"tool_calls": [...]}。"""
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search_skill",
                        "arguments": '{"query": "fgOTN容量"}'
                    }
                }
            ]
        }
        resp = _make_non_stream_response(message)
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        tc_chunks = [c for c in chunks if "tool_calls" in c]
        assert len(tc_chunks) == 1
        tc = tc_chunks[0]["tool_calls"][0]
        assert tc["id"] == "call_1"
        assert tc["name"] == "search_skill"
        assert tc["arguments"] == {"query": "fgOTN容量"}

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self):
        """多个工具调用全部解析。"""
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "tool_a", "arguments": '{"x": 1}'}},
                {"id": "c2", "type": "function",
                 "function": {"name": "tool_b", "arguments": '{"y": 2}'}},
            ]
        }
        resp = _make_non_stream_response(message)
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        tc_chunks = [c for c in chunks if "tool_calls" in c]
        assert len(tc_chunks) == 1
        tcs = tc_chunks[0]["tool_calls"]
        assert len(tcs) == 2
        assert {tc["name"] for tc in tcs} == {"tool_a", "tool_b"}

    @pytest.mark.asyncio
    async def test_tool_calls_arguments_already_dict(self):
        """部分模型返回 arguments 已是 dict 而非 JSON 字符串，应兼容处理。"""
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "search_skill", "arguments": {"query": "test"}}}
            ]
        }
        resp = _make_non_stream_response(message)
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        tc = [c for c in chunks if "tool_calls" in c][0]["tool_calls"][0]
        assert tc["arguments"] == {"query": "test"}


# ─── reasoning_content ────────────────────────────────────────────────────────

class TestNonStreamReasoning:

    @pytest.mark.asyncio
    async def test_explicit_reasoning_content(self):
        """模型返回显式 reasoning_content 字段时正确 yield。"""
        message = {
            "role": "assistant",
            "content": "最终回答",
            "reasoning_content": "内部推理过程..."
        }
        resp = _make_non_stream_response(message)
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        reasoning = "".join(c.get("reasoning_content", "") for c in chunks)
        content = "".join(c.get("content", "") for c in chunks)
        assert "内部推理过程" in reasoning
        assert "最终回答" in content

    @pytest.mark.asyncio
    async def test_think_tag_in_content(self):
        """content 中含 <think>...</think> 标签时正确拆分为 reasoning + content。"""
        message = {
            "role": "assistant",
            "content": "<think>思考中...</think>这是回答"
        }
        resp = _make_non_stream_response(message)
        svc = _make_svc(think_tag_mode="qwen3")
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        reasoning = "".join(c.get("reasoning_content", "") for c in chunks)
        content = "".join(c.get("content", "") for c in chunks)
        assert "思考中" in reasoning
        assert "这是回答" in content

    @pytest.mark.asyncio
    async def test_think_tag_mode_none_no_parse(self):
        """think_tag_mode=none 时不解析 think 标签，原样输出 content。"""
        raw_text = "<think>思考</think>回答"
        message = {"role": "assistant", "content": raw_text}
        resp = _make_non_stream_response(message)
        svc = _make_svc(think_tag_mode="none")
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        content = "".join(c.get("content", "") for c in chunks)
        assert content == raw_text
        assert not any("reasoning_content" in c for c in chunks)


# ─── 错误处理 ─────────────────────────────────────────────────────────────────

class TestNonStreamErrors:

    @pytest.mark.asyncio
    async def test_http_error_yields_error(self):
        """HTTP 非 200 响应 yield {"error": ...}。"""
        resp = MagicMock()
        resp.status = 500
        resp.text = AsyncMock(return_value="Internal Server Error")
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        assert any("error" in c for c in chunks)
        assert "500" in chunks[0]["error"]

    @pytest.mark.asyncio
    async def test_empty_choices_yields_error(self):
        """空 choices 返回错误。"""
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"choices": []})
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        assert any("error" in c for c in chunks)


# ─── complete_full / complete 集成 ────────────────────────────────────────────

class TestNonStreamHighLevel:

    @pytest.mark.asyncio
    async def test_complete_full_non_stream(self):
        """complete_full 在 stream=False 时正常工作。"""
        message = {"role": "assistant", "content": "非流式回答", "reasoning_content": "推理"}
        resp = _make_non_stream_response(message)
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            result = await svc.complete_full([{"role": "user", "content": "test"}], cfg)

        assert result["content"] == "非流式回答"
        assert "推理" in result["reasoning_content"]

    @pytest.mark.asyncio
    async def test_complete_non_stream(self):
        """complete() 在 stream=False 时返回纯文本。"""
        message = {"role": "assistant", "content": "简短回答"}
        resp = _make_non_stream_response(message)
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            text = await svc.complete([{"role": "user", "content": "test"}], cfg)

        assert text == "简短回答"


# ─── tools 非流式 + 空响应防御 ────────────────────────────────────────────────

class TestNonStreamWithTools:

    @pytest.mark.asyncio
    async def test_tools_non_stream_respects_config(self):
        """config.stream=False + tools 时，payload 中 stream 应为 False（尊重配置）。"""
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "get_session_status", "arguments": "{}"}}
            ]
        }
        resp = _make_non_stream_response(message)
        svc = _make_svc()
        cfg = _non_stream_config()

        tools = [{"type": "function", "function": {"name": "get_session_status",
                                                     "parameters": {"type": "object", "properties": {}}}}]

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg, tools=tools)

        call_kwargs = mock_session.post.call_args
        payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        assert payload["stream"] is False, "应尊重 config.stream=False"

        tc_chunks = [c for c in chunks if "tool_calls" in c]
        assert len(tc_chunks) == 1
        assert tc_chunks[0]["tool_calls"][0]["name"] == "get_session_status"


class TestEmptyResponseDetection:

    @pytest.mark.asyncio
    async def test_empty_content_empty_tool_calls_yields_error(self):
        """模型返回 content='' 且 tool_calls=[] 时 yield error 而非静默。"""
        message = {"role": "assistant", "content": "", "tool_calls": []}
        resp = _make_non_stream_response(message)
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        assert any("error" in c for c in chunks), "空响应应 yield error"
        assert "空响应" in chunks[0]["error"]

    @pytest.mark.asyncio
    async def test_content_none_no_tools_yields_error(self):
        """模型返回 content=None 且无 tool_calls 时 yield error。"""
        message = {"role": "assistant", "content": None}
        resp = _make_non_stream_response(message)
        svc = _make_svc()
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        assert any("error" in c for c in chunks)


# ─── content 内嵌 <tool_call> 标签解析 ────────────────────────────────────────

class TestToolCallTagParsing:

    @pytest.mark.asyncio
    async def test_think_and_tool_call_tags_in_content(self):
        """模型将 <think> 和 <tool_call> 都放在 content 中时，正确拆分为 reasoning + tool_calls。"""
        raw_content = (
            '<think>\n用户想分析OTN升级，我需要先调用skill_router。\n</think>\n\n'
            '<tool_call>\n{"name": "skill_router", "arguments": {"query": "分析政企OTN升级的机会点"}}\n</tool_call>'
        )
        message = {"role": "assistant", "content": raw_content, "tool_calls": []}
        resp = _make_non_stream_response(message)
        svc = _make_svc(think_tag_mode="qwen3")
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        # 应有 reasoning_content
        reasoning = "".join(c.get("reasoning_content", "") for c in chunks)
        assert "skill_router" in reasoning

        # 应有 tool_calls
        tc_chunks = [c for c in chunks if "tool_calls" in c]
        assert len(tc_chunks) == 1
        tc = tc_chunks[0]["tool_calls"][0]
        assert tc["name"] == "skill_router"
        assert tc["arguments"] == {"query": "分析政企OTN升级的机会点"}

        # 不应将 <tool_call> 标签当作普通 content 输出
        content = "".join(c.get("content", "") for c in chunks)
        assert "<tool_call>" not in content

    @pytest.mark.asyncio
    async def test_tool_call_tag_without_think(self):
        """content 只有 <tool_call> 没有 <think> 时正确解析。"""
        raw_content = '<tool_call>\n{"name": "get_session_status", "arguments": {}}\n</tool_call>'
        message = {"role": "assistant", "content": raw_content, "tool_calls": []}
        resp = _make_non_stream_response(message)
        svc = _make_svc(think_tag_mode="none")
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        tc_chunks = [c for c in chunks if "tool_calls" in c]
        assert len(tc_chunks) == 1
        assert tc_chunks[0]["tool_calls"][0]["name"] == "get_session_status"

    @pytest.mark.asyncio
    async def test_multiple_tool_call_tags(self):
        """content 中有多个 <tool_call> 标签时全部解析。"""
        raw_content = (
            '<tool_call>\n{"name": "tool_a", "arguments": {"x": 1}}\n</tool_call>\n'
            '<tool_call>\n{"name": "tool_b", "arguments": {"y": 2}}\n</tool_call>'
        )
        message = {"role": "assistant", "content": raw_content, "tool_calls": []}
        resp = _make_non_stream_response(message)
        svc = _make_svc(think_tag_mode="none")
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        tc_chunks = [c for c in chunks if "tool_calls" in c]
        assert len(tc_chunks) == 1
        tcs = tc_chunks[0]["tool_calls"]
        assert len(tcs) == 2
        assert {tc["name"] for tc in tcs} == {"tool_a", "tool_b"}

    @pytest.mark.asyncio
    async def test_content_with_text_and_tool_call(self):
        """content 中既有普通文本又有 <tool_call> 时，文本和工具调用各自正确输出。"""
        raw_content = '让我先查一下状态。\n<tool_call>\n{"name": "get_session_status", "arguments": {}}\n</tool_call>'
        message = {"role": "assistant", "content": raw_content, "tool_calls": []}
        resp = _make_non_stream_response(message)
        svc = _make_svc(think_tag_mode="none")
        cfg = _non_stream_config()

        with patch.object(svc, "_get_session") as mock_gs:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=_MockContextManager(resp))
            mock_gs.return_value = mock_session

            chunks = await _collect(svc, [{"role": "user", "content": "test"}], cfg)

        content = "".join(c.get("content", "") for c in chunks)
        assert "先查一下状态" in content
        assert "<tool_call>" not in content

        tc_chunks = [c for c in chunks if "tool_calls" in c]
        assert len(tc_chunks) == 1
        assert tc_chunks[0]["tool_calls"][0]["name"] == "get_session_status"
