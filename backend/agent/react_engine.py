"""SimpleReActEngine —— 对标 DeerFlow LangGraph Agent Loop。

执行流程：
  初始化 messages = [system] + history + [user]
  STEP LOOP (MAX_STEPS):
    ① 上下文压缩检查
    ② llm.complete_with_tools(messages, tools)
    ③ if tool_calls:
         append AIMessage(tool_calls)
         for each tool_call:
           yield SSE("tool_call", ...)
           result = await tool_registry.execute(tool_call)
           append ToolMessage(result)
           yield SSE("tool_result", ...)
         循环检测
       else（最终答案）:
         yield SSE("chat_reply", content)
         break
  收尾：持久化新消息

设计决策：
  - 警告/强制停止消息注入为 user role（避免 system message 限制）
  - tool_call / tool_result SSE 事件是通用事件，前端渲染为 ToolCallBlock
  - 工具 handler 内部转发的业务事件（outline_chunk、report_chunk 等）保持原样
"""
import json
import logging
from typing import AsyncGenerator, Optional

from llm.config import LLMConfig
from llm.service import LLMService
from agent.tool_registry import ToolRegistry, ToolContext
from agent.tool_definitions import ALL_TOOLS
from agent.loop_detector import LoopDetector
from agent.context_compressor import ContextCompressor

logger = logging.getLogger(__name__)

MAX_STEPS = 15


class SimpleReActEngine:

    def __init__(
        self,
        llm_service: LLMService,
        react_config: LLMConfig,
        compressor_config: Optional[LLMConfig] = None,
    ):
        self._llm = llm_service
        self._react_config = react_config
        self._compressor = ContextCompressor(llm_service, compressor_config)

    async def run(
        self,
        session_id: str,
        user_message: str,
        system_prompt: str,
        tool_registry: ToolRegistry,
        chat_history,           # ChatHistoryService
        session_service,        # SessionService
        skill_loader,           # SkillLoader（ToolContext 使用）
        trace_callback=None,
        on_new_messages=None,   # Optional[Callable[[list[dict]], None]]
    ) -> AsyncGenerator[str, None]:
        """
        主循环。yield 各类 SSE 事件字符串（data 部分，不含 "data: " 前缀）。
        """
        # ─── 初始化消息列表 ───────────────────────────────────────────────
        raw_history = await chat_history.get_messages(session_id, limit=20)
        history_msgs = _format_history(raw_history)

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            *history_msgs,
            {"role": "user", "content": user_message},
        ]

        # ToolContext 持有跨工具调用的可变状态
        tool_ctx = ToolContext(
            session_id=session_id,
            skill_loader=skill_loader,
            chat_history=chat_history,
            session_service=session_service,
            llm_service=self._llm,
            trace_callback=trace_callback,
        )

        # 加载当前会话的大纲到 ToolContext
        try:
            state = await chat_history.get_outline_state(session_id)
            if state and state.get("outline_json"):
                tool_ctx.current_outline = state["outline_json"]
        except Exception:
            pass

        # 加载 has_report 状态
        try:
            recent_msgs = await chat_history.get_messages(session_id, limit=50)
            for m in reversed(recent_msgs):
                if (m.get("metadata") or {}).get("report_html"):
                    tool_ctx.has_report = True
                    break
        except Exception:
            pass

        loop_detector = LoopDetector()
        prev_len = len(messages)   # 记录起始位置，收尾时只持久化新消息

        # ─── ReAct 主循环 ────────────────────────────────────────────────
        final_content = ""
        for step in range(MAX_STEPS):
            # ① 上下文压缩
            if self._compressor.should_compress(messages):
                messages = await self._compressor.compress(messages)

            # ② LLM 调用（带 tools）
            try:
                response = await self._llm.complete_with_tools(
                    messages, ALL_TOOLS, self._react_config
                )
            except Exception as e:
                logger.error(f"ReAct LLM 调用失败 (step={step}): {e}")
                err_msg = f"LLM 调用异常: {e}"
                yield _ev("error", message=err_msg)
                yield _ev("done")
                return

            finish_reason = response.get("finish_reason", "stop")
            tool_calls = response.get("tool_calls") or []
            content = response.get("content") or ""

            # ③ 工具调用分支
            if finish_reason == "tool_calls" or tool_calls:
                # 追加 AIMessage（含 tool_calls）
                messages.append({
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": json.dumps(tc["args"], ensure_ascii=False)},
                        }
                        for tc in tool_calls
                    ],
                })

                # 逐个执行工具
                for tc in tool_calls:
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("args", {})

                    # 先 yield tool_call 事件（前端渲染 ToolCallBlock）
                    yield _ev("tool_call", name=tool_name, args=tool_args)

                    # 执行工具，收集所有 SSE 输出
                    tool_result_content = ""
                    tool_success = True
                    async for chunk in tool_registry.execute(tc, tool_ctx):
                        try:
                            parsed = json.loads(chunk)
                            evt_type = parsed.get("type", "")
                            if evt_type == "tool_result":
                                # 提取工具结果（用于 ToolMessage）
                                tool_result_content = parsed.get("content", "")
                                tool_success = parsed.get("success", True)
                                # yield tool_result 给前端
                                yield _ev("tool_result",
                                          name=tool_name,
                                          content=tool_result_content,
                                          success=tool_success)
                            else:
                                # 转发业务事件（outline_chunk, report_chunk 等）
                                yield chunk
                        except (json.JSONDecodeError, Exception):
                            yield chunk

                    # 追加 ToolMessage（供下一轮 LLM 感知）
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": tool_result_content or "(no result)",
                    })

                # 循环检测
                loop_level = loop_detector.check(tool_calls)
                if loop_level > 0:
                    warn_content = loop_detector.get_warning_message(loop_level)
                    messages.append({"role": "user", "content": warn_content})
                    if loop_level >= 2:
                        # 强制停止：从消息中剥离最后一个 assistant 的 tool_calls
                        # 让下一轮 LLM 没有工具可调，强制输出文本
                        messages = _strip_last_tool_calls(messages)

            else:
                # ④ 最终答案
                final_content = content
                yield _ev("chat_reply", content=final_content)
                messages.append({"role": "assistant", "content": final_content})
                break

        else:
            # 达到 MAX_STEPS 还没输出最终答案
            final_content = "已达到最大步骤数，请检查您的请求或重试。"
            yield _ev("chat_reply", content=final_content)
            messages.append({"role": "assistant", "content": final_content})

        # ─── 收尾：持久化新消息 + 通知 memory 更新 ──────────────────────
        new_msgs = messages[prev_len:]
        await _persist_new_messages(
            chat_history, session_id, new_msgs,
            tool_ctx, final_content,
        )

        # 回调通知 LeadAgent 收集本轮新消息（用于异步 memory 提取）
        if on_new_messages and new_msgs:
            try:
                on_new_messages(new_msgs)
            except Exception:
                pass

        yield _ev("done")


