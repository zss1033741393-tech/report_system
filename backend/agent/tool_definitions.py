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
import re
from typing import AsyncGenerator

from agent.context import SkillContext, SkillResult
from agent.tool_registry import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)


def _query_matches_anchor(query: str, anchor_name: str) -> bool:
    """检查查询内容与锚点名称是否有字符级关联。

    用于过滤 L1 级别的降级误匹配：当 LLM 无法找到精确锚点时会选
    顶层宽泛节点（L1），此时锚点名与用户意图往往毫无关联。
    策略：提取锚点名中的中文 2-gram 和长度≥3 的英文词，
    若均不出现在 query 中则判定为无关。
    """
    if not anchor_name:
        return False
    # 中文 2-gram 滑动匹配
    zh_segs = re.findall(r'[\u4e00-\u9fff]+', anchor_name)
    for seg in zh_segs:
        for i in range(len(seg) - 1):
            if seg[i:i + 2] in query:
                return True
    # 英文/数字词（长度≥3）大小写不敏感
    en_words = re.findall(r'[A-Za-z0-9]+', anchor_name)
    for word in en_words:
        if len(word) >= 3 and word.lower() in query.lower():
            return True
    return False


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
                subtree = result.data.get("subtree")
                if subtree:
                    anchor = result.data.get("anchor") or {}
                    anchor_level = anchor.get("level", -1)
                    anchor_name = anchor.get("name", "")

                    # L1 降级误匹配检测：顶层宽泛节点且与查询无字符关联，
                    # 说明知识库中没有与用户意图匹配的具体场景。
                    if anchor_level <= 1 and not _query_matches_anchor(query, anchor_name):
                        logger.warning(
                            f"search_skill: L1 降级误匹配，拒绝 anchor={anchor_name!r} query={query!r}"
                        )
                        result = SkillResult(
                            False,
                            f"未在知识库中找到与「{query}」直接匹配的分析场景。"
                            f"请尝试更具体的描述，例如：「帮我分析fgOTN部署机会」"
                            f"或「分析政企OTN站点容量」。",
                        )
                    else:
                        # 正常大纲生成完成，更新工具上下文并持久化
                        tool_ctx.current_outline = subtree
                        tool_ctx.has_outline = True
                        if anchor:
                            await tool_ctx.chat_history.save_outline_state(
                                tool_ctx.session_id,
                                subtree,
                                anchor,
                            )
                # else: L5 确认场景，subtree 为 None，不标记 has_outline

                # L5 确认场景：额外发送 confirm_required SSE 事件触发前端对话框
                if result.success and (result.data or {}).get("type") == "confirm_required":
                    yield {"sse": json.dumps({
                        "type": "confirm_required",
                        "indicator_name": result.data.get("indicator_name", ""),
                        "full_path": result.data.get("full_path", ""),
                        "ancestors": result.data.get("ancestors", []),
                    }, ensure_ascii=False)}
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
    node_id = args.get("node_id", "")
    operator = args.get("operator", "eq")
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
        params={"param_key": param_key, "param_value": param_value,
                "node_id": node_id, "operator": operator},
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

    # persist_only 前：将 inject_params 写入 SQLite 的最新大纲 params 同步到 Redis 缓存。
    # preview_only 阶段缓存的 fc 含默认 params，inject_params 只更新 SQLite 不更新缓存，
    # 不同步则 SkillPersist 写 indicators.json 时使用旧默认值。
    await _sync_injected_params_to_skill_cache(tool_ctx, context_key)

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


async def _sync_injected_params_to_skill_cache(tool_ctx: ToolContext, context_key: str) -> None:
    """将 chat_history（SQLite）中最新的大纲 params 同步到 skill_factory_ctx Redis 缓存。

    inject_params 执行后只更新 SQLite 的 outline_json.paragraph.params，不更新
    preview_only 阶段写入的 skill_factory_ctx Redis 缓存。此函数在 persist_only 执行前
    补偿这个同步缺口，确保 indicators.json 中写入的是用户最终确认的参数值。
    """
    try:
        cache_key = f"skill_factory_ctx:{context_key}"
        cached = await tool_ctx.session_service.redis.get(cache_key)
        if not cached:
            return

        fc_dict = json.loads(cached)
        bindings = fc_dict.get("bindings", [])
        if not bindings:
            return

        # 读取 SQLite 中 inject_params 更新后的最新大纲
        state = await tool_ctx.chat_history.get_outline_state(tool_ctx.session_id)
        if not state or not state.get("outline_json"):
            return

        live_outline = state["outline_json"]

        # 构建 node_id → 节点快查表
        node_map: dict = {}
        _collect_node_map(live_outline, node_map)

        # 将最新 params 覆写到缓存的 bindings（只改 params，其余字段不变）
        updated = False
        for binding in bindings:
            node_id = binding.get("node_id", "")
            live_node = node_map.get(node_id)
            if not live_node:
                continue
            live_params = live_node.get("paragraph", {}).get("params", {})
            if live_params:
                binding.setdefault("paragraph", {})["params"] = live_params
                updated = True

        if updated:
            # outline_json 一并更新，保持 outline.json 与 indicators.json 一致
            fc_dict["outline_json"] = live_outline
            await tool_ctx.session_service.redis.setex(
                cache_key, 3600, json.dumps(fc_dict, ensure_ascii=False)
            )
            logger.info(
                f"_sync_injected_params_to_skill_cache: 已同步注入参数到沉淀缓存 "
                f"session={tool_ctx.session_id} bindings_updated={sum(1 for b in bindings if node_map.get(b.get('node_id', '')))}"
            )
    except Exception as e:
        logger.warning(f"同步注入参数到沉淀缓存失败（继续沉淀，params 可能为默认值）: {e}")


