"""工具定义 —— 12 个 ReAct 工具的 schema + 执行函数。

每个工具函数签名：
  async def fn(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]
  yield {"sse": str}          → 透传 SSE 事件
  yield {"result": SkillResult}  → 工具执行结果（最后一次）

工具分类：
  基础工具：read_skill_file, get_session_status
  运行态：search_skill, get_current_outline, clip_outline, inject_params, execute_data, render_report
  设计态：understand_intent, extract_structure, design_outline, bind_data, preview_report, persist_skill
"""

import json
import logging
import os
from typing import AsyncGenerator

from agent.context import SkillContext, SkillResult
from agent.tool_registry import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 基础工具
# ─────────────────────────────────────────────────────────────────────────────

async def _read_skill_file(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    path = args.get("path", "")
    if not path:
        yield {"result": SkillResult(False, "缺少 path 参数")}
        return
    try:
        # 优先从 registry 按名称读取
        content = tool_ctx.registry.load_full_content(path)
        if not content and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        if content:
            yield {"result": SkillResult(True, f"已读取 {path}", data={"content": content})}
        else:
            yield {"result": SkillResult(False, f"未找到文件: {path}")}
    except Exception as e:
        logger.error(f"read_skill_file 失败 path={path}: {e}", exc_info=True)
        yield {"result": SkillResult(False, f"读取失败: {e}")}


async def _get_session_status(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    sid = tool_ctx.session_id
    try:
        has_outline = await tool_ctx.chat_history.has_outline(sid)
        outline_state = await tool_ctx.chat_history.get_outline_state(sid) if has_outline else None
        has_report = tool_ctx.has_report
        # 检查 skill-factory 缓存
        cached_ctx_key = ""
        try:
            cached = await tool_ctx.session_service.redis.get(f"skill_factory_ctx:{sid}")
            if cached:
                cached_ctx_key = sid
        except Exception as e:
            logger.debug(f"Redis 缓存检查失败（可忽略）: {e}")
        # 检查 pending_confirm
        pending = await tool_ctx.session_service.get_pending_confirm(sid)

        status = {
            "has_outline": has_outline,
            "has_report": has_report,
            "has_cached_context": bool(cached_ctx_key),
            "cached_context_key": cached_ctx_key or "",
            "has_pending_confirm": bool(pending),
            "outline_summary": "",
        }
        if outline_state and outline_state.get("outline_json"):
            tree = outline_state["outline_json"]
            names = []
            def _collect(node, depth=0):
                if depth > 2: return
                if node.get("name"): names.append(node["name"])
                for c in node.get("children", []): _collect(c, depth + 1)
            _collect(tree)
            status["outline_summary"] = "、".join(names[:5])

        yield {"result": SkillResult(True, "已获取会话状态", data=status)}
    except Exception as e:
        logger.error(f"get_session_status 失败 session={tool_ctx.session_id}: {e}", exc_info=True)
        yield {"result": SkillResult(False, f"获取状态失败: {e}")}


# ─────────────────────────────────────────────────────────────────────────────
# 运行态工具
# ─────────────────────────────────────────────────────────────────────────────

async def _search_skill(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    query = args.get("query", "")
    if not query:
        yield {"result": SkillResult(False, "缺少 query 参数")}
        return

    executor = tool_ctx.loader.get_executor("outline-generate")
    if not executor:
        logger.error("search_skill: outline-generate 执行器未加载")
        yield {"result": SkillResult(False, "outline-generate 执行器未加载")}
        return

    logger.info(f"search_skill: query={query!r} session={tool_ctx.session_id}")
    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message=query,
        params={"query": query},
        trace_callback=tool_ctx.trace_callback,
    )
    result = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result = item
            if result.success:
                tool_ctx.current_outline = result.data.get("subtree")
                tool_ctx.has_outline = True
                # 持久化大纲状态
                if result.data.get("subtree") and result.data.get("anchor"):
                    await tool_ctx.chat_history.save_outline_state(
                        tool_ctx.session_id,
                        result.data["subtree"],
                        result.data.get("anchor"),
                    )
        elif isinstance(item, str):
            yield {"sse": item}

    final = result or SkillResult(False, "大纲搜索失败")
    logger.info(f"search_skill: 完成 success={final.success} summary={final.summary!r}")
    yield {"result": final}


async def _get_current_outline(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    try:
        state = await tool_ctx.chat_history.get_outline_state(tool_ctx.session_id)
        if state and state.get("outline_json"):
            yield {"result": SkillResult(True, "已获取大纲", data={
                "outline_json": state["outline_json"],
                "anchor_info": state.get("anchor_info"),
            })}
        else:
            yield {"result": SkillResult(False, "当前会话没有大纲")}
    except Exception as e:
        logger.error(f"get_current_outline 失败 session={tool_ctx.session_id}: {e}", exc_info=True)
        yield {"result": SkillResult(False, f"获取大纲失败: {e}")}


async def _clip_outline(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    instruction = args.get("instruction", "")
    if not instruction:
        yield {"result": SkillResult(False, "缺少 instruction 参数")}
        return

    executor = tool_ctx.loader.get_executor("outline-clip")
    if not executor:
        yield {"result": SkillResult(False, "outline-clip 执行器未加载")}
        return

    # 获取当前大纲
    state = await tool_ctx.chat_history.get_outline_state(tool_ctx.session_id)
    current_outline = state.get("outline_json") if state else tool_ctx.current_outline

    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message=instruction,
        params={"instructions": instruction},
        current_outline=current_outline,
        trace_callback=tool_ctx.trace_callback,
    )
    result = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result = item
            if result.success and result.data.get("updated_outline"):
                tool_ctx.current_outline = result.data["updated_outline"]
                await tool_ctx.chat_history.save_outline_state(
                    tool_ctx.session_id, result.data["updated_outline"]
                )
        elif isinstance(item, str):
            yield {"sse": item}

    yield {"result": result or SkillResult(False, "大纲裁剪失败")}


async def _inject_params(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    param_key = args.get("param_key", "")
    param_value = args.get("param_value", "")
    target_node = args.get("target_node", "")
    if not param_key:
        yield {"result": SkillResult(False, "缺少 param_key 参数")}
        return

    executor = tool_ctx.loader.get_executor("param-inject")
    if not executor:
        yield {"result": SkillResult(False, "param-inject 执行器未加载")}
        return

    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message="",
        params={"param_key": param_key, "param_value": param_value, "target_node": target_node},
        trace_callback=tool_ctx.trace_callback,
    )
    result = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result = item
        elif isinstance(item, str):
            yield {"sse": item}

    yield {"result": result or SkillResult(False, "参数注入失败")}


async def _execute_data(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    executor = tool_ctx.loader.get_executor("data-execute")
    if not executor:
        yield {"result": SkillResult(False, "data-execute 执行器未加载")}
        return

    state = await tool_ctx.chat_history.get_outline_state(tool_ctx.session_id)
    current_outline = state.get("outline_json") if state else tool_ctx.current_outline

    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message="",
        params={},
        current_outline=current_outline,
        trace_callback=tool_ctx.trace_callback,
    )
    result = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result = item
            tool_ctx.step_results["data_results"] = result.data.get("data_results", {})
        elif isinstance(item, str):
            yield {"sse": item}

    final = result or SkillResult(False, "数据执行失败")
    logger.info(f"execute_data: 完成 success={final.success} session={tool_ctx.session_id}")
    yield {"result": final}


async def _render_report(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    executor = tool_ctx.loader.get_executor("report-generate")
    if not executor:
        yield {"result": SkillResult(False, "report-generate 执行器未加载")}
        return

    state = await tool_ctx.chat_history.get_outline_state(tool_ctx.session_id)
    current_outline = state.get("outline_json") if state else tool_ctx.current_outline

    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message="",
        params={},
        current_outline=current_outline,
        step_results=tool_ctx.step_results,
        trace_callback=tool_ctx.trace_callback,
    )
    result = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result = item
            if result.success and result.data.get("report_html"):
                tool_ctx.has_report = True
        elif isinstance(item, str):
            yield {"sse": item}

    final = result or SkillResult(False, "报告生成失败")
    logger.info(f"render_report: 完成 success={final.success} session={tool_ctx.session_id}")
    yield {"result": final}


# ─────────────────────────────────────────────────────────────────────────────
# 设计态工具（skill-factory 六步）
# 使用 skill-factory 执行器的子步骤模式
# ─────────────────────────────────────────────────────────────────────────────

async def _run_skill_factory_step(
    step_name: str, args: dict, tool_ctx: ToolContext
) -> AsyncGenerator[dict, None]:
    """通用的 skill-factory 单步执行代理。"""
    executor = tool_ctx.loader.get_executor("skill-factory")
    if not executor:
        yield {"result": SkillResult(False, "skill-factory 执行器未加载")}
        return

    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message=args.get("expert_input", ""),
        params={**args, "_single_step": step_name},
        current_outline=tool_ctx.current_outline,
        trace_callback=tool_ctx.trace_callback,
        step_results=tool_ctx.step_results,
    )
    result = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result = item
        elif isinstance(item, str):
            yield {"sse": item}

    yield {"result": result or SkillResult(False, f"{step_name} 执行失败")}


async def _understand_intent(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    """启动完整设计态流程（preview_only：步骤1-5）。完成后系统发送沉淀确认提示，等待用户决策。"""
    expert_input = args.get("expert_input", "")
    if not expert_input:
        yield {"result": SkillResult(False, "缺少 expert_input 参数")}
        return

    executor = tool_ctx.loader.get_executor("skill-factory")
    if not executor:
        logger.error("understand_intent: skill-factory 执行器未加载")
        yield {"result": SkillResult(False, "skill-factory 执行器未加载")}
        return

    logger.info(f"understand_intent: 启动 preview_only 流程 session={tool_ctx.session_id}")
    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message=expert_input,
        params={"mode": "preview_only", "expert_input": expert_input},
        current_outline=tool_ctx.current_outline,
        trace_callback=tool_ctx.trace_callback,
    )
    result = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result = item
        elif isinstance(item, str):
            yield {"sse": item}

    final = result or SkillResult(False, "设计态流程失败")
    logger.info(f"understand_intent: 完成 success={final.success}")

    # 将 skill-factory 生成的大纲持久化到会话，使后续 clip/status 能正确识别
    if final.success and final.data.get("outline_json"):
        try:
            await tool_ctx.chat_history.save_outline_state(
                tool_ctx.session_id,
                final.data["outline_json"],
            )
            tool_ctx.has_outline = True
            tool_ctx.current_outline = final.data["outline_json"]
            logger.info(f"understand_intent: 大纲已持久化到会话 session={tool_ctx.session_id}")
        except Exception as e:
            logger.warning(f"understand_intent: 大纲持久化失败（可忽略）: {e}")

    yield {"result": final}


# ── 以下分步工具在 executor 中无法单独执行（_single_step 参数从未在 executor 实现），
#    已整合到 understand_intent(preview_only) 中。保留空壳避免 LLM 误调时报硬错误。

async def _extract_structure(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    yield {"result": SkillResult(False, "此步骤已整合到 understand_intent，请勿单独调用")}

async def _design_outline(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    yield {"result": SkillResult(False, "此步骤已整合到 understand_intent，请勿单独调用")}

async def _bind_data(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    yield {"result": SkillResult(False, "此步骤已整合到 understand_intent，请勿单独调用")}

async def _preview_report(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    yield {"result": SkillResult(False, "此步骤已整合到 understand_intent，请勿单独调用")}


async def _persist_skill(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    context_key = args.get("context_key", tool_ctx.session_id)
    executor = tool_ctx.loader.get_executor("skill-factory")
    if not executor:
        yield {"result": SkillResult(False, "skill-factory 执行器未加载")}
        return

    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message="",
        params={"mode": "persist_only", "saved_context": context_key},
        trace_callback=tool_ctx.trace_callback,
    )
    result = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result = item
        elif isinstance(item, str):
            yield {"sse": item}

    yield {"result": result or SkillResult(False, "能力沉淀失败")}


# ─────────────────────────────────────────────────────────────────────────────
# 注册入口
# ─────────────────────────────────────────────────────────────────────────────

def register_all_tools(registry: ToolRegistry):
    """注册所有工具到 ToolRegistry。"""

    # ── 基础工具 ──
    registry.register(
        name="read_skill_file",
        description=(
            "读取指定路径的 SKILL.md 文件全文。执行复杂的看网分析任务前，"
            "先调用此工具了解该技能的完整工作流和步骤要求。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "技能名称（如 skill-factory）或 SKILL.md 文件路径"},
            },
            "required": ["path"],
        },
        fn=_read_skill_file,
    )

    registry.register(
        name="get_session_status",
        description=(
            "获取当前会话状态：是否已有大纲、是否已有报告、是否有待沉淀的设计态缓存、"
            "是否有待用户确认的层级选择。在规划下一步操作前调用。"
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        fn=_get_session_status,
    )

    # ── 运行态工具 ──
    registry.register(
        name="search_skill",
        description=(
            "在知识库中搜索与用户问题匹配的已沉淀看网能力，返回结构化大纲。"
            "用户提出网络分析需求时首先调用此工具。"
            "若匹配成功则加载已沉淀大纲；否则通过 GraphRAG 生成临时大纲。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用户的分析需求描述"},
            },
            "required": ["query"],
        },
        fn=_search_skill,
    )

    registry.register(
        name="get_current_outline",
        description="获取当前会话的完整大纲 JSON。在执行裁剪、参数注入或报告生成前调用以了解现有大纲结构。",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        fn=_get_current_outline,
    )

    registry.register(
        name="clip_outline",
        description=(
            "按裁剪指令删除、筛选或保留大纲节点。"
            "用户说'不看XX/删除XX/去掉XX'时调用。"
            "执行后必须重新调用 execute_data + render_report 刷新报告。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "instruction": {"type": "string", "description": "裁剪指令，如'删除低阶交叉节点'"},
            },
            "required": ["instruction"],
        },
        fn=_clip_outline,
    )

    registry.register(
        name="inject_params",
        description=(
            "注入运行时过滤参数（行业筛选/阈值修改等）。"
            "用户说'只看XX行业/阈值改为XX'时调用。"
            "执行后必须重新调用 execute_data + render_report 刷新报告。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "param_key": {"type": "string", "description": "参数名，如 industry/threshold"},
                "param_value": {"type": "string", "description": "参数值"},
                "target_node": {"type": "string", "description": "目标节点名（可选，为空则全局注入）"},
            },
            "required": ["param_key", "param_value"],
        },
        fn=_inject_params,
    )

    registry.register(
        name="execute_data",
        description=(
            "执行大纲中所有评估指标的数据查询（SQL/API/Mock）。"
            "生成报告前必须先调用此工具获取数据。"
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        fn=_execute_data,
    )

    registry.register(
        name="render_report",
        description=(
            "基于当前大纲和数据结果生成 HTML 报告。"
            "这是生成报告的最后一步，必须在 execute_data 之后调用。"
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        fn=_render_report,
    )

    # ── 设计态工具（skill-factory 六步）──
    registry.register(
        name="understand_intent",
        description=(
            "执行完整看网能力设计流程（五步：意图理解→结构提取→大纲设计→数据绑定→报告预览）。"
            "用户输入超过 80 字的看网逻辑描述时调用此工具。"
            "流程完成后系统自动向用户发送沉淀确认提示，等待用户决定是否保存为可复用能力。"
            "【重要】此工具调用完成后，不得再调用 persist_skill，必须等待用户明确回复。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "expert_input": {"type": "string", "description": "专家输入的看网逻辑文本（完整原文）"},
            },
            "required": ["expert_input"],
        },
        fn=_understand_intent,
    )

    registry.register(
        name="persist_skill",
        description=(
            "将设计态成果沉淀为可复用看网能力并写入系统。"
            "【重要】仅在用户明确说'保存/沉淀/确认保存'时才调用此工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "context_key": {"type": "string", "description": "缓存 key（通常为 session_id，可从 get_session_status 获取）"},
            },
            "required": [],
        },
        fn=_persist_skill,
    )
