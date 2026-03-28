"""Lead Agent —— ReAct 引擎入口。

v5.0: 替换 Plan-then-Execute 为 SimpleReActEngine（ReAct 主循环）。
  - 删除 Planner / Reflector
  - System Prompt 注入 <skill_system> 块（Progressive Loading）
  - LLM 通过 tool calling 自主决策，工具 handler 复用所有现有 Executor
  - 新增 /api/v1/sessions/{sid}/artifacts 端点（通过 ChatHistory 提供数据）
"""
import json
import logging
from typing import AsyncGenerator

from agent.context_compressor import ContextCompressor
from agent.react_engine import SimpleReActEngine
from agent.tool_registry import ToolRegistry, build_tool_registry
from llm.config import LLMConfig
from llm.service import LLMService
from services.chat_history import ChatHistoryService
from services.session_service import SessionService
from utils.trace_logger import TraceLogger

logger = logging.getLogger(__name__)

# ─── System Prompt ────────────────────────────────────────────────────────

_SYSTEM_BASE = """\
你是"看网报告助手"，专注于电信网络评估分析。你能帮助用户：
1. 生成网络评估大纲和报告
2. 对大纲进行裁剪、参数调整
3. 将专家看网逻辑沉淀为可复用能力

## 核心能力
- 理解用户的网络分析需求，自动匹配已沉淀的看网能力
- 支持复杂多步骤操作（生成大纲→裁剪→注入参数→执行数据→渲染报告）
- 通过设计态六步流程，将新的看网逻辑结构化并持久化

## 工作原则
- 每次行动前先用 get_session_status 了解当前会话状态
- 遇到复杂任务先用 read_skill_file 了解对应技能的工作流
- 裁剪或修改大纲后，如果已有报告，必须重新执行数据 + 渲染报告
- 只在用户明确确认"保存/沉淀"后才调用 persist_skill

<skill_system>
你有权访问以下看网技能。当任务匹配某个技能的使用场景时，
先调用 read_skill_file(<path>) 读取该技能的完整工作流指导，
然后按照指导顺序选择工具。

Progressive Loading：只在需要时读取，不要预先读取所有技能文件。

<available_skills>
  <skill>
    <name>skill-factory</name>
    <description>设计态六步流程：将专家看网逻辑（>80字自然语言）沉淀为可复用能力。用户输入大段看网逻辑时使用。</description>
    <path>skills/builtin/skill-factory/SKILL.md</path>
  </skill>
  <skill>
    <name>outline-operations</name>
    <description>运行态大纲操作：生成大纲、裁剪节点、注入参数。用户提出网络分析需求或要修改已有大纲时使用。</description>
    <path>skills/builtin/outline-generate/SKILL.md</path>
  </skill>
  <skill>
    <name>report-generation</name>
    <description>报告生成：执行数据查询 + HTML 渲染。需要生成或刷新报告时使用。</description>
    <path>skills/builtin/report-generate/SKILL.md</path>
  </skill>
</available_skills>
</skill_system>

## 响应风格
- 每步操作完成后简洁告知用户进展
- 报告/大纲生成完成后提示用户查看右侧面板
- 遇到错误时解释原因并提供解决建议
"""


class LeadAgent:

    def __init__(
        self,
        llm_service: LLMService,
        middleware_chain,           # MiddlewareChain（仍用于初始化 has_report 状态）
        skill_registry,             # SkillRegistry
        skill_loader,               # SkillLoader
        chat_history: ChatHistoryService,
        session_service: SessionService,
    ):
        self._llm = llm_service
        self._mw = middleware_chain
        self._reg = skill_registry
        self._loader = skill_loader
        self._ch = chat_history
        self._ss = session_service

        # 加载 LLM 配置
        from llm.config import _load
        react_config = _load("react_agent")
        compressor_config = _load("context_compressor")

        self._engine = SimpleReActEngine(
            llm_service=llm_service,
            react_config=react_config,
            compressor_config=compressor_config,
        )
        self._tool_registry: ToolRegistry = build_tool_registry(
            skill_loader=skill_loader,
            chat_history=chat_history,
            session_service=session_service,
            llm_service=llm_service,
        )

    async def handle_message(
        self, session_id: str, user_message: str
    ) -> AsyncGenerator[str, None]:
        await self._ch.ensure_session(session_id)
        await self._ch.add_message(session_id, "user", user_message)

        # 更新会话标题（首次对话）
        msgs = await self._ch.get_messages(session_id, limit=2)
        if len(msgs) <= 1:
            title = user_message[:20] + ("..." if len(user_message) > 20 else "")
            await self._ch.update_session_title(session_id, title)

        trace = TraceLogger(session_id=session_id)
        trace_cb = self._make_trace_callback(session_id, trace.trace_id)

        system_prompt = _SYSTEM_BASE

        async for event in self._engine.run(
            session_id=session_id,
            user_message=user_message,
            system_prompt=system_prompt,
            tool_registry=self._tool_registry,
            chat_history=self._ch,
            session_service=self._ss,
            skill_loader=self._loader,
            trace_callback=trace_cb,
        ):
            yield event

    def _make_trace_callback(self, session_id: str, trace_id: str):
        ch = self._ch

        async def callback(
            llm_type, step_name, request_messages, response_content,
            reasoning_content, model, temperature, elapsed_ms, success, error,
        ):
            await ch.save_llm_trace(
                session_id=session_id, trace_id=trace_id,
                llm_type=llm_type, step_name=step_name,
                request_messages=request_messages,
                response_content=response_content,
                reasoning_content=reasoning_content,
                model=model, temperature=temperature,
                elapsed_ms=elapsed_ms, success=success, error=error,
            )

        return callback
