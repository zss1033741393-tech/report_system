"""工具定义 —— ReAct 工具的 schema + 执行函数。

架构分层：
  L1 工具（Agent 常驻）：get_skill_instructions（按需加载 SKILL.md 正文）
  L2 工具（按需加载）  ：get_skill_reference（加载 references/ 文件）
  LLM helper 函数     ：_llm_*（统一管理所有子 LLM 调用，executor 不含任何 LLM 逻辑）
  工具函数签名：async def fn(args, tool_ctx) -> AsyncGenerator[dict, None]
    yield {"sse": str}            → 透传 SSE 事件
    yield {"result": SkillResult} → 工具执行结果（最后一次）

工具分类：
  Skill 披露：get_skill_instructions, get_skill_reference
  基础查询：get_session_status
  运行态：skill_router, search_skill, get_current_outline, clip_outline,
          inject_params, execute_data, render_report
  设计态：extract_intent, persist_outline
  报告修改：modify_report_data, modify_report_text
"""

import json
import logging
import os
import re
from typing import AsyncGenerator

from agent.context import SkillContext, SkillResult
from agent.tool_registry import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# LLM Helper 函数（统一管理所有子 LLM 调用，executor 层零 LLM 依赖）
# ─────────────────────────────────────────────────────────────────────────────

async def _llm_extract_intent(expert_input: str, llm_service, trace_callback=None) -> dict:
    """意图提取：自然语言 → scene_intro/keywords/query_variants/skill_name。"""
    from llm.agent_llm import AgentLLM
    from llm.config import SKILL_FACTORY_JSON_CONFIG
    prompt = (
        "你是看网逻辑分析专家。分析看网逻辑文本，提取结构化信息。\n\n"
        "## 输出格式\n"
        '```json\n{"scene_intro":"50字以内","keywords":["3-5个关键词"],'
        '"query_variants":["3种用户问法"],"skill_name":"英文下划线"}\n```\n\n'
        f"## 看网逻辑\n{expert_input}\n\n用 ```json ``` 代码块包裹输出。"
    )
    agent = AgentLLM(llm_service, "", SKILL_FACTORY_JSON_CONFIG,
                     trace_callback=trace_callback,
                     llm_type="intent_extract", step_name="intent_extract")
    try:
        result = await agent.chat_json(prompt)
        return {
            "scene_intro": result.get("scene_intro", ""),
            "keywords": result.get("keywords", []),
            "query_variants": result.get("query_variants", [])[:5],
            "skill_name": result.get("skill_name", "unnamed_skill"),
        }
    except Exception as e:
        logger.warning(f"意图提取 LLM 失败: {e}")
        return {"scene_intro": "", "keywords": [], "query_variants": [], "skill_name": "unnamed_skill"}


async def _llm_select_anchor(query: str, nodes: list, llm_service, trace_callback=None) -> dict:
    """锚点选择：从 Neo4j 候选节点中选出最符合用户意图的唯一节点。"""
    from llm.agent_llm import AgentLLM
    from llm.config import ANCHOR_SELECT_CONFIG
    system_prompt = (
        "你是知识库节点选择专家。从候选中选出最符合用户意图的唯一节点。\n"
        "判断原则: 宽泛→高层级，具体→低层级，父子关系时按粒度判断。\n"
        '用 ```json ``` 代码块包裹输出，格式:\n'
        '```json\n{"selected_id":"","selected_name":"","selected_path":"","level":0,"reason":""}\n```'
    )
    cs = "\n".join(f'- id={n["id"]} name={n["name"]} level={n["level"]} path={n.get("path","")}' for n in nodes)
    agent = AgentLLM(llm_service, system_prompt, ANCHOR_SELECT_CONFIG,
                     trace_callback=trace_callback, llm_type="anchor_select", step_name="anchor_select")
    try:
        return await agent.chat_json(f"## 候选\n{cs}\n\n## 问题\n{query}")
    except Exception:
        f = nodes[0]
        return {"selected_id": f["id"], "selected_name": f["name"],
                "selected_path": f.get("path", ""), "level": f["level"], "reason": "fallback"}


