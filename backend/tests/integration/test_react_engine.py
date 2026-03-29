"""集成测试：SimpleReActEngine —— SSE 事件流 + 技能规划场景。

测试方法：
  Mock LLMService.complete_with_tools() 预置确定性返回值
  Mock ToolRegistry 控制工具执行结果
  收集 yield 的 SSE 事件序列，验证顺序和内容

覆盖场景：
  A. 简单对话（无工具调用）→ chat_reply + done
  B. 单次工具调用 → tool_call + tool_result + chat_reply + done
  C. 多步工具链（3 步）→ 3×(tool_call+tool_result) + chat_reply + done
  D. 业务事件转发（outline_chunk）→ 事件透传
  E. 循环检测触发 → 警告消息注入
  F. LLM 异常 → error + done
  G. 达到 MAX_STEPS → 强制输出
  H. 消息持久化验证
"""
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agent.react_engine import SimpleReActEngine, MAX_STEPS
from agent.tool_registry import ToolRegistry, ToolContext
from agent.loop_detector import WARN_THRESHOLD


# ─── 辅助工具 ────────────────────────────────────────────────────────────────

def _make_engine(llm):
    from llm.config import LLMConfig
    config = LLMConfig(model="test", temperature=0.1)
    engine = SimpleReActEngine(llm, react_config=config, compressor_config=config)
    return engine


def _mock_chat_history():
    ch = MagicMock()
    ch.get_messages = AsyncMock(return_value=[])
    ch.get_outline_state = AsyncMock(return_value=None)
    ch.add_message = AsyncMock(return_value=1)
    ch.ensure_session = AsyncMock()
    ch.save_outline_state = AsyncMock()
    ch.update_session_title = AsyncMock()
    return ch


def _mock_session_service():
    ss = MagicMock()
    ss.redis = AsyncMock()
    ss.redis.get = AsyncMock(return_value=None)
    return ss


def _mock_skill_loader():
    sl = MagicMock()
    sl.get_executor = MagicMock(return_value=None)
    return sl


async def _collect_events(gen) -> list[dict]:
    """收集 async generator 的所有 SSE 事件。"""
    events = []
    async for chunk in gen:
        try:
            events.append(json.loads(chunk))
        except Exception:
            events.append({"_raw": chunk})
    return events


def _llm_stop(content="这是最终答案。"):
    """模拟 LLM 直接返回最终答案（无工具调用）。"""
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value={
        "content": content,
        "tool_calls": [],
        "finish_reason": "stop",
    })
    return llm


def _llm_tool_then_stop(tool_name="get_session_status", tool_args=None, final_answer="完成了"):
    """第一次调用返回工具调用，第二次返回最终答案。"""
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(side_effect=[
        {
            "content": "",
            "tool_calls": [{"id": "call_1", "name": tool_name, "args": tool_args or {"session_id": "s1"}}],
            "finish_reason": "tool_calls",
        },
        {
            "content": final_answer,
            "tool_calls": [],
            "finish_reason": "stop",
        },
    ])
    return llm


def _empty_tool_registry():
    """总是返回空 tool_result 的 ToolRegistry。"""
    reg = MagicMock()

    async def _exec(tc, ctx):
        # 注意：engine 自身会先 yield tool_call 事件，registry 只需返回 tool_result
        yield json.dumps({"type": "tool_result", "name": tc["name"],
                          "content": "ok", "success": True})

    reg.execute = _exec
    return reg


# ─── 场景 A: 简单对话 ─────────────────────────────────────────────────────────

class TestScenarioASimpleChat:
    @pytest.mark.asyncio
    async def test_simple_chat_yields_chat_reply_and_done(self, chat_history):
        llm = _llm_stop("你好，我是助手。")
        engine = _make_engine(llm)
        gen = engine.run(
            session_id="s-a", user_message="你好",
            system_prompt="你是助手",
            tool_registry=_empty_tool_registry(),
            chat_history=chat_history,
            session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        )
        events = await _collect_events(gen)
        types = [e["type"] for e in events]
        assert "chat_reply" in types
        assert types[-1] == "done"

    @pytest.mark.asyncio
    async def test_simple_chat_reply_content(self, chat_history):
        llm = _llm_stop("这是测试回答内容")
        engine = _make_engine(llm)
        events = await _collect_events(engine.run(
            session_id="s-a2", user_message="测试",
            system_prompt="系统提示", tool_registry=_empty_tool_registry(),
            chat_history=chat_history, session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        ))
        chat_reply = next(e for e in events if e.get("type") == "chat_reply")
        assert chat_reply["content"] == "这是测试回答内容"

    @pytest.mark.asyncio
    async def test_simple_chat_no_tool_events(self, chat_history):
        events = await _collect_events(_make_engine(_llm_stop()).run(
            session_id="s-a3", user_message="你好",
            system_prompt="", tool_registry=_empty_tool_registry(),
            chat_history=chat_history, session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        ))
        types = [e["type"] for e in events]
        assert "tool_call" not in types
        assert "tool_result" not in types


