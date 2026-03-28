"""工具注册中心 —— 将 LLM 工具调用桥接到现有 Executor 实例。

设计原则：
  - ToolRegistry 是纯桥接层，不实现任何业务逻辑
  - 所有业务实现复用现有 Executor（SkillLoader 管理的 Python 对象）
  - 将工具调用参数转成 SkillContext，再调 executor.execute()，收集结果
"""

import json
import logging
import os
from typing import Any, AsyncGenerator

from agent.context import SkillContext, SkillResult
from agent.skill_loader import SkillLoader
from agent.skill_registry import SkillRegistry
from services.chat_history import ChatHistoryService
from services.session_service import SessionService

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册中心，将 LLM tool_call 路由到对应的 Executor 方法。"""

    def __init__(
        self,
        skill_loader: SkillLoader,
        skill_registry: SkillRegistry,
        chat_history: ChatHistoryService,
        session_service: SessionService,
        skills_root: str = "./skills",
    ):
        self._loader = skill_loader
        self._registry = skill_registry
        self._ch = chat_history
        self._ss = session_service
        # 规范化 skills_root，去掉尾部斜杠，统一用 os.path.abspath 处理
        self._skills_root = os.path.abspath(skills_root)

        # 工具名 → 处理方法映射
        self._handlers = {
            # 基础工具
            "read_skill_file": self._handle_read_skill_file,
            "get_session_status": self._handle_get_session_status,
            # 运行态工具
            "search_skill": self._handle_search_skill,
            "get_current_outline": self._handle_get_current_outline,
            "clip_outline": self._handle_clip_outline,
            "inject_params": self._handle_inject_params,
            "execute_data": self._handle_execute_data,
            "render_report": self._handle_render_report,
            # 设计态工具（skill-factory 六步）
            "understand_intent": self._handle_understand_intent,
            "extract_structure": self._handle_extract_structure,
            "design_outline": self._handle_design_outline,
            "bind_data": self._handle_bind_data,
            "preview_report": self._handle_preview_report,
            "persist_skill": self._handle_persist_skill,
        }

    def has_tool(self, name: str) -> bool:
        return name in self._handlers

    async def execute(
        self,
        tool_name: str,
        tool_args: dict,
        session_id: str,
        current_outline: Any = None,
        step_results: dict = None,
        user_message: str = "",
        trace_callback=None,
    ) -> AsyncGenerator[str, None]:
        """
        执行指定工具，以 AsyncGenerator 方式 yield SSE 事件字符串。
        """
        handler = self._handlers.get(tool_name)
        if not handler:
            yield self._sse("tool_result", name=tool_name, content=f"未知工具: {tool_name}", error=True)
            return

        ctx = SkillContext(
            session_id=session_id,
            user_message=user_message,
            params=tool_args,
            current_outline=current_outline,
            step_results=step_results or {},
            trace_callback=trace_callback,
        )

        try:
            async for item in handler(ctx, tool_args):
                yield item
        except Exception as e:
            logger.exception(f"工具执行失败: {tool_name}, {e}")
            yield self._sse("tool_result", name=tool_name,
                            content=f"工具执行出错: {e}", error=True)

    # ─── 基础工具 ─────────────────────────────────────────────────────────────

    async def _handle_read_skill_file(self, ctx: SkillContext, args: dict):
        """
        修复：LLM 传来的 path 可能含 "skills/" 前缀（如 skills/builtin/xxx/SKILL.md），
        而 _skills_root 本身已是 .../skills 的绝对路径，直接拼接会变成
        .../skills/skills/builtin/...（双重 skills）。

        策略：
          1. 如果 path 是绝对路径 → 直接用
          2. 如果 path 以 "skills/" 开头 → 去掉前缀后再拼接 _skills_root
          3. 否则 → 直接拼接 _skills_root
        """
        path = args.get("path", "").strip()

        if os.path.isabs(path):
            abs_path = path
        else:
            # 去掉 "skills/" 开头，防止双重路径
            clean = path
            for prefix in ("skills/", "skills\\"):
                if clean.startswith(prefix):
                    clean = clean[len(prefix):]
                    break
            abs_path = os.path.join(self._skills_root, clean)

        logger.debug(f"read_skill_file: path={path!r} → abs={abs_path!r}")

        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
            yield self._sse("tool_result", name="read_skill_file", content=content)
        except FileNotFoundError:
            # 提供调试信息，告知实际尝试路径
            yield self._sse("tool_result", name="read_skill_file",
                            content=f"文件不存在: {abs_path}（原始参数: {path}）", error=True)

    async def _handle_get_session_status(self, ctx: SkillContext, args: dict):
        session_id = args.get("session_id", ctx.session_id)
        try:
            outline_state = await self._ch.get_outline_state(session_id)

            # 防御：outline_state 可能是 None 或 outline_json 字段为 None
            has_outline = (
                outline_state is not None
                and isinstance(outline_state, dict)
                and outline_state.get("outline_json") is not None
            )

            # 检查最近消息中是否有报告
            # 防御：metadata 可能是 None，用 (m.get("metadata") or {}) 避免 NoneType.get
            msgs = await self._ch.get_messages(session_id, limit=20)
            has_report = any(
                (m.get("metadata") or {}).get("report_html")
                for m in msgs
            )

            # 检查 Redis 是否有 skill-factory 缓存
            cached_ctx_key = ""
            try:
                cached = await self._ss.redis.get(f"skill_factory_ctx:{session_id}")
                if cached:
                    cached_ctx_key = session_id
            except Exception:
                pass

            outline_summary = ""
            if has_outline:
                outline_json = outline_state.get("outline_json")
                if outline_json and isinstance(outline_json, dict):
                    outline_summary = self._summarize_outline(outline_json)

            status = {
                "has_outline": has_outline,
                "has_report": has_report,
                "has_cached_context": bool(cached_ctx_key),
                "cached_context_key": cached_ctx_key,
                "outline_summary": outline_summary,
            }
            yield self._sse("tool_result", name="get_session_status",
                            content=json.dumps(status, ensure_ascii=False))
        except Exception as e:
            logger.exception(f"get_session_status 失败: {e}")
            yield self._sse("tool_result", name="get_session_status",
                            content=f"获取状态失败: {e}", error=True)

    # ─── 运行态工具 ───────────────────────────────────────────────────────────

    async def _handle_search_skill(self, ctx: SkillContext, args: dict):
        """
        修复：不再走完整 outline-generate executor（那会触发完整大纲生成），
        改为轻量 FAISS 检索：直接调 GraphRAGExecutor 的 search_only 方法（如有），
        或通过 skill_registry.load_full_content + faiss_retriever 检索已沉淀能力。

        返回给 LLM 的结果：
          - 命中：技能名称 + 简要描述，让 LLM 知道有现成能力可用
          - 未命中：明确告知未命中，LLM 自行决定是否生成新大纲
        """
        query = args.get("query", ctx.user_message)

        executor = self._loader.get_executor("outline-generate")
        if not executor:
            yield self._sse("tool_result", name="search_skill",
                            content="知识库检索服务未就绪", error=True)
            return

        # 优先使用 executor 的轻量检索方法（只做 Step 0，不生成大纲）
        if hasattr(executor, "search_skill_only"):
            try:
                result = await executor.search_skill_only(query)
                if result:
                    yield self._sse("tool_result", name="search_skill",
                                    content=json.dumps(result, ensure_ascii=False))
                else:
                    yield self._sse("tool_result", name="search_skill",
                                    content="未找到匹配的已沉淀看网能力，需要生成新大纲")
                return
            except Exception as e:
                logger.warning(f"search_skill_only 失败，降级到 FAISS 检索: {e}")

        # 降级：直接用 SkillRegistry 遍历 custom skills 元数据做简单匹配
        try:
            custom_skills = [
                s for s in self._registry.get_all()
                if s.source == "custom" and s.enabled
            ]
            if not custom_skills:
                yield self._sse("tool_result", name="search_skill",
                                content="未找到匹配的已沉淀看网能力，需要生成新大纲")
                return

            # 简单关键词匹配（不做向量检索，避免重复触发 GraphRAG）
            query_lower = query.lower()
            matched = [
                s for s in custom_skills
                if any(kw in s.description.lower() or kw in s.name.lower()
                       for kw in query_lower.split())
            ]

            if matched:
                result_text = "\n".join(
                    f"- {s.name}: {s.description}" for s in matched[:3]
                )
                yield self._sse("tool_result", name="search_skill",
                                content=f"找到以下已沉淀看网能力：\n{result_text}")
            else:
                yield self._sse("tool_result", name="search_skill",
                                content="未找到匹配的已沉淀看网能力，需要生成新大纲")
        except Exception as e:
            logger.exception(f"search_skill 降级检索失败: {e}")
            yield self._sse("tool_result", name="search_skill",
                            content="知识库检索失败，需要生成新大纲", error=True)

    async def _handle_get_current_outline(self, ctx: SkillContext, args: dict):
        session_id = args.get("session_id", ctx.session_id)
        try:
            state = await self._ch.get_outline_state(session_id)
            if not state or not state.get("outline_json"):
                yield self._sse("tool_result", name="get_current_outline",
                                content="当前会话暂无大纲", error=True)
                return
            yield self._sse("tool_result", name="get_current_outline",
                            content=json.dumps(state["outline_json"], ensure_ascii=False))
        except Exception as e:
            yield self._sse("tool_result", name="get_current_outline",
                            content=f"获取大纲失败: {e}", error=True)

    async def _handle_clip_outline(self, ctx: SkillContext, args: dict):
        """复用 outline-clip Executor"""
        executor = self._loader.get_executor("outline-clip")
        if not executor:
            yield self._sse("tool_result", name="clip_outline",
                            content="outline-clip executor 未加载", error=True)
            return

        state = await self._ch.get_outline_state(ctx.session_id)
        if state and state.get("outline_json"):
            ctx.current_outline = state["outline_json"]

        ctx.params["instructions"] = args.get("instruction", ctx.user_message)

        async for item in executor.execute(ctx):
            if isinstance(item, SkillResult):
                if item.success:
                    if item.data.get("updated_outline"):
                        await self._ch.save_outline_state(
                            ctx.session_id, item.data["updated_outline"]
                        )
                    yield self._sse("tool_result", name="clip_outline",
                                    content=item.summary or "大纲裁剪完成")
                else:
                    yield self._sse("tool_result", name="clip_outline",
                                    content=item.summary or "裁剪失败", error=True)
            elif isinstance(item, str):
                yield item

    async def _handle_inject_params(self, ctx: SkillContext, args: dict):
        """复用 param-inject Executor"""
        executor = self._loader.get_executor("param-inject")
        if not executor:
            yield self._sse("tool_result", name="inject_params",
                            content="param-inject executor 未加载", error=True)
            return

        ctx.params["param_key"] = args.get("param_key", "")
        ctx.params["param_value"] = args.get("param_value", "")
        ctx.params["target_node"] = args.get("target_node", "")

        async for item in executor.execute(ctx):
            if isinstance(item, SkillResult):
                result_content = item.summary or ("参数注入成功" if item.success else "参数注入失败")
                yield self._sse("tool_result", name="inject_params",
                                content=result_content, error=not item.success)
            elif isinstance(item, str):
                yield item

    async def _handle_execute_data(self, ctx: SkillContext, args: dict):
        """复用 data-execute Executor"""
        executor = self._loader.get_executor("data-execute")
        if not executor:
            yield self._sse("tool_result", name="execute_data",
                            content="data-execute executor 未加载", error=True)
            return

        state = await self._ch.get_outline_state(ctx.session_id)
        if state and state.get("outline_json"):
            ctx.current_outline = state["outline_json"]

        data_results = {}
        async for item in executor.execute(ctx):
            if isinstance(item, SkillResult):
                if item.success:
                    data_results = item.data.get("data_results", {})
                    ctx.step_results["data_results"] = data_results
                    yield self._sse("tool_result", name="execute_data",
                                    content=json.dumps(
                                        {"success": True, "node_count": len(data_results)},
                                        ensure_ascii=False
                                    ))
                else:
                    yield self._sse("tool_result", name="execute_data",
                                    content=item.summary or "数据执行失败", error=True)
            elif isinstance(item, str):
                yield item

    async def _handle_render_report(self, ctx: SkillContext, args: dict):
        """复用 report-generate Executor"""
        executor = self._loader.get_executor("report-generate")
        if not executor:
            yield self._sse("tool_result", name="render_report",
                            content="report-generate executor 未加载", error=True)
            return

        state = await self._ch.get_outline_state(ctx.session_id)
        if state and state.get("outline_json"):
            ctx.current_outline = state["outline_json"]

        async for item in executor.execute(ctx):
            if isinstance(item, SkillResult):
                result_content = item.summary or ("报告生成完成" if item.success else "报告生成失败")
                yield self._sse("tool_result", name="render_report",
                                content=result_content, error=not item.success)
            elif isinstance(item, str):
                yield item

    # ─── 设计态工具（skill-factory 六步）──────────────────────────────────────

    async def _handle_skill_factory_step(self, ctx: SkillContext, step_name: str):
        """通用的 skill-factory 子步骤执行器"""
        executor = self._loader.get_executor("skill-factory")
        if not executor:
            yield self._sse("tool_result", name=step_name,
                            content="skill-factory executor 未加载", error=True)
            return

        ctx.params["__react_step__"] = step_name

        if hasattr(executor, "execute_step"):
            async for item in executor.execute_step(ctx, step_name):
                if isinstance(item, SkillResult):
                    yield self._sse("tool_result", name=step_name,
                                    content=item.summary or step_name,
                                    error=not item.success,
                                    data=item.data)
                elif isinstance(item, str):
                    yield item
        else:
            async for item in executor.execute(ctx):
                if isinstance(item, SkillResult):
                    yield self._sse("tool_result", name=step_name,
                                    content=item.summary or step_name,
                                    error=not item.success)
                    return
                elif isinstance(item, str):
                    yield item

    async def _handle_understand_intent(self, ctx: SkillContext, args: dict):
        ctx.params["expert_input"] = args.get("expert_input", ctx.user_message)
        ctx.params["mode"] = "preview_only"
        async for item in self._handle_skill_factory_step(ctx, "understand_intent"):
            yield item

    async def _handle_extract_structure(self, ctx: SkillContext, args: dict):
        ctx.params["expert_input"] = args.get("raw_input", ctx.user_message)
        async for item in self._handle_skill_factory_step(ctx, "extract_structure"):
            yield item

    async def _handle_design_outline(self, ctx: SkillContext, args: dict):
        async for item in self._handle_skill_factory_step(ctx, "design_outline"):
            yield item

    async def _handle_bind_data(self, ctx: SkillContext, args: dict):
        async for item in self._handle_skill_factory_step(ctx, "bind_data"):
            yield item

    async def _handle_preview_report(self, ctx: SkillContext, args: dict):
        async for item in self._handle_skill_factory_step(ctx, "preview_report"):
            yield item

    async def _handle_persist_skill(self, ctx: SkillContext, args: dict):
        ctx.params["mode"] = "persist_only"
        ctx.params["saved_context"] = args.get("context_key", ctx.session_id)
        executor = self._loader.get_executor("skill-factory")
        if not executor:
            yield self._sse("tool_result", name="persist_skill",
                            content="skill-factory executor 未加载", error=True)
            return

        async for item in executor.execute(ctx):
            if isinstance(item, SkillResult):
                yield self._sse("tool_result", name="persist_skill",
                                content=item.summary or ("沉淀成功" if item.success else "沉淀失败"),
                                error=not item.success)
            elif isinstance(item, str):
                yield item

    # ─── 工具方法 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _sse(event_type: str, name: str = "", content: str = "",
             error: bool = False, data: dict = None) -> str:
        payload = {"type": event_type, "tool_name": name, "content": content}
        if error:
            payload["error"] = True
        if data:
            payload["data"] = data
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _summarize_outline(outline_json: Any, max_items: int = 8) -> str:
        """生成大纲的简要摘要，供状态查询返回"""
        if not outline_json or not isinstance(outline_json, dict):
            return ""
        items = []

        def _walk(node, depth=0):
            if not isinstance(node, dict):
                return
            if len(items) >= max_items:
                return
            name = node.get("name", "")
            level = node.get("level", 0)
            if name and level > 1:
                items.append("  " * max(depth - 1, 0) + f"- {name} (L{level})")
            for child in node.get("children", []):
                _walk(child, depth + 1)

        _walk(outline_json)
        return "\n".join(items)