def _collect_node_map(node: dict, result: dict) -> None:
    """递归构建 {node_id: node_dict} 映射，供 params 快速查找。"""
    if node_id := node.get("id"):
        result[node_id] = node
    for child in node.get("children", []):
        _collect_node_map(child, result)


# ─────────────────────────────────────────────────────────────────────────────
# 报告修改工具
# ─────────────────────────────────────────────────────────────────────────────


async def _load_latest_report_html(tool_ctx: ToolContext) -> str:
    """从对话历史中加载最近一条包含 report_html 的消息，返回 HTML 字符串。"""
    try:
        msgs = await tool_ctx.chat_history.get_messages(tool_ctx.session_id, limit=50)
        for m in reversed(msgs):
            meta = m.get("metadata") or {}
            if meta.get("report_html"):
                return meta["report_html"]
    except Exception as e:
        logger.warning(f"加载报告 HTML 失败: {e}")
    return ""

async def _modify_report_data(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    """数据层修改：修改参数后局部刷新报告对应章节。"""
    instruction = args.get("instruction", "")
    if not instruction:
        yield {"result": SkillResult(False, "缺少 instruction 参数")}
        return

    sid = tool_ctx.session_id
    outline_state = await tool_ctx.chat_history.get_outline_state(sid)
    if not outline_state or not outline_state.get("outline_json"):
        yield {"result": SkillResult(False, "当前没有大纲，无法修改报告")}
        return

    outline = outline_state["outline_json"]
    report_html = await _load_latest_report_html(tool_ctx)
    if not report_html:
        yield {"result": SkillResult(False, "当前没有已生成的报告，请先生成报告")}
        return

    # 定位目标章节
    try:
        import sys as _sys
        _modify_scripts = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "skills", "builtin", "report-modify", "scripts"
        ))
        if _modify_scripts not in _sys.path:
            _sys.path.insert(0, _modify_scripts)
        from section_resolver import resolve_section
    except Exception as e:
        yield {"result": SkillResult(False, f"章节定位模块加载失败: {e}")}
        return

    resolved = resolve_section(instruction, outline)
    node_ids = resolved.get("node_ids", [])
    yield {"sse": json.dumps({"type": "thinking_step", "step": "modify_report",
                              "status": "running",
                              "detail": f"定位章节：{resolved.get('parsed_action', '')}"}, ensure_ascii=False)}

    # 从 instruction 中提取参数（简单解析：数字+%）
    import re as _re
    param_matches = _re_param_from_instruction(instruction)
    updated_params = {}
    for key, val in param_matches.items():
        updated_params[key] = val

    # 重新执行数据并生成 patch
    from services.data.data_service_factory import create_data_service
    try:
        from report_modify_executor import modify_data  # 已在 sys.path 中
        result = await modify_data(
            outline=outline,
            report_html=report_html,
            target_node_ids=node_ids,
            updated_params=updated_params,
            data_service=create_data_service(),
        )
    except Exception as e:
        logger.error(f"modify_report_data 执行失败: {e}", exc_info=True)
        yield {"result": SkillResult(False, f"修改失败: {e}")}
        return

    # 推送局部 patch 事件
    for patch in result.get("patches", []):
        yield {"sse": json.dumps({"type": "report_patch",
                                  "node_id": patch["node_id"],
                                  "html": patch["html"]}, ensure_ascii=False)}

    new_html = result.get("new_report_html", report_html)
    yield {"result": SkillResult(True, f"已局部刷新报告（{len(result.get('patches', []))} 个节点）",
                                 data={"report_html": new_html,
                                       "patch_count": len(result.get("patches", []))})}


def _re_param_from_instruction(instruction: str) -> dict:
    """从指令文本中提取参数，如"阈值改为90%" → {"threshold": "90"}。"""
    params = {}
    import re as _re
    m = _re.search(r'(?:阈值|覆盖率)[^\d]*(\d+)', instruction)
    if m:
        params["threshold"] = m.group(1)
    m = _re.search(r'(\d+)\s*%', instruction)
    if m and "threshold" not in params:
        params["threshold"] = m.group(1)
    return params


