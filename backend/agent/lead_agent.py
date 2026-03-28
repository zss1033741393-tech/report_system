"""Lead Agent —— ReAct 架构入口。

LLM 全程参与工具调用决策，动态感知中间结果，自主规划下一步。

保持与原有接口完全兼容：
  - handle_message(session_id, user_message) → AsyncGenerator[str, None]（SSE 字符串）
  - 构造函数签名与原版相同（middleware_chain / skill_registry / skill_loader 保留）
"""

import json
import logging
from typing import AsyncGenerator

from agent.context import AgentContext
from agent.middleware.base import MiddlewareChain
from agent.react_engine import SimpleReActEngine
from agent.memory import MemoryStorage, MemoryUpdater, MemoryQueue
from agent.skill_loader import SkillLoader
from agent.skill_registry import SkillRegistry
from agent.tool_registry import ToolRegistry
from llm.service import LLMService
from services.chat_history import ChatHistoryService
from services.session_service import SessionService
from utils.trace_logger import TraceLogger

logger = logging.getLogger(__name__)


class LeadAgent:
    """
    ReAct 版 Lead Agent。

    与原版接口完全兼容，main.py 无需修改。
    """

    def __init__(
        self,
        llm_service: LLMService,
        middleware_chain: MiddlewareChain,
        skill_registry: SkillRegistry,
        skill_loader: SkillLoader,
        chat_history: ChatHistoryService,
        session_service: SessionService,
    ):
        self._llm = llm_service
        self._mw = middleware_chain
        self._reg = skill_registry
        self._loader = skill_loader
        self._ch = chat_history
        self._ss = session_service

        # 构建 ToolRegistry（桥接 Executor）
        self._tool_registry = ToolRegistry(
            skill_loader=skill_loader,
            skill_registry=skill_registry,
            chat_history=chat_history,
            session_service=session_service,
        )

        # 构建 Memory 系统
        self._memory_storage = MemoryStorage()
        memory_updater = MemoryUpdater(llm_service, self._memory_storage)
        self._memory_queue = MemoryQueue(memory_updater)

        # 构建 ReAct 引擎
        self._engine = SimpleReActEngine(
            llm_service=llm_service,
            tool_registry=self._tool_registry,
            chat_history=chat_history,
            session_service=session_service,
            skill_registry=skill_registry,
            memory_storage=self._memory_storage,
            memory_queue=self._memory_queue,
        )

    def _make_trace_callback(self, session_id: str, trace_id: str):
        ch = self._ch

        async def callback(
            llm_type, step_name, request_messages, response_content,
            reasoning_content, model, temperature, elapsed_ms, success, error
        ):
            await ch.save_llm_trace(
                session_id=session_id,
                trace_id=trace_id,
                llm_type=llm_type,
                step_name=step_name,
                request_messages=request_messages,
                response_content=response_content,
                reasoning_content=reasoning_content,
                model=model,
                temperature=temperature,
                elapsed_ms=elapsed_ms,
                success=success,
                error=error,
            )

        return callback

    async def handle_message(
        self, session_id: str, user_message: str
    ) -> AsyncGenerator[str, None]:
        """
        处理用户消息，yield SSE 事件字符串。
        与原版接口完全兼容。
        """
        # ─── 初始化 ──────────────────────────────────────────────────────────
        await self._ch.ensure_session(session_id)
        await self._ch.add_message(session_id, "user", user_message)

        trace = TraceLogger(session_id=session_id)
        trace.log("request.start", data={"user_message": user_message})
        trace_cb = self._make_trace_callback(session_id, trace.trace_id)

        # 更新会话标题（首次消息）
        msgs = await self._ch.get_messages(session_id, limit=2)
        if len(msgs) <= 1:
            title = user_message[:20] + ("..." if len(user_message) > 20 else "")
            await self._ch.update_session_title(session_id, title)

        # ─── Middleware（加载历史、大纲状态等）─────────────────────────────
        ctx = AgentContext(
            session_id=session_id,
            user_message=user_message,
            trace_id=trace.trace_id,
        )
        ctx = await self._mw.run_before(ctx)

        # 从 middleware 收集的 chat_history（已过滤 thinking/outline 等特殊消息）
        chat_history_msgs = ctx.chat_history or []

        # ─── ReAct 主循环 ────────────────────────────────────────────────────
        collected_reply = []

        async for sse_str in self._engine.run(
            session_id=session_id,
            user_message=user_message,
            chat_history_msgs=chat_history_msgs,
            trace_callback=trace_cb,
        ):
            yield sse_str

            # 收集最终回复内容，用于持久化
            try:
                evt = json.loads(sse_str)
                if evt.get("type") == "chat_reply":
                    collected_reply.append(evt.get("content", ""))
            except Exception:
                pass

        # ─── 持久化 assistant 回复 ───────────────────────────────────────────
        final_reply = "".join(collected_reply)
        if final_reply:
            await self._ch.add_message(session_id, "assistant", final_reply)
        else:
            # 如果没有 chat_reply（例如只有工具调用），记录一条摘要
            await self._ch.add_message(session_id, "assistant", "已完成操作，请查看右侧面板。")

        trace.log("request.done")

    @staticmethod
    def _ev(event_type: str, **kwargs) -> str:
        return json.dumps({"type": event_type, **kwargs}, ensure_ascii=False)