# ─── 辅助函数 ────────────────────────────────────────────────────────────

def _ev(event_type: str, **kwargs) -> str:
    return json.dumps({"type": event_type, **kwargs}, ensure_ascii=False)


def _format_history(raw_msgs: list[dict]) -> list[dict]:
    """将 ChatHistoryService 的消息格式转为 OpenAI messages 格式。"""
    result = []
    for m in raw_msgs:
        role = m.get("role", "user")
        if role not in ("user", "assistant"):
            continue
        meta = m.get("metadata") or {}
        content = m.get("content", "")
        # 简化 assistant 消息，避免注入过多上下文
        if role == "assistant":
            if meta.get("summary"):
                content = f"[摘要] {meta['summary']}"
            elif m.get("msg_type") == "outline":
                content = "[已生成大纲]"
        result.append({"role": role, "content": content})
    return result


def _strip_last_tool_calls(messages: list[dict]) -> list[dict]:
    """从消息列表末尾移除最近一个含 tool_calls 的 assistant 消息及其后的 tool messages。"""
    # 从后往前找最近的含 tool_calls 的 assistant 消息
    idx = len(messages) - 1
    while idx >= 0:
        m = messages[idx]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            break
        idx -= 1
    if idx < 0:
        return messages
    # 截断到该 assistant 消息之前
    return messages[:idx]


async def _persist_new_messages(
    chat_history,
    session_id: str,
    new_messages: list[dict],
    tool_ctx: ToolContext,
    final_content: str,
):
    """持久化本轮新增消息（assistant 最终回复 + metadata）。"""
    try:
        meta = {}
        if tool_ctx.current_outline:
            pass  # outline 已在工具 handler 内持久化
        if tool_ctx.has_report:
            meta["has_report"] = True

        # 只持久化 assistant 最终文本回复
        if final_content:
            await chat_history.add_message(
                session_id, "assistant", final_content,
                msg_type="text",
                metadata=meta if meta else None,
            )
    except Exception as e:
        logger.warning(f"持久化新消息失败: {e}")