async def _llm_filter_nodes(subtree: dict, focus_dims: list, focus_items: list,
                             exclude: list, llm_service, trace_callback=None) -> list:
    """条件裁剪：返回应被移除的节点名称列表（executor 用于 _prune_tree）。"""
    from llm.agent_llm import AgentLLM
    from llm.config import LLMConfig

    l3_l4_names = []
    for child in subtree.get("children", []):
        if child.get("level") in (3, 4):
            l3_l4_names.append(f'- {child["name"]} (L{child["level"]})')
        for gc in child.get("children", []):
            if gc.get("level") in (3, 4):
                l3_l4_names.append(f'- {gc["name"]} (L{gc["level"]})')
    if not l3_l4_names:
        return []

    prompt = (
        "你是大纲裁剪专家。根据用户条件判断哪些节点应该保留。\n\n"
        f"## 用户条件\n关注的维度: {', '.join(focus_dims) or '无特定要求'}\n"
        f"关注的评估项: {', '.join(focus_items) or '无特定要求'}\n"
        f"排除: {', '.join(exclude) or '无'}\n\n"
        f"## 待判断的节点列表\n{chr(10).join(l3_l4_names)}\n\n"
        "用 ```json ``` 代码块包裹，格式: "
        '{"keep": ["节点名1"], "remove": ["节点名2"]}'
    )
    agent = AgentLLM(llm_service, "", LLMConfig(temperature=0.1, max_tokens=512, response_format="json"),
                     trace_callback=trace_callback, llm_type="filter", step_name="condition_filter")
    try:
        result = await agent.chat_json(prompt)
        return result.get("remove", [])
    except Exception as e:
        logger.warning(f"条件裁剪 LLM 失败，保留完整子树: {e}")
        return []


async def _llm_organize_bottom_up(intent: dict, bottom_up: dict, raw_input: str,
                                   llm_service, trace_callback=None) -> dict:
    """自底向上大纲组织：返回完整大纲树 JSON（L2 根节点）。"""
    from llm.agent_llm import AgentLLM
    from llm.config import SKILL_FACTORY_OUTLINE_CONFIG

    # 从 BottomUpOrganizer.build_llm_prompt 获取 prompt（避免重复维护）
    import importlib.util, sys as _sys
    bu_path = _find_skill_script("outline-generate", "bottom_up_organizer.py")
    if bu_path:
        spec = importlib.util.spec_from_file_location("_bu_mod", bu_path)
        bu_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bu_mod)
        system_prompt, user_msg = bu_mod.BottomUpOrganizer.build_llm_prompt(intent, bottom_up, raw_input)
    else:
        # 内联降级
        system_prompt = "你是报告大纲设计专家，请根据以下信息组织大纲树。"
        user_msg = f"看网逻辑: {raw_input}"

    agent = AgentLLM(llm_service, system_prompt, SKILL_FACTORY_OUTLINE_CONFIG,
                     trace_callback=trace_callback,
                     llm_type="bottom_up_outline", step_name="bottom_up_organize")
    try:
        return await agent.chat_json(user_msg)
    except Exception as e:
        logger.error(f"路径B LLM 大纲生成失败: {e}", exc_info=True)
        raise


async def _llm_parse_clip(instruction: str, nodes_text: str,
                           llm_service, trace_callback=None) -> list:
    """裁剪指令解析：自然语言 → 结构化操作列表。"""
    from llm.agent_llm import AgentLLM
    from llm.config import LLMConfig
    prompt = (
        "你是大纲裁剪专家。根据用户指令，生成裁剪操作列表。\n\n"
        f"## 当前大纲节点\n{nodes_text}\n\n"
        f"## 用户指令\n{instruction}\n\n"
        '## 输出格式\n用 ```json ``` 代码块包裹，格式：\n'
        '{"instructions": [\n'
        '    {"type": "delete_node", "target_name": "节点名", "level": 4},\n'
        '    {"type": "filter_param", "target_name": "节点名", "param_key": "industry", "param_value": "金融"},\n'
        '    {"type": "keep_only", "target_names": ["节点名1", "节点名2"]}\n'
        ']}'
    )
    agent = AgentLLM(llm_service, "", LLMConfig(temperature=0.1, max_tokens=1024),
                     trace_callback=trace_callback, llm_type="outline_clip", step_name="parse_clip")
    try:
        result = await agent.chat_json(prompt)
        return result.get("instructions", [])
    except Exception as e:
        logger.warning(f"裁剪指令解析失败: {e}")
        return []