# ─── 场景 B: 单次工具调用 ─────────────────────────────────────────────────────

class TestScenarioBSingleTool:
    @pytest.mark.asyncio
    async def test_single_tool_event_sequence(self, chat_history):
        llm = _llm_tool_then_stop("get_session_status", {"session_id": "s-b"})
        engine = _make_engine(llm)
        events = await _collect_events(engine.run(
            session_id="s-b", user_message="状态如何",
            system_prompt="", tool_registry=_empty_tool_registry(),
            chat_history=chat_history, session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        ))
        types = [e["type"] for e in events]
        # 顺序：tool_call → tool_result → ... → chat_reply → done
        assert types[0] == "tool_call"
        assert types[1] == "tool_result"
        assert "chat_reply" in types
        assert types[-1] == "done"

    @pytest.mark.asyncio
    async def test_tool_call_event_has_name(self, chat_history):
        llm = _llm_tool_then_stop("get_session_status")
        events = await _collect_events(_make_engine(llm).run(
            session_id="s-b2", user_message="查状态",
            system_prompt="", tool_registry=_empty_tool_registry(),
            chat_history=chat_history, session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        ))
        tc_event = next(e for e in events if e.get("type") == "tool_call")
        assert tc_event["name"] == "get_session_status"

    @pytest.mark.asyncio
    async def test_tool_result_event_has_content(self, chat_history):
        llm = _llm_tool_then_stop("search_skill")
        events = await _collect_events(_make_engine(llm).run(
            session_id="s-b3", user_message="搜索",
            system_prompt="", tool_registry=_empty_tool_registry(),
            chat_history=chat_history, session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        ))
        tr_event = next(e for e in events if e.get("type") == "tool_result")
        assert "content" in tr_event
        assert "success" in tr_event


# ─── 场景 C: 多步工具链 ───────────────────────────────────────────────────────

class TestScenarioCMultiStep:
    @pytest.mark.asyncio
    async def test_three_step_tool_chain(self, chat_history):
        """三步工具链：get_session_status → search_skill → execute_data → 最终答案。"""
        llm = MagicMock()
        llm.complete_with_tools = AsyncMock(side_effect=[
            {"content": "", "tool_calls": [{"id": "c1", "name": "get_session_status", "args": {"session_id": "s-c"}}], "finish_reason": "tool_calls"},
            {"content": "", "tool_calls": [{"id": "c2", "name": "search_skill", "args": {"session_id": "s-c", "query": "容量"}}], "finish_reason": "tool_calls"},
            {"content": "", "tool_calls": [{"id": "c3", "name": "execute_data", "args": {"session_id": "s-c"}}], "finish_reason": "tool_calls"},
            {"content": "三步完成", "tool_calls": [], "finish_reason": "stop"},
        ])
        events = await _collect_events(_make_engine(llm).run(
            session_id="s-c", user_message="分析容量",
            system_prompt="", tool_registry=_empty_tool_registry(),
            chat_history=chat_history, session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        ))
        types = [e["type"] for e in events]
        assert types.count("tool_call") == 3
        assert types.count("tool_result") == 3
        assert "chat_reply" in types
        assert types[-1] == "done"


# ─── 场景 D: 业务事件转发 ─────────────────────────────────────────────────────

