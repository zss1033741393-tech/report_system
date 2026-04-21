"""SkillRouterExecutor —— 看网能力动态路由——纯算法，不含 LLM 调用。

LLM 精排（matched_ids）已上移至 tool_definitions._skill_router。
executor 只负责：查询 outlines 表 → 构建候选列表 → 推送 SSE。
"""
import json
import logging
from typing import AsyncGenerator, Union

from agent.context import SkillContext, SkillResult
from config import settings

logger = logging.getLogger(__name__)


class SkillRouterExecutor:

    def __init__(self, outline_store, session_service):
        self._store = outline_store
        self._ss = session_service

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        query = ctx.params.get("query", ctx.user_message)

        if not getattr(settings, "SKILL_ROUTER_ENABLED", True):
            yield SkillResult(True, "skill_router 已禁用", data={"candidates": []})
            return

        # Step 1: 查询 DB 中已激活的大纲
        yield json.dumps({"type": "thinking_step", "step": "skill_router",
                          "status": "running", "detail": "正在检索已沉淀的看网能力..."}, ensure_ascii=False)

        try:
            rows = await self._store.list_active_outlines_for_router()
        except Exception as e:
            logger.error(f"skill_router: 查询 outlines 表失败: {e}", exc_info=True)
            rows = []

        if not rows:
            yield json.dumps({"type": "thinking_step", "step": "skill_router",
                              "status": "done", "detail": "暂无已沉淀的看网能力"}, ensure_ascii=False)
            yield SkillResult(True, "无已沉淀能力", data={"candidates": []})
            return

        # 构建元数据列表
        skill_metas = []
        for row in rows:
            skill_metas.append({
                "skill_id": row["skill_name"],
                "outline_id": row["id"],
                "display_name": row.get("display_name") or row["skill_name"],
                "scene_intro": row.get("scene_intro", ""),
                "keywords": row.get("keywords") or [],
                "query_variants": row.get("query_variants") or [],
            })

        yield json.dumps({"type": "thinking_step", "step": "skill_router",
                          "status": "running",
                          "detail": f"找到 {len(skill_metas)} 个已沉淀能力，等待精排..."}, ensure_ascii=False)

        # Step 2: 接收 tool 层 LLM 预计算的精排结果（executor 不调 LLM）
        matched_ids = ctx.params.get("matched_ids", [])

        # Step 3: 构建候选列表
        meta_map = {m["skill_id"]: m for m in skill_metas}
        labels = ["A", "B", "C", "D", "E"]
        candidates = []
        for i, match_item in enumerate(matched_ids[:5]):
            sid_key = match_item.get("skill_id", "") if isinstance(match_item, dict) else match_item
            m = meta_map.get(sid_key)
            if not m:
                continue
            desc = match_item.get("description", "") if isinstance(match_item, dict) else ""
            candidates.append({
                "label": labels[i],
                "skill_id": m["skill_id"],
                "outline_id": m["outline_id"],
                "display_name": m["display_name"],
                "scene_intro": m.get("scene_intro", ""),
                "keywords": m.get("keywords", []),
                "description": desc,
            })

        yield json.dumps({"type": "thinking_step", "step": "skill_router",
                          "status": "done",
                          "detail": f"精排完成，{len(candidates)} 个候选"}, ensure_ascii=False)

        # Step 4: 推送 SSE + 保存 Redis
        if candidates:
            await self._ss.set_skill_candidates(ctx.session_id, {
                "candidates": candidates,
                "query": query,
            })
            yield json.dumps({
                "type": "skill_candidates",
                "candidates": candidates,
                "query": query,
            }, ensure_ascii=False)

        yield SkillResult(True, f"路由完成，{len(candidates)} 个候选",
                          data={"candidates": candidates, "query": query})
