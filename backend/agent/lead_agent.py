"""Lead Agent —— 基于 SimpleReActEngine 的 ReAct 循环架构。

替代旧的 Plan → Execute → Reflect 架构：
  LLM 自主决策工具调用 → 执行工具 → 观察结果 → 继续决策

保留的功能：
  - 中间件链（历史/大纲状态/待确认）
  - L5 层级确认 (_confirm)
  - 状态持久化 (_persist)
  - SSE 事件兼容（tool_call/tool_result 为新增，旧事件仍透传）
  - Memory 注入（<memory> 块）
"""
import json
import logging
from typing import AsyncGenerator, Optional

from agent.context import AgentContext, SkillContext
from agent.middleware.base import MiddlewareChain
from agent.react_engine import SimpleReActEngine
from agent.skill_registry import SkillRegistry
from agent.skill_loader import SkillLoader
from agent.tool_registry import ToolContext, ToolRegistry
from agent.tool_definitions import register_all_tools
from llm.service import LLMService
from services.chat_history import ChatHistoryService
from services.session_service import SessionService
from utils.trace_logger import TraceLogger

logger = logging.getLogger(__name__)

# ─── System Prompt 基础指令 ───
BASE_INSTRUCTIONS = """\
你是智能看网报告助手。帮助用户生成网络分析大纲和报告，并支持专家将看网逻辑固化为可复用能力。

## 核心工作方式
1. 首先调用 get_session_status 了解当前会话状态
2. 根据用户意图选择合适的工具序列
3. 复杂任务前先调用 read_skill_file 阅读对应技能的工作流指导

## 意图识别规则
- 用户询问网络分析/评估 → search_skill(query)，完成后向用户展示大纲并询问是否生成报告
- 用户明确要求生成报告（"生成报告"/"帮我出报告"等）→ execute_data + render_report
- 用户要求删除/不看某节点 → clip_outline，裁剪完成后询问用户是否重新生成报告
- 用户修改参数/阈值/过滤条件 → inject_params，注入完成后询问用户是否重新生成报告
- 用户输入 >80 字看网逻辑（经验描述）→ 调用 understand_intent(expert_input) 启动设计态，严格按 SKILL.md 指导逐步执行，完成第五步后停止并询问用户
- 用户说"保存/沉淀/确认保存" → persist_skill（仅此时才调用）

## 关键约束【严格遵守，不得违反】
- 【禁止】search_skill 完成后自动调用 execute_data/render_report，必须先询问用户
- 【禁止】clip_outline 或 inject_params 完成后自动调用 execute_data/render_report，必须先询问用户
- 【禁止】skill-factory 五步完成后自动调用 persist_skill，预览完成后必须询问用户是否保存
- 生成报告必须先执行 execute_data，再执行 render_report（此顺序不可颠倒）
- persist_skill 必须等用户明确说"保存/沉淀/确认保存"后才调用，绝不主动触发
"""

# ─── Skill System Prompt 段落（由 SkillRegistry 生成）───
SKILL_SYSTEM_TEMPLATE = """\
<skill_system>
调用工具时，遇到复杂任务先用 read_skill_file(<skill_name>) 阅读工作流指导。
只在需要时读取，不要预先读取所有技能。

<available_skills>
{skill_entries}
</available_skills>
</skill_system>"""


