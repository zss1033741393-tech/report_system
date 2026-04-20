"""SkillRouterExecutor —— 看网能力动态路由。

查询 outlines 表中 status IN ('active','approved') 的已沉淀大纲，
通过 LLM 精排返回候选列表，推送 skill_candidates SSE 事件并保存 Redis 供 LeadAgent 拦截。
"""
import json
import logging
from typing import AsyncGenerator, Union

from agent.context import SkillContext, SkillResult
from config import settings

logger = logging.getLogger(__name__)

ROUTER_SYSTEM_PROMPT = """\
你是看网能力路由专家。根据用户的分析需求，从已沉淀的看网能力列表中找出最相关的候选项，并为每个候选生成简短的差异化描述帮助用户选择。

## 输出格式
用 ```json ``` 代码块包裹，格式：
```json
{"matches": [{"skill_id": "skill_id1", "description": "该方案侧重于..."}, {"skill_id": "skill_id2", "description": "该方案侧重于..."}]}
```
- matches 为匹配的候选列表，最多 5 个，按相关度从高到低排列
- 每个候选包含 skill_id 和 description 两个字段
- description 规则：
  - 多个候选时：突出该方案与其他候选的差异点（如分析维度、侧重场景、数据来源的不同），30-50字
  - 仅一个候选时：简要说明该能力适合的场景，30字以内
- 若无匹配则返回空列表：{"matches": []}
- 只输出 JSON，不要加解释文字
"""


class SkillRouterExecutor:

    def __init__(self, llm_service, outline_store, session_service):
        self._llm = llm_service
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
                          "detail": f"找到 {len(skill_metas)} 个已沉淀能力，正在 LLM 精排..."}, ensure_ascii=False)

        # Step 2: LLM 精排
        matched_ids = await self._llm_select_skills(
            query, skill_metas, trace_callback=ctx.trace_callback
        )

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

    async def _llm_select_skills(self, query: str, skill_metas: list,
                                  trace_callback=None) -> list:
        """独立 LLM 调用精排 Skill，返回 [{"skill_id": str, "description": str}, ...]。"""
        from llm.config import SKILL_ROUTER_CONFIG
        from llm.agent_llm import AgentLLM

        lines = []
        for m in skill_metas:
            kw_str = "、".join(m.get("keywords", [])[:5])
            qv_str = "、".join(m.get("query_variants", [])[:3])
            lines.append(
                f'skill_id={m["skill_id"]}\n'
                f'  名称: {m.get("display_name", m["skill_id"])}\n'
                f'  场景: {m.get("scene_intro", "")}\n'
                f'  关键词: {kw_str}\n'
                f'  触发问法示例: {qv_str}'
            )

        skill_list_text = "\n\n".join(lines)
        user_msg = f"## 用户需求\n{query}\n\n## 已沉淀看网能力列表\n{skill_list_text}"

        try:
            agent = AgentLLM(
                self._llm,
                system_prompt=ROUTER_SYSTEM_PROMPT,
                config=SKILL_ROUTER_CONFIG,
                trace_callback=trace_callback,
                llm_type="skill_router",
                step_name="skill_router_select",
            )
            data = await agent.chat_json(user_msg)
            raw_matches = data.get("matches", [])
            result = []
            for item in raw_matches:
                if isinstance(item, str):
                    result.append({"skill_id": item, "description": ""})
                elif isinstance(item, dict) and "skill_id" in item:
                    result.append({"skill_id": item["skill_id"], "description": item.get("description", "")})
            return result
        except Exception as e:
            logger.warning(f"skill_router LLM 精排失败，返回空候选: {e}")
            return []