async def _llm_route_skills(query: str, skill_metas: list,
                             llm_service, trace_callback=None) -> list:
    """Skill 路由精排：返回 [{"skill_id": str, "description": str}, ...]。"""
    from llm.agent_llm import AgentLLM
    from llm.config import SKILL_ROUTER_CONFIG
    system_prompt = (
        "你是看网能力路由专家。根据用户的分析需求，从已沉淀的看网能力列表中找出最相关的候选项，"
        "并为每个候选生成简短的差异化描述帮助用户选择。\n\n"
        "## 输出格式\n用 ```json ``` 代码块包裹，格式：\n"
        '{"matches": [{"skill_id": "id1", "description": "该方案侧重于..."}, ...]}\n'
        "- 最多 5 个，按相关度从高到低排列\n- 若无匹配返回 {\"matches\": []}"
    )
    lines = []
    for m in skill_metas:
        kw_str = "、".join(m.get("keywords", [])[:5])
        qv_str = "、".join(m.get("query_variants", [])[:3])
        lines.append(
            f'skill_id={m["skill_id"]}\n'
            f'  名称: {m.get("display_name", m["skill_id"])}\n'
            f'  场景: {m.get("scene_intro", "")}\n'
            f'  关键词: {kw_str}\n'
            f'  触发问法: {qv_str}'
        )
    user_msg = f"## 用户需求\n{query}\n\n## 已沉淀看网能力列表\n" + "\n\n".join(lines)
    agent = AgentLLM(llm_service, system_prompt, SKILL_ROUTER_CONFIG,
                     trace_callback=trace_callback,
                     llm_type="skill_router", step_name="skill_router_select")
    try:
        data = await agent.chat_json(user_msg)
        result = []
        for item in data.get("matches", []):
            if isinstance(item, str):
                result.append({"skill_id": item, "description": ""})
            elif isinstance(item, dict) and "skill_id" in item:
                result.append({"skill_id": item["skill_id"], "description": item.get("description", "")})
        return result
    except Exception as e:
        logger.warning(f"skill_router LLM 精排失败: {e}")
        return []


def _find_skill_script(skill_name: str, script_filename: str) -> str:
    """在 skill registry 中查找 script 文件的绝对路径。"""
    base = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "skills", "builtin"))
    path = os.path.join(base, skill_name, "scripts", script_filename)
    return path if os.path.isfile(path) else ""


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
# Skill 渐进式披露工具（L2：指令正文 / L3：references 文件）
# ─────────────────────────────────────────────────────────────────────────────

