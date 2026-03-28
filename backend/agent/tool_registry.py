"""ToolRegistry —— ReAct 引擎工具注册与执行。

每个工具对应一个 async handler，handler 内部复用现有 Executor。
返回值统一为 str（SSE 事件流）或最终文本（供 ToolMessage 使用）。

handler 签名:
  async def handler(tool_call: dict, context: ToolContext) -> AsyncGenerator[str, None]

tool_call:
  {"id": "...", "name": "...", "args": {...}}

ToolContext:
  session_id, skill_loader, chat_history, session_service, llm_service
  + 跨轮累积状态: current_outline, has_report, data_results, factory_context_key
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Optional

from agent.context import SkillContext, SkillResult

logger = logging.getLogger(__name__)


# ─── ToolContext ─────────────────────────────────────────────────────────

@dataclass
class ToolContext:
    """ReAct 轮次间共享的可变状态。"""
    session_id: str
    skill_loader: Any                    # SkillLoader
    chat_history: Any                    # ChatHistoryService
    session_service: Any                 # SessionService
    llm_service: Any                     # LLMService（用于 read_skill_file 等轻量调用）
    trace_callback: Optional[Callable] = None

    # 跨工具调用的累积状态
    current_outline: Optional[dict] = None
    has_report: bool = False
    data_results: dict = field(default_factory=dict)
    factory_context_key: str = ""        # persist_skill 使用


# ─── ToolRegistry ────────────────────────────────────────────────────────

class ToolRegistry:
    """工具注册中心。"""

    def __init__(self):
        self._handlers: dict[str, Callable] = {}

    def register(self, name: str, handler: Callable):
        self._handlers[name] = handler

    def has(self, name: str) -> bool:
        return name in self._handlers

    async def execute(
        self, tool_call: dict, ctx: ToolContext
    ) -> AsyncGenerator[str, None]:
        """执行工具调用，yield SSE 事件字符串。"""
        name = tool_call.get("name", "")
        handler = self._handlers.get(name)
        if not handler:
            yield json.dumps({"type": "tool_result", "name": name,
                              "content": f"未知工具: {name}", "success": False},
                             ensure_ascii=False)
            return
        try:
            async for chunk in handler(tool_call, ctx):
                yield chunk
        except Exception as e:
            logger.exception(f"工具 {name} 执行异常: {e}")
            yield json.dumps({"type": "tool_result", "name": name,
                              "content": f"工具执行失败: {e}", "success": False},
                             ensure_ascii=False)


# ─── 工具 handlers ────────────────────────────────────────────────────────

async def _handle_read_skill_file(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    path = tool_call["args"].get("path", "")
    yield json.dumps({"type": "tool_call", "name": "read_skill_file",
                      "args": {"path": path}}, ensure_ascii=False)
    try:
        # 相对路径基准：backend/ 工作目录
        if not os.path.isabs(path):
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            full_path = os.path.join(base, path)
        else:
            full_path = path
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        result = content[:8000]  # 限制长度
    except FileNotFoundError:
        result = f"文件不存在: {path}"
    except Exception as e:
        result = f"读取失败: {e}"
    yield json.dumps({"type": "tool_result", "name": "read_skill_file",
                      "content": result, "success": True}, ensure_ascii=False)


async def _handle_get_session_status(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    yield json.dumps({"type": "tool_call", "name": "get_session_status",
                      "args": {"session_id": sid}}, ensure_ascii=False)
    try:
        outline_state = await ctx.chat_history.get_outline_state(sid)
        has_outline = bool(outline_state and outline_state.get("outline_json"))
        if has_outline and ctx.current_outline is None:
            ctx.current_outline = outline_state.get("outline_json")

        # 检查 Redis 缓存 context
        factory_ctx_key = ""
        try:
            cached = await ctx.session_service.redis.get(f"skill_factory_ctx:{sid}")
            if cached:
                factory_ctx_key = sid
                ctx.factory_context_key = sid
        except Exception:
            pass

        status = {
            "has_outline": has_outline,
            "has_report": ctx.has_report,
            "has_cached_context": bool(factory_ctx_key),
            "context_key": factory_ctx_key or None,
            "current_outline_summary": _outline_summary(ctx.current_outline),
        }
        result = json.dumps(status, ensure_ascii=False)
    except Exception as e:
        result = f"获取状态失败: {e}"
    yield json.dumps({"type": "tool_result", "name": "get_session_status",
                      "content": result, "success": True}, ensure_ascii=False)


async def _handle_search_skill(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    query = tool_call["args"].get("query", "")
    yield json.dumps({"type": "tool_call", "name": "search_skill",
                      "args": {"query": query}}, ensure_ascii=False)

    executor = ctx.skill_loader.get_executor("outline-generate")
    if not executor:
        yield json.dumps({"type": "tool_result", "name": "search_skill",
                          "content": "outline-generate executor 未加载", "success": False},
                         ensure_ascii=False)
        return

    skill_ctx = _make_skill_ctx(sid, query, ctx)
    result_obj = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result_obj = item
        elif isinstance(item, str):
            yield item  # 转发业务 SSE 事件（outline_chunk 等）

    if result_obj and result_obj.success:
        ctx.current_outline = result_obj.data.get("subtree") or ctx.current_outline
        await ctx.chat_history.save_outline_state(
            sid,
            result_obj.data.get("subtree"),
            result_obj.data.get("anchor"),
        )
        content = result_obj.summary
    else:
        content = (result_obj.summary if result_obj else "搜索失败")

    yield json.dumps({"type": "tool_result", "name": "search_skill",
                      "content": content, "success": bool(result_obj and result_obj.success)},
                     ensure_ascii=False)


async def _handle_get_current_outline(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    yield json.dumps({"type": "tool_call", "name": "get_current_outline",
                      "args": {}}, ensure_ascii=False)
    try:
        if ctx.current_outline is None:
            state = await ctx.chat_history.get_outline_state(sid)
            ctx.current_outline = (state or {}).get("outline_json")
        content = (json.dumps(ctx.current_outline, ensure_ascii=False)
                   if ctx.current_outline else "当前会话尚无大纲")
    except Exception as e:
        content = f"获取大纲失败: {e}"
    yield json.dumps({"type": "tool_result", "name": "get_current_outline",
                      "content": content, "success": True}, ensure_ascii=False)


async def _handle_clip_outline(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    instruction = tool_call["args"].get("instruction", "")
    yield json.dumps({"type": "tool_call", "name": "clip_outline",
                      "args": {"instruction": instruction}}, ensure_ascii=False)

    executor = ctx.skill_loader.get_executor("outline-clip")
    if not executor:
        yield json.dumps({"type": "tool_result", "name": "clip_outline",
                          "content": "outline-clip executor 未加载", "success": False},
                         ensure_ascii=False)
        return

    skill_ctx = _make_skill_ctx(sid, instruction, ctx,
                                extra_params={"instructions": instruction})
    result_obj = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result_obj = item
        elif isinstance(item, str):
            yield item

    if result_obj and result_obj.success:
        new_outline = result_obj.data.get("updated_outline")
        if new_outline:
            ctx.current_outline = new_outline
            await ctx.chat_history.save_outline_state(sid, new_outline)
        yield json.dumps({"type": "outline_clipped", "success": True}, ensure_ascii=False)

    content = result_obj.summary if result_obj else "裁剪失败"
    yield json.dumps({"type": "tool_result", "name": "clip_outline",
                      "content": content,
                      "success": bool(result_obj and result_obj.success)},
                     ensure_ascii=False)


async def _handle_inject_params(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    param_updates = tool_call["args"].get("param_updates", {})
    yield json.dumps({"type": "tool_call", "name": "inject_params",
                      "args": {"param_updates": param_updates}}, ensure_ascii=False)

    executor = ctx.skill_loader.get_executor("param-inject")
    if not executor:
        yield json.dumps({"type": "tool_result", "name": "inject_params",
                          "content": "param-inject executor 未加载", "success": False},
                         ensure_ascii=False)
        return

    # 将 param_updates 字典展开为 executor 期望的参数格式
    for key, value in param_updates.items():
        skill_ctx = _make_skill_ctx(sid, "", ctx,
                                    extra_params={"param_key": key,
                                                  "param_value": json.dumps(value, ensure_ascii=False)
                                                  if not isinstance(value, str) else value})
        result_obj = None
        async for item in executor.execute(skill_ctx):
            if isinstance(item, SkillResult):
                result_obj = item
            elif isinstance(item, str):
                yield item

    content = f"参数已注入: {list(param_updates.keys())}"
    yield json.dumps({"type": "tool_result", "name": "inject_params",
                      "content": content, "success": True}, ensure_ascii=False)


async def _handle_execute_data(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    yield json.dumps({"type": "tool_call", "name": "execute_data",
                      "args": {}}, ensure_ascii=False)

    executor = ctx.skill_loader.get_executor("data-execute")
    if not executor:
        yield json.dumps({"type": "tool_result", "name": "execute_data",
                          "content": "data-execute executor 未加载", "success": False},
                         ensure_ascii=False)
        return

    skill_ctx = _make_skill_ctx(sid, "", ctx)
    result_obj = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result_obj = item
        elif isinstance(item, str):
            yield item

    if result_obj and result_obj.success:
        ctx.data_results = result_obj.data.get("data_results", {})

    content = result_obj.summary if result_obj else "数据执行失败"
    yield json.dumps({"type": "tool_result", "name": "execute_data",
                      "content": content,
                      "success": bool(result_obj and result_obj.success)},
                     ensure_ascii=False)


async def _handle_render_report(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    yield json.dumps({"type": "tool_call", "name": "render_report",
                      "args": {}}, ensure_ascii=False)

    executor = ctx.skill_loader.get_executor("report-generate")
    if not executor:
        yield json.dumps({"type": "tool_result", "name": "render_report",
                          "content": "report-generate executor 未加载", "success": False},
                         ensure_ascii=False)
        return

    skill_ctx = _make_skill_ctx(sid, "", ctx,
                                extra_params={"data_results": ctx.data_results})
    result_obj = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result_obj = item
        elif isinstance(item, str):
            yield item

    if result_obj and result_obj.success:
        ctx.has_report = True

    content = result_obj.summary if result_obj else "报告生成失败"
    yield json.dumps({"type": "tool_result", "name": "render_report",
                      "content": content,
                      "success": bool(result_obj and result_obj.success)},
                     ensure_ascii=False)


# ─── 设计态工具（skill-factory 子步骤） ──────────────────────────────────

async def _handle_understand_intent(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    expert_input = tool_call["args"].get("expert_input", "")
    yield json.dumps({"type": "tool_call", "name": "understand_intent",
                      "args": {"expert_input": expert_input[:100] + "..."}}, ensure_ascii=False)
    async for chunk in _run_factory_step(ctx, sid, "full", expert_input, stop_after="intent"):
        yield chunk


async def _handle_extract_structure(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    raw_input = tool_call["args"].get("raw_input", "")
    yield json.dumps({"type": "tool_call", "name": "extract_structure",
                      "args": {}}, ensure_ascii=False)
    async for chunk in _run_factory_step(ctx, sid, "full", raw_input, stop_after="struct"):
        yield chunk


async def _handle_design_outline(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    structured_text = tool_call["args"].get("structured_text", "")
    yield json.dumps({"type": "tool_call", "name": "design_outline",
                      "args": {}}, ensure_ascii=False)
    async for chunk in _run_factory_step(ctx, sid, "full", structured_text,
                                         stop_after="outline"):
        yield chunk


async def _handle_preview_report(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    yield json.dumps({"type": "tool_call", "name": "preview_report",
                      "args": {}}, ensure_ascii=False)
    async for chunk in _run_factory_step(ctx, sid, "preview_only", "", stop_after="preview"):
        yield chunk


async def _handle_persist_skill(
    tool_call: dict, ctx: ToolContext
) -> AsyncGenerator[str, None]:
    sid = tool_call["args"].get("session_id", ctx.session_id)
    context_key = tool_call["args"].get("context_key", ctx.factory_context_key or sid)
    yield json.dumps({"type": "tool_call", "name": "persist_skill",
                      "args": {"context_key": context_key}}, ensure_ascii=False)

    executor = ctx.skill_loader.get_executor("skill-factory")
    if not executor:
        yield json.dumps({"type": "tool_result", "name": "persist_skill",
                          "content": "skill-factory executor 未加载", "success": False},
                         ensure_ascii=False)
        return

    skill_ctx = _make_skill_ctx(sid, "", ctx,
                                extra_params={"mode": "persist_only", "saved_context": context_key})
    result_obj = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result_obj = item
        elif isinstance(item, str):
            yield item

    content = result_obj.summary if result_obj else "沉淀失败"
    yield json.dumps({"type": "tool_result", "name": "persist_skill",
                      "content": content,
                      "success": bool(result_obj and result_obj.success)},
                     ensure_ascii=False)


# ─── 辅助函数 ────────────────────────────────────────────────────────────

def _make_skill_ctx(
    sid: str,
    user_message: str,
    ctx: ToolContext,
    extra_params: dict | None = None,
) -> SkillContext:
    return SkillContext(
        session_id=sid,
        user_message=user_message,
        params=extra_params or {},
        current_outline=ctx.current_outline,
        trace_callback=ctx.trace_callback,
    )


def _outline_summary(outline: dict | None, max_nodes: int = 5) -> str:
    if not outline:
        return "无"
    nodes = []

    def _walk(node, depth=0):
        if len(nodes) >= max_nodes:
            return
        indent = "  " * depth
        nodes.append(f"{indent}{node.get('name', '')}")
        for child in (node.get("children") or []):
            _walk(child, depth + 1)

    _walk(outline)
    return "\n".join(nodes)


async def _run_factory_step(
    ctx: ToolContext,
    sid: str,
    mode: str,
    expert_input: str,
    stop_after: str,
) -> AsyncGenerator[str, None]:
    """
    运行 skill-factory 完整流程但在 stop_after 步骤后停止。
    stop_after: "intent" | "struct" | "outline" | "preview"
    """
    executor = ctx.skill_loader.get_executor("skill-factory")
    if not executor:
        yield json.dumps({"type": "tool_result", "name": "skill_factory_step",
                          "content": "skill-factory executor 未加载", "success": False},
                         ensure_ascii=False)
        return

    # 设计态步骤通过 full 模式运行到对应步骤
    # 将 stop_after 映射为步骤名，executor 内部通过 design_step 事件上报进度
    skill_ctx = _make_skill_ctx(
        sid, expert_input, ctx,
        extra_params={
            "mode": mode,
            "expert_input": expert_input,
            "_stop_after": stop_after,   # executor 检测此参数决定是否中途停止
        },
    )
    result_obj = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result_obj = item
            # 若有 context_key，存入 ToolContext
            if result_obj.data.get("context_key"):
                ctx.factory_context_key = result_obj.data["context_key"]
        elif isinstance(item, str):
            yield item

    content = result_obj.summary if result_obj else f"步骤 {stop_after} 执行失败"
    yield json.dumps({"type": "tool_result", "name": f"factory_{stop_after}",
                      "content": content,
                      "success": bool(result_obj and result_obj.success)},
                     ensure_ascii=False)


# ─── 工厂函数 ─────────────────────────────────────────────────────────────

def build_tool_registry(skill_loader, chat_history, session_service, llm_service) -> ToolRegistry:
    """组装并返回 ToolRegistry 实例。"""
    reg = ToolRegistry()
    reg.register("read_skill_file", _handle_read_skill_file)
    reg.register("get_session_status", _handle_get_session_status)
    reg.register("search_skill", _handle_search_skill)
    reg.register("get_current_outline", _handle_get_current_outline)
    reg.register("clip_outline", _handle_clip_outline)
    reg.register("inject_params", _handle_inject_params)
    reg.register("execute_data", _handle_execute_data)
    reg.register("render_report", _handle_render_report)
    reg.register("understand_intent", _handle_understand_intent)
    reg.register("extract_structure", _handle_extract_structure)
    reg.register("design_outline", _handle_design_outline)
    reg.register("preview_report", _handle_preview_report)
    reg.register("persist_skill", _handle_persist_skill)
    return reg