class LeadAgent:

    def __init__(
        self,
        llm_service: LLMService,
        middleware_chain: MiddlewareChain,
        skill_registry: SkillRegistry,
        skill_loader: SkillLoader,
        chat_history: ChatHistoryService,
        session_service: SessionService,
        memory_store=None,    # Optional[MemoryStore]
        memory_updater=None,  # Optional[MemoryUpdater]
    ):
        self._llm = llm_service
        self._mw = middleware_chain
        self._reg = skill_registry
        self._loader = skill_loader
        self._ch = chat_history
        self._ss = session_service
        self._memory = memory_store
        self._memory_updater = memory_updater

        # 构建 ToolRegistry
        self._tool_registry = ToolRegistry()
        register_all_tools(self._tool_registry)

        # 构建 ReAct 引擎
        self._engine = SimpleReActEngine(llm_service, self._tool_registry)

        # 预生成技能系统 prompt 段落
        self._skill_system_prompt = self._build_skill_system_prompt()

    def _build_skill_system_prompt(self) -> str:
        """生成 <skill_system> 块，列出所有已启用技能的路径和描述。"""
        enabled = [s for s in self._reg.get_enabled() if s.source == "builtin"]
        # 也包含 custom skills
        custom = [s for s in self._reg.get_enabled() if s.source == "custom"]
        all_skills = enabled + custom

        entries = []
        for s in all_skills:
            entries.append(
                f'  <skill>\n'
                f'    <name>{s.name}</name>\n'
                f'    <description>{s.description}</description>\n'
                f'    <path>{s.skill_md_path}</path>\n'
                f'  </skill>'
            )
        return SKILL_SYSTEM_TEMPLATE.format(skill_entries="\n".join(entries))

    def _build_system_prompt(self, memory_block: str = "") -> str:
        """组装完整 system prompt。"""
        parts = [BASE_INSTRUCTIONS]
        if memory_block:
            parts.append(f"\n<memory>\n{memory_block}\n</memory>")
        parts.append(f"\n{self._skill_system_prompt}")
        return "\n".join(parts)

    def _make_trace_callback(self, session_id: str, trace_id: str):
        ch = self._ch
        async def callback(llm_type, step_name, request_messages, response_content,
                           reasoning_content, model, temperature, elapsed_ms, success, error):
            await ch.save_llm_trace(
                session_id=session_id, trace_id=trace_id,
                llm_type=llm_type, step_name=step_name,
                request_messages=request_messages, response_content=response_content,
                reasoning_content=reasoning_content, model=model, temperature=temperature,
                elapsed_ms=elapsed_ms, success=success, error=error,
            )
        return callback

    async def handle_message(self, session_id: str, user_message: str) -> AsyncGenerator[str, None]:
        await self._ch.ensure_session(session_id)
        await self._ch.add_message(session_id, "user", user_message)
        trace = TraceLogger(session_id=session_id)
        trace.log("request.start", data={"user_message": user_message})

        # 设置会话标题（首条消息）
        msgs = await self._ch.get_messages(session_id, limit=2)
        if len(msgs) <= 1:
            title = user_message[:20] + ("..." if len(user_message) > 20 else "")
            await self._ch.update_session_title(session_id, title)

        trace_cb = self._make_trace_callback(session_id, trace.trace_id)

        # ─── 中间件链：填充上下文 ───
        ctx = AgentContext(session_id=session_id, user_message=user_message, trace_id=trace.trace_id)
        ctx = await self._mw.run_before(ctx)

        # ─── 检查 L5 待确认 ───
        if ctx.has_pending_confirm and ctx.pending_confirm_options:
            # 判断用户是否在回答确认（A/B/C 或选择描述）
            if self._is_confirm_reply(user_message):
                async for ev in self._confirm(ctx, user_message, trace_cb):
                    yield ev
                yield self._ev("done")
                return

        # ─── 构建 Memory 块 ───
        memory_block = ""
        if self._memory:
            try:
                memory_block = self._memory.format_for_injection(max_tokens=2000)
            except Exception as e:
                logger.warning(f"Memory 格式化失败，跳过注入: {e}")

        system_prompt = self._build_system_prompt(memory_block)

        # ─── 构建 ToolContext ───
        tool_ctx = ToolContext(
            session_id=session_id,
            loader=self._loader,
            registry=self._reg,
            chat_history=self._ch,
            session_service=self._ss,
            container=None,
            trace_callback=trace_cb,
            current_outline=ctx.current_outline,
            has_outline=ctx.has_outline,
            has_report=ctx.has_report,
        )
        tool_ctx._trace_id = trace.trace_id  # 传给 engine 用于 tool_call_traces

        # ─── 运行 ReAct 引擎 ───
        reply_content = ""
        collected_thinking: list[dict] = []
        report_html = ""
        report_title = ""
        outline_md = ""
        _outline_building = False  # 追踪是否在新一轮大纲流中

        async for sse_str in self._engine.run(
            session_id=session_id,
            user_message=user_message,
            system_prompt=system_prompt,
            chat_history=ctx.chat_history,
            tool_ctx=tool_ctx,
            trace_callback=trace_cb,
        ):
            yield sse_str
            # 收集最终回复内容和产物，用于持久化
            try:
                p = json.loads(sse_str)
                t = p.get("type", "")
                if t == "chat_reply":
                    reply_content = p.get("content", "")
                elif t == "thinking_step":
                    e = {"step": p["step"], "status": p["status"], "detail": p["detail"], "data": p.get("data")}
                    if e["status"] == "done":
                        for idx in range(len(collected_thinking) - 1, -1, -1):
                            if collected_thinking[idx]["step"] == e["step"] and collected_thinking[idx]["status"] == "running":
                                collected_thinking[idx] = e
                                break
                        else:
                            collected_thinking.append(e)
                    else:
                        collected_thinking.append(e)
                elif t == "outline_done":
                    _outline_building = False  # 本轮大纲流结束
                elif t == "report_done":
                    report_title = p.get("title", "报告")
                elif t == "outline_chunk":
                    if not _outline_building:
                        # 新一轮大纲流开始（clip/search 产生新大纲），清空旧内容
                        outline_md = ""
                        _outline_building = True
                    outline_md += p.get("content", "")
                elif t == "report_chunk":
                    report_html += p.get("content", "")
            except Exception as e:
                logger.debug(f"SSE 事件解析失败（跳过）: {e} raw={sse_str[:100]!r}")

        # ─── 保存助手消息 + 产物 metadata ───
        meta: dict = {}
        if collected_thinking:
            meta["thinking"] = collected_thinking
        if outline_md:
            meta["outline_md"] = outline_md
        if report_html:
            meta["report_html"] = report_html
            meta["report_title"] = report_title or "报告"
        if tool_ctx.has_report and not report_html:
            # 报告由工具内部直接落库，未经 report_chunk SSE 流出
            logger.warning(f"has_report=True 但 report_html 为空，报告可能由 executor 直接落库 session={session_id}")

        await self._ch.add_message(
            session_id, "assistant",
            reply_content or "已处理完毕。",
            msg_type="text",
            metadata=meta if meta else None,
        )

        # ─── Memory 异步更新 ───
        if self._memory_updater:
            try:
                await self._memory_updater.enqueue_update(session_id, user_message, reply_content)
            except Exception as e:
                logger.warning(f"Memory 更新入队失败: {e}")

        yield self._ev("done")

    def _is_confirm_reply(self, message: str) -> bool:
        """判断用户回复是否是 L5 层级确认。"""
        msg = message.strip().upper()
        return msg in ("A", "B", "C") or any(
            kw in message for kw in ["选择", "选A", "选B", "选C", "第一", "第二", "第三"]
        )

    async def _confirm(self, ctx: AgentContext, user_message: str, trace_cb=None) -> AsyncGenerator[str, None]:
        """处理 L5 层级确认。"""
        pending = ctx.pending_confirm_options
        if not pending:
            yield self._ev("chat_reply", content="确认已超时，请重新开始。")
            return

        # 解析用户选择
        node_id = None
        msg = user_message.strip().upper()
        option_map = {"A": 0, "B": 1, "C": 2}
        if msg in option_map:
            idx = option_map[msg]
            if idx < len(pending):
                node_id = pending[idx].get("id")
        if not node_id:
            for o in pending:
                if o.get("name", "") in user_message or o.get("label", "") in user_message:
                    node_id = o.get("id")
                    break
        if not node_id:
            yield self._ev("chat_reply", content="未识别您的选择，请回复 A、B 或 C。")
            return

        await self._ss.delete_pending_confirm(ctx.session_id)
        yield self._ev("chat_reply", content="正在生成大纲...")

        executor = self._loader.get_executor("outline-generate")
        if executor and hasattr(executor, "execute_from_node"):
            from agent.context import SkillResult
            result = None
            async for item in executor.execute_from_node(
                SkillContext(session_id=ctx.session_id, user_message="", trace_callback=trace_cb),
                node_id,
            ):
                if isinstance(item, SkillResult):
                    result = item
                elif isinstance(item, str):
                    yield item
            if result and result.success:
                await self._ch.save_outline_state(
                    ctx.session_id,
                    result.data.get("subtree"),
                    result.data.get("anchor"),
                )
                yield self._ev("chat_reply", content="大纲已生成，请查看右侧面板。")
                await self._ch.add_message(ctx.session_id, "assistant", "已生成大纲", msg_type="outline")

    @staticmethod
    def _ev(t: str, **kw) -> str:
        return json.dumps({"type": t, **kw}, ensure_ascii=False)