async def _get_skill_instructions(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    """L2 披露：加载 SKILL.md 正文（不含 frontmatter），获取 How to Use / Steps 等执行指南。"""
    skill_name = args.get("skill_name", "")
    if not skill_name:
        yield {"result": SkillResult(False, "缺少 skill_name 参数")}
        return
    try:
        content = tool_ctx.registry.load_full_content(skill_name)
        if content:
            # 只返回 frontmatter 之后的正文
            parts = content.split("---", 2)
            body = parts[2].strip() if len(parts) >= 3 else content
            yield {"result": SkillResult(True, f"已加载 {skill_name} 指南", data={"instructions": body})}
        else:
            yield {"result": SkillResult(False, f"未找到 Skill: {skill_name}")}
    except Exception as e:
        yield {"result": SkillResult(False, f"加载失败: {e}")}


async def _get_skill_reference(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    """L3 披露：加载 skill references/ 目录下的参考文件（prompt 模板、清单、Schema 等）。"""
    skill_name = args.get("skill_name", "")
    ref_name = args.get("ref_name", "")
    if not skill_name or not ref_name:
        yield {"result": SkillResult(False, "缺少 skill_name 或 ref_name 参数")}
        return
    base = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "skills", "builtin"))
    ref_path = os.path.join(base, skill_name, "references", ref_name)
    if not os.path.isfile(ref_path):
        yield {"result": SkillResult(False, f"参考文件不存在: {skill_name}/references/{ref_name}")}
        return
    try:
        with open(ref_path, "r", encoding="utf-8") as f:
            content = f.read()
        yield {"result": SkillResult(True, f"已加载 {ref_name}", data={"content": content, "path": ref_path})}
    except Exception as e:
        yield {"result": SkillResult(False, f"读取失败: {e}")}


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

    # LLM 锚点选择（tool 层统一做，executor 只做纯算法）
    # 先让 executor 做 FAISS+Neo4j，再传入 LLM 预计算的锚点
    # 策略：运行一次"预检"以获取候选节点，再调 LLM 选锚，最后传 anchor 参数给真正的 execute
    anchor = None
    filter_conditions = args.get("filter_conditions")
    remove_nodes = []

    try:
        llm_svc = tool_ctx.container.get("llm_service") if tool_ctx.container else None
        # 从 executor 暴露的 helper 获取候选节点（不启动完整 execute 流程）
        qe = await executor._emb.get_embedding(query)
        cands = executor._faiss.search(qe, executor._top_k, executor._threshold)
        if cands:
            nodes = await executor._neo4j.get_ancestor_paths([c.neo4j_id for c in cands])
            if nodes and llm_svc:
                anchor = await _llm_select_anchor(query, nodes, llm_svc, tool_ctx.trace_callback)
                # 条件裁剪
                if filter_conditions and isinstance(filter_conditions, dict):
                    fd = filter_conditions.get("focus_dimensions", [])
                    fi = filter_conditions.get("focus_items", [])
                    ex = filter_conditions.get("exclude", [])
                    if fd or fi or ex:
                        # 需要先取子树才能裁剪，这里先记录条件，executor 返回后裁剪
                        pass  # remove_nodes 在 executor 返回 subtree 后再算
    except Exception as e:
        logger.warning(f"search_skill: LLM 预计算失败，使用 executor 降级: {e}")

    logger.info(f"search_skill: query={query!r} session={tool_ctx.session_id}")
    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message=query,
        params={"query": query, "anchor": anchor, "remove_nodes": remove_nodes or None,
                "filter_conditions": filter_conditions},
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


async def _skill_router(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    query = args.get("query", "")
    if not query:
        yield {"result": SkillResult(False, "缺少 query 参数")}
        return

    executor = tool_ctx.loader.get_executor("skill-router")
    if not executor:
        logger.warning("skill_router: skill-router 执行器未加载，跳过路由")
        yield {"result": SkillResult(True, "skill_router 未加载，跳过", data={"candidates": []})}
        return

    # LLM 精排（tool 层统一做）：先查 DB 获取 skill_metas，再调 LLM，结果传给 executor
    matched_ids = []
    try:
        rows = await executor._store.list_active_outlines_for_router()
        skill_metas = [
            {
                "skill_id": r["skill_name"],
                "outline_id": r["id"],
                "display_name": r.get("display_name") or r["skill_name"],
                "scene_intro": r.get("scene_intro", ""),
                "keywords": r.get("keywords") or [],
                "query_variants": r.get("query_variants") or [],
            }
            for r in rows
        ]
        if skill_metas:
            llm_svc = tool_ctx.container.get("llm_service") if tool_ctx.container else None
            if llm_svc:
                matched_ids = await _llm_route_skills(query, skill_metas, llm_svc, tool_ctx.trace_callback)
    except Exception as e:
        logger.warning(f"skill_router LLM 预计算失败: {e}")

    ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message=query,
        params={"query": query, "matched_ids": matched_ids},
        trace_callback=tool_ctx.trace_callback,
    )
    result = None
    async for item in executor.execute(ctx):
        if isinstance(item, SkillResult):
            result = item
        elif isinstance(item, str):
            yield {"sse": item}

    yield {"result": result or SkillResult(False, "skill_router 执行失败")}


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

    # LLM 裁剪指令解析（tool 层统一做，executor 只执行纯算法）
    clip_instructions = []
    try:
        from skills.builtin.outline_clip.scripts.outline_clip_executor import OutlineClipExecutor as _OCE
        nodes_text = _OCE.collect_nodes_text(current_outline) if current_outline else ""
        llm_svc = tool_ctx.container.get("llm_service") if tool_ctx.container else None
        if llm_svc:
            clip_instructions = await _llm_parse_clip(instruction, nodes_text, llm_svc, tool_ctx.trace_callback)
    except Exception as e:
        logger.warning(f"clip_outline: LLM 解析失败，executor 将返回失败: {e}")

    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message=instruction,
        params={"instructions": instruction, "clip_instructions": clip_instructions},
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
# 设计态工具（重构后：intent-extract + outline-persist 两个独立 Skill）
# ─────────────────────────────────────────────────────────────────────────────

