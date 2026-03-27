"""skill-factory 元技能执行器 v5。

纯编排器——SubSkill 独立模块实现，executor 只负责模式路由和执行编排。
支持 4 种模式：full / preview_only / persist_only / persist_current。
"""
import json, logging, os, sys
from typing import AsyncGenerator, Union

# 把 scripts 目录加入 sys.path，使 context / sub_skills 可直接 import
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from agent.context import SkillContext, SkillResult
from context import SkillFactoryContext, ServiceBundle, sse_event, design_step
from sub_skills import (
    IntentUnderstand, StructExtract, OutlineDesign, DataBinding, ReportPreview, SkillPersist,
)
from sub_skills.data_binding import _collect_l5_bindings
from sub_skills.outline_design import outline_to_md

logger = logging.getLogger(__name__)


class SkillFactoryExecutor:
    """元技能执行器——纯编排。"""

    def __init__(self, llm_service, embedding_service, faiss_retriever,
                 neo4j_retriever, outline_renderer, session_service, kb_store):
        self._svc = ServiceBundle(llm_service, embedding_service, faiss_retriever,
                                   neo4j_retriever, outline_renderer, session_service, kb_store)

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        mode = ctx.params.get("mode", "full")
        expert_input = ctx.params.get("expert_input", ctx.user_message)
        saved_key = ctx.params.get("saved_context", "")

        # ─── persist_only：从 Redis 缓存恢复 ───
        if mode == "persist_only":
            async for event in self._persist_only(ctx, saved_key):
                yield event
            return

        # ─── persist_current：从当前会话大纲直接沉淀 ───
        if mode == "persist_current":
            async for event in self._persist_current(ctx, expert_input):
                yield event
            return

        # ─── full / preview_only：完整流程 ───
        fc = SkillFactoryContext(raw_input=expert_input, mode=mode)

        # 执行 Sub-Step 1-5
        steps = [IntentUnderstand, StructExtract, OutlineDesign, DataBinding, ReportPreview]
        for StepClass in steps:
            step = StepClass(self._svc)
            async for event in step.run(fc, ctx):
                yield event

        if mode == "preview_only":
            # 缓存 + 提示沉淀
            cache_key = ctx.session_id
            await self._svc.session.redis.setex(
                f"skill_factory_ctx:{cache_key}", 3600,
                json.dumps(fc.to_cache_dict(), ensure_ascii=False)
            )
            yield sse_event("persist_prompt", {
                "message": "报告预览完成。是否将此次推理保存为新的看网能力？",
                "context_key": cache_key,
            })
            yield SkillResult(True, "报告预览完成",
                              data={"context_key": cache_key, "outline_md": fc.outline_md,
                                    "outline_json": fc.outline_json, "skill_name": fc.skill_name,
                                    "report_html": fc.report_html})
            return

        # full 模式：执行 Step 6
        persist = SkillPersist(self._svc)
        async for event in persist.run(fc, ctx):
            yield event

        yield SkillResult(True, f"看网能力「{fc.skill_name}」已创建并沉淀",
                          data={"skill_dir": fc.skill_dir, "skill_name": fc.skill_name,
                                "outline_md": fc.outline_md, "outline_json": fc.outline_json,
                                "report_html": fc.report_html})

    # ─── 模式处理 ───

    async def _persist_only(self, ctx, saved_key):
        if not saved_key:
            yield SkillResult(False, "persist_only 模式需要 saved_context 参数"); return
        cached = await self._svc.session.redis.get(f"skill_factory_ctx:{saved_key}")
        if not cached:
            yield SkillResult(False, "缓存已过期，请重新执行"); return
        fc = SkillFactoryContext.from_cache_dict(json.loads(cached))
        persist = SkillPersist(self._svc)
        async for event in persist.run(fc, ctx):
            yield event
        yield SkillResult(True, f"看网能力「{fc.skill_name}」已沉淀",
                          data={"skill_dir": fc.skill_dir, "skill_name": fc.skill_name})

    async def _persist_current(self, ctx, expert_input):
        if not ctx.current_outline:
            yield SkillResult(False, "当前没有大纲，无法保存"); return

        yield design_step("skill_persist", "running")
        fc = SkillFactoryContext(raw_input=expert_input, mode="persist_current")
        fc.outline_json = ctx.current_outline
        fc.outline_md = outline_to_md(ctx.current_outline)

        # 快速提取 skill_name
        from llm.agent_llm import AgentLLM
        from llm.config import SKILL_FACTORY_JSON_CONFIG
        try:
            agent = AgentLLM(self._svc.llm, "", SKILL_FACTORY_JSON_CONFIG,
                             trace_callback=ctx.trace_callback, llm_type="skill_factory", step_name="quick_extract")
            r = await agent.chat_json(
                f"从以下大纲提取：skill_name(英文), scene_intro(50字), keywords(3-5个), query_variants(3种问法)。\n\n"
                f"大纲：\n{fc.outline_md[:500]}\n\n用 ```json ``` 代码块包裹输出。"
            )
            fc.skill_name = r.get("skill_name", "unnamed_skill")
            fc.scene_intro = r.get("scene_intro", "")
            fc.keywords = r.get("keywords", [])
            fc.query_variants = r.get("query_variants", [])[:5]
        except Exception as e:
            logger.warning(f"快速提取失败: {e}")
            fc.skill_name = "unnamed_skill"

        fc.raw_input = expert_input
        bindings = []
        _collect_l5_bindings(fc.outline_json, bindings)
        fc.bindings = bindings

        persist = SkillPersist(self._svc)
        async for event in persist.run(fc, ctx):
            yield event
        yield SkillResult(True, f"看网能力「{fc.skill_name}」已沉淀",
                          data={"skill_dir": fc.skill_dir, "skill_name": fc.skill_name,
                                "outline_json": fc.outline_json})