async def _modify_report_text(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    """文本层修改：对报告中某章节的 narrative 文字用 LLM 改写。"""
    instruction = args.get("instruction", "")
    if not instruction:
        yield {"result": SkillResult(False, "缺少 instruction 参数")}
        return

    sid = tool_ctx.session_id
    outline_state = await tool_ctx.chat_history.get_outline_state(sid)
    if not outline_state or not outline_state.get("outline_json"):
        yield {"result": SkillResult(False, "当前没有大纲，无法修改报告")}
        return

    outline = outline_state["outline_json"]
    report_html = await _load_latest_report_html(tool_ctx)
    if not report_html:
        yield {"result": SkillResult(False, "当前没有已生成的报告，请先生成报告")}
        return

    # 定位目标章节
    try:
        import sys as _sys
        _modify_scripts = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "skills", "builtin", "report-modify", "scripts"
        ))
        if _modify_scripts not in _sys.path:
            _sys.path.insert(0, _modify_scripts)
        from section_resolver import resolve_section, collect_l5_nodes_under
    except Exception as e:
        yield {"result": SkillResult(False, f"章节定位模块加载失败: {e}")}
        return

    resolved = resolve_section(instruction, outline)
    node_ids = resolved.get("node_ids", [])
    yield {"sse": json.dumps({"type": "thinking_step", "step": "modify_report",
                              "status": "running",
                              "detail": f"定位章节：{resolved.get('parsed_action', '')}"}, ensure_ascii=False)}

    # 找到目标章节下第一个 L5 节点作为改写目标
    l5_nodes = collect_l5_nodes_under(outline, node_ids) if node_ids else []
    if not l5_nodes:
        yield {"result": SkillResult(False, "未找到目标 L5 指标节点，无法改写文字")}
        return

    target_node = l5_nodes[0]
    target_node_id = target_node.get("id", "")
    target_node_name = target_node.get("name", "")

    try:
        from report_modify_executor import modify_text  # 已在 sys.path 中
        llm_svc = getattr(tool_ctx.container, "llm", None) if tool_ctx.container else None
        result = await modify_text(
            outline=outline,
            report_html=report_html,
            target_node_id=target_node_id,
            instruction=instruction,
            node_name=target_node_name,
            llm_service=llm_svc,
        )
    except Exception as e:
        logger.error(f"modify_report_text 执行失败: {e}", exc_info=True)
        yield {"result": SkillResult(False, f"文字改写失败: {e}")}
        return

    if result.get("error"):
        yield {"result": SkillResult(False, f"LLM 改写失败: {result['error']}")}
        return

    patch = result.get("patch")
    if patch:
        yield {"sse": json.dumps({"type": "report_patch",
                                  "node_id": patch["node_id"],
                                  "html": patch["html"]}, ensure_ascii=False)}

    new_html = result.get("new_report_html", report_html)
    yield {"result": SkillResult(True, f"已改写「{target_node_name}」的分析文字",
                                 data={"report_html": new_html})}


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
            "若返回 success=false 且提示未找到匹配场景，说明知识库中确实没有对应能力，"
            "应直接告知用户，不得重试或使用更宽泛的关键词重新搜索。"
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
            "裁剪完成后询问用户是否重新生成报告，不得自动调用 execute_data/render_report。"
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
            "用户说'只看XX行业/阈值改为XX/改成XX%'时调用。"
            "调用前必须先执行 get_current_outline 获取大纲 JSON，从中精确找到目标 L5 节点的 node_id，"
            "不得凭记忆猜测 node_id。同一参数涉及多个节点时，需对每个节点分别调用本工具。"
            "注入完成后询问用户是否生成报告，不得自动调用 execute_data/render_report。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "目标 L5 节点的 id（从大纲 JSON 中获取），为空则全局注入",
                },
                "param_key": {"type": "string", "description": "参数名，如 bandwidth_threshold / industry"},
                "param_value": {"type": "string", "description": "参数值，如 '100' / '金融'"},
                "operator": {
                    "type": "string",
                    "description": "比较运算符：lt/lte/gt/gte/eq，默认 eq",
                    "enum": ["lt", "lte", "gt", "gte", "eq"],
                },
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

    # ── 报告修改工具 ──
    registry.register(
        name="modify_report_data",
        description=(
            "修改报告中某个章节的数据参数（如阈值、行业过滤），重新执行该节点数据查询并局部刷新报告。"
            "用户说'把第X章的阈值改为N%'或'重新计算第X节'时调用。"
            "调用前需确认已有报告（has_report=true）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "instruction": {"type": "string", "description": "用户的修改指令，如'把第一章覆盖率阈值改为90%'"},
            },
            "required": ["instruction"],
        },
        fn=_modify_report_data,
    )

    registry.register(
        name="modify_report_text",
        description=(
            "对报告中某个章节的分析文字进行润色、改写或扩充。"
            "用户说'润色第X章第Y节的结论'或'修改第X章的分析文字'时调用。"
            "调用前需确认已有报告（has_report=true）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "instruction": {"type": "string", "description": "用户的改写指令，如'润色第二章第一节，增加趋势判断'"},
            },
            "required": ["instruction"],
        },
        fn=_modify_report_text,
    )