async def _extract_intent(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    """执行意图提取 + 双路径检索（Step1 LLM + Step2 纯算法）。

    路径A（自顶向下）：命中 L1~L4 高置信度节点，返回子树供 search_skill 渲染大纲。
    路径B（自底向上）：仅命中 L5 指标，返回指标列表 + KB 内容，由 LLM 自由组织 L2~L4。
    完成后系统缓存上下文到 Redis，发送 persist_prompt 等待用户确认是否沉淀。
    """
    expert_input = args.get("expert_input", "")
    if not expert_input:
        yield {"result": SkillResult(False, "缺少 expert_input 参数")}
        return

    executor = tool_ctx.loader.get_executor("intent-extract")
    if not executor:
        logger.error("extract_intent: intent-extract 执行器未加载")
        yield {"result": SkillResult(False, "intent-extract 执行器未加载")}
        return

    # Step 1: LLM 意图提取（tool 层统一做，executor 不含 LLM）
    logger.info(f"extract_intent: 启动 session={tool_ctx.session_id}")
    llm_svc = tool_ctx.container.get("llm_service") if tool_ctx.container else None
    intent = await _llm_extract_intent(expert_input, llm_svc, tool_ctx.trace_callback)

    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message=expert_input,
        params={"expert_input": expert_input, "intent": intent},
        current_outline=tool_ctx.current_outline,
        trace_callback=tool_ctx.trace_callback,
    )
    result = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result = item
        elif isinstance(item, str):
            yield {"sse": item}

    final = result or SkillResult(False, "意图提取失败")
    if not final.success:
        yield {"result": final}
        return

    path = (final.data or {}).get("path", "no_match")
    intent = (final.data or {}).get("intent", {})

    # 路径 A：直接用子树生成大纲（复用 search_skill 渲染逻辑）
    if path == "top_down":
        top_down = (final.data or {}).get("top_down", {})
        subtree = top_down.get("subtree")
        anchor_info = top_down.get("anchor", {})
        if subtree and anchor_info:
            # 合并 paragraph（indicator_resolver）
            rag_executor = tool_ctx.loader.get_executor("outline-generate")
            if rag_executor:
                rag_executor.merge_paragraph(subtree, skill_dir="")
            # 渲染大纲
            container = tool_ctx.container
            renderer = container.get("outline_renderer") if container else None
            if renderer:
                chunks = []
                async for chunk in renderer.render_stream(subtree, anchor_info):
                    chunks.append(chunk)
                    yield {"sse": json.dumps({"type": "outline_chunk", "content": chunk}, ensure_ascii=False)}
                yield {"sse": json.dumps({"type": "outline_done", "anchor": anchor_info}, ensure_ascii=False)}
            # 持久化大纲到会话
            await tool_ctx.chat_history.save_outline_state(
                tool_ctx.session_id, subtree, anchor_info
            )
            tool_ctx.has_outline = True
            tool_ctx.current_outline = subtree
            # 缓存上下文供 persist_outline 使用
            cache_payload = {
                "raw_input": expert_input,
                "intent": intent,
                "outline_json": subtree,
                "path": "top_down",
            }
            await tool_ctx.session_service.redis.setex(
                f"skill_factory_ctx:{tool_ctx.session_id}", 3600,
                json.dumps(cache_payload, ensure_ascii=False)
            )
            yield {"sse": json.dumps({"type": "persist_prompt",
                                      "message": "大纲已生成。是否将此次推理保存为新的看网能力？",
                                      "context_key": tool_ctx.session_id}, ensure_ascii=False)}
            yield {"result": SkillResult(True, f"路径A大纲生成完成（{anchor_info.get('name', '')}）",
                                          data={"path": "top_down", "outline_json": subtree,
                                                "intent": intent})}
            return

    # 路径 B：LLM 组织大纲 → BottomUpOrganizer 后处理
    if path in ("bottom_up", "no_match"):
        bottom_up_data = (final.data or {}).get("bottom_up", {})

        try:
            # Step 1: LLM 生成 raw_outline（tool 层统一做）
            raw_outline = await _llm_organize_bottom_up(
                intent, bottom_up_data, expert_input, llm_svc, tool_ctx.trace_callback
            )

            # Step 2: BottomUpOrganizer 纯算法后处理（hydrate_l5 + paragraph + md渲染）
            import importlib.util
            bu_path = _find_skill_script("outline-generate", "bottom_up_organizer.py")
            if not bu_path:
                yield {"result": SkillResult(False, "bottom_up_organizer.py 未找到")}
                return
            spec = importlib.util.spec_from_file_location("_bu_mod", bu_path)
            bu_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bu_mod)
            indicator_resolver = tool_ctx.container.get("indicator_resolver") if tool_ctx.container else None
            organizer = bu_mod.BottomUpOrganizer(indicator_resolver)
            bu_ctx = SkillContext(
                session_id=tool_ctx.session_id,
                user_message=expert_input,
                params={
                    "intent": intent, "bottom_up": bottom_up_data,
                    "raw_input": expert_input, "raw_outline": raw_outline,
                },
                trace_callback=tool_ctx.trace_callback,
            )
            bu_result = None
            async for item in organizer.execute(bu_ctx):
                if isinstance(item, SkillResult):
                    bu_result = item
                elif isinstance(item, str):
                    yield {"sse": item}

            if bu_result and bu_result.success:
                subtree = bu_result.data.get("subtree", {})
                anchor_info = bu_result.data.get("anchor", {})
                await tool_ctx.chat_history.save_outline_state(tool_ctx.session_id, subtree, anchor_info)
                tool_ctx.has_outline = True
                tool_ctx.current_outline = subtree
                await tool_ctx.session_service.redis.setex(
                    f"skill_factory_ctx:{tool_ctx.session_id}", 3600,
                    json.dumps({"raw_input": expert_input, "intent": intent,
                                "outline_json": subtree, "path": "bottom_up"}, ensure_ascii=False)
                )
                yield {"sse": json.dumps({"type": "persist_prompt",
                                          "message": "大纲已生成。是否将此次推理保存为新的看网能力？",
                                          "context_key": tool_ctx.session_id}, ensure_ascii=False)}
                yield {"result": SkillResult(True, "路径B大纲生成完成",
                                              data={"path": "bottom_up", "outline_json": subtree, "intent": intent})}
                return
            else:
                yield {"result": bu_result or SkillResult(False, "路径B大纲生成失败")}
                return
        except Exception as e:
            logger.error(f"extract_intent: 路径B大纲生成失败: {e}", exc_info=True)

    yield {"result": SkillResult(False, f"意图提取完成但无法生成大纲 (path={path})")}