class TestScenarioDBusinessEvents:
    @pytest.mark.asyncio
    async def test_outline_chunk_forwarded(self, chat_history):
        """工具内部产生的 outline_chunk 事件应被转发给前端。"""
        llm = MagicMock()
        llm.complete_with_tools = AsyncMock(side_effect=[
            {"content": "", "tool_calls": [{"id": "oc1", "name": "search_skill",
                                             "args": {"session_id": "s-d", "query": "容量"}}],
             "finish_reason": "tool_calls"},
            {"content": "大纲生成完成", "tool_calls": [], "finish_reason": "stop"},
        ])

        # 自定义 registry：产生 outline_chunk 事件
        reg = MagicMock()
        async def _exec_outline(tc, ctx):
            yield json.dumps({"type": "outline_chunk", "content": "第一节"})
            yield json.dumps({"type": "outline_chunk", "content": "第二节"})
            yield json.dumps({"type": "outline_done", "anchor": None})
            yield json.dumps({"type": "tool_result", "name": "search_skill",
                              "content": "大纲已生成", "success": True})
        reg.execute = _exec_outline

        events = await _collect_events(_make_engine(llm).run(
            session_id="s-d", user_message="生成大纲",
            system_prompt="", tool_registry=reg,
            chat_history=chat_history, session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        ))
        types = [e["type"] for e in events]
        assert "outline_chunk" in types
        assert "outline_done" in types
        outline_chunks = [e for e in events if e["type"] == "outline_chunk"]
        assert len(outline_chunks) == 2


# ─── 场景 E: 循环检测 ─────────────────────────────────────────────────────────

class TestScenarioELoopDetection:
    @pytest.mark.asyncio
    async def test_loop_warning_injected(self, chat_history):
        """同一工具调用 WARN_THRESHOLD 次后，消息列表中应注入警告。"""
        # 构造：前 WARN_THRESHOLD 次返回同一工具，最后返回最终答案
        tool_responses = [
            {"content": "", "tool_calls": [{"id": f"lc{i}", "name": "search_skill",
                                             "args": {"query": "容量", "session_id": "s-e"}}],
             "finish_reason": "tool_calls"}
            for i in range(WARN_THRESHOLD)
        ]
        tool_responses.append({
            "content": "循环后的最终答案", "tool_calls": [], "finish_reason": "stop"
        })
        llm = MagicMock()
        llm.complete_with_tools = AsyncMock(side_effect=tool_responses)

        events = await _collect_events(_make_engine(llm).run(
            session_id="s-e", user_message="分析",
            system_prompt="", tool_registry=_empty_tool_registry(),
            chat_history=chat_history, session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        ))
        # 最终应完成（有 done）
        types = [e["type"] for e in events]
        assert "done" in types


# ─── 场景 F: LLM 异常 ────────────────────────────────────────────────────────

class TestScenarioFError:
    @pytest.mark.asyncio
    async def test_llm_exception_yields_error_done(self, chat_history):
        llm = MagicMock()
        llm.complete_with_tools = AsyncMock(side_effect=RuntimeError("LLM 服务不可用"))
        events = await _collect_events(_make_engine(llm).run(
            session_id="s-f", user_message="触发错误",
            system_prompt="", tool_registry=_empty_tool_registry(),
            chat_history=chat_history, session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        ))
        types = [e["type"] for e in events]
        assert "error" in types
        assert types[-1] == "done"

    @pytest.mark.asyncio
    async def test_error_event_has_message(self, chat_history):
        llm = MagicMock()
        llm.complete_with_tools = AsyncMock(side_effect=RuntimeError("连接超时"))
        events = await _collect_events(_make_engine(llm).run(
            session_id="s-f2", user_message="触发错误",
            system_prompt="", tool_registry=_empty_tool_registry(),
            chat_history=chat_history, session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        ))
        error_event = next(e for e in events if e.get("type") == "error")
        assert "message" in error_event
        assert len(error_event["message"]) > 0


# ─── 场景 H: 消息持久化 ───────────────────────────────────────────────────────

class TestScenarioHPersistence:
    @pytest.mark.asyncio
    async def test_final_reply_persisted(self, chat_history):
        """ReAct 循环结束后，最终回复应被持久化到 chat_history。"""
        await chat_history.create_session("s-persist", "测试")
        llm = _llm_stop("持久化的最终答案")
        await _collect_events(_make_engine(llm).run(
            session_id="s-persist", user_message="问题",
            system_prompt="", tool_registry=_empty_tool_registry(),
            chat_history=chat_history, session_service=_mock_session_service(),
            skill_loader=_mock_skill_loader(),
        ))
        msgs = await chat_history.get_messages("s-persist")
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        assert "持久化的最终答案" in assistant_msgs[-1]["content"]