async def _persist_outline(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]:
    """将设计态大纲沉淀到 DB（outlines/outline_nodes/node_bindings 三张表）。
    仅在用户明确说"保存/沉淀"时调用。
    """
    context_key = args.get("context_key", tool_ctx.session_id)
    executor = tool_ctx.loader.get_executor("outline-persist")
    if not executor:
        yield {"result": SkillResult(False, "outline-persist 执行器未加载")}
        return

    # 同步 inject_params 修改的最新 params 到 Redis 缓存
    await _sync_injected_params_to_cache(tool_ctx, context_key)

    skill_ctx = SkillContext(
        session_id=tool_ctx.session_id,
        user_message="",
        params={"context_key": context_key},
        trace_callback=tool_ctx.trace_callback,
    )
    result = None
    async for item in executor.execute(skill_ctx):
        if isinstance(item, SkillResult):
            result = item
        elif isinstance(item, str):
            yield {"sse": item}

    yield {"result": result or SkillResult(False, "大纲沉淀失败")}


async def _sync_injected_params_to_cache(tool_ctx: ToolContext, context_key: str) -> None:
    """将 inject_params 写入 SQLite 的最新 params 同步到 Redis 缓存，保持 persist 时数据一致。"""
    try:
        cache_key = f"skill_factory_ctx:{context_key}"
        cached = await tool_ctx.session_service.redis.get(cache_key)
        if not cached:
            return
        fc_dict = json.loads(cached)
        state = await tool_ctx.chat_history.get_outline_state(tool_ctx.session_id)
        if state and state.get("outline_json"):
            fc_dict["outline_json"] = state["outline_json"]
            await tool_ctx.session_service.redis.setex(
                cache_key, 3600, json.dumps(fc_dict, ensure_ascii=False)
            )
    except Exception as e:
        logger.warning(f"同步 params 到缓存失败（可忽略）: {e}")


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

    # ── Skill 渐进式披露工具（L2/L3）──
    registry.register(
        name="get_skill_instructions",
        description=(
            "L2 披露：加载指定 Skill 的 SKILL.md 正文（How to Use / Steps 等执行指南）。"
            "决定使用某个 Skill 后调用，了解具体调用步骤和参数要求。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "Skill 名称，如 intent-extract / outline-generate"},
            },
            "required": ["skill_name"],
        },
        fn=_get_skill_instructions,
    )

    registry.register(
        name="get_skill_reference",
        description=(
            "L3 披露：加载 Skill references/ 目录下的参考文件（prompt 模板、评审清单、数据 Schema 等）。"
            "执行 Skill 具体步骤时按需调用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "Skill 名称"},
                "ref_name": {"type": "string", "description": "文件名，如 anchor_select_prompt.md"},
            },
            "required": ["skill_name", "ref_name"],
        },
        fn=_get_skill_reference,
    )

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
        name="skill_router",
        description=(
            "检索已沉淀的看网能力并通过 LLM 精排，返回候选列表供用户选择。"
            "用户提出看网分析需求时优先调用此工具（在 search_skill 之前）。"
            "若有候选结果会推送 skill_candidates 事件，等待用户选择后再继续。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用户的分析需求描述"},
            },
            "required": ["query"],
        },
        fn=_skill_router,
    )

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

    # ── 设计态工具 ──
    registry.register(
        name="extract_intent",
        description=(
            "执行意图提取+双路径检索，生成看网分析大纲。"
            "用户输入超过80字的看网逻辑描述时调用此工具。"
            "路径A（命中L1~L4高置信度节点）直接返回子树大纲；"
            "路径B（仅命中L5指标）由LLM自底向上自由组织L2~L4结构。"
            "流程完成后系统自动向用户发送沉淀确认提示，等待用户决定是否保存。"
            "【重要】此工具调用完成后，不得再调用 persist_outline，必须等待用户明确回复。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "expert_input": {"type": "string", "description": "专家输入的看网逻辑文本（完整原文）"},
            },
            "required": ["expert_input"],
        },
        fn=_extract_intent,
    )

    registry.register(
        name="persist_outline",
        description=(
            "将设计态大纲沉淀到DB（outlines/outline_nodes/node_bindings 三张表）。"
            "【重要】仅在用户明确说'保存/沉淀/确认保存'时才调用此工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "context_key": {"type": "string", "description": "缓存 key（通常为 session_id，可从 get_session_status 获取）"},
            },
            "required": [],
        },
        fn=_persist_outline,
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
