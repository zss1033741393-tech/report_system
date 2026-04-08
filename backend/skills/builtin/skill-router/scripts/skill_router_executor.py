"""SkillRouterExecutor —— 看网能力动态路由。

扫描已沉淀的自定义 Skill，通过 LLM 精排返回候选列表，
推送 skill_candidates SSE 事件并保存 Redis 供 LeadAgent 拦截。
"""
import json
import logging
import os
import re
from typing import AsyncGenerator, Union

import yaml

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

    def __init__(self, llm_service, skill_registry, session_service):
        self._llm = llm_service
        self._reg = skill_registry
        self._ss = session_service

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        query = ctx.params.get("query", ctx.user_message)
        sid = ctx.session_id

        if not getattr(settings, "SKILL_ROUTER_ENABLED", True):
            yield SkillResult(True, "skill_router 已禁用", data={"candidates": []})
            return

        # Step 1: 扫描自定义 Skill 目录
        yield json.dumps({"type": "thinking_step", "step": "skill_router",
                          "status": "running", "detail": "正在扫描已沉淀的看网能力..."}, ensure_ascii=False)

        custom_dir = "skills/custom"
        skill_metas = []
        if os.path.isdir(custom_dir):
            for entry in sorted(os.listdir(custom_dir)):
                skill_dir = os.path.join(custom_dir, entry)
                if not os.path.isdir(skill_dir):
                    continue
                meta = self._load_skill_meta_full(skill_dir)
                if meta:
                    skill_metas.append(meta)

        if not skill_metas:
            yield json.dumps({"type": "thinking_step", "step": "skill_router",
                              "status": "done", "detail": "暂无已沉淀的看网能力"}, ensure_ascii=False)
            yield SkillResult(True, "无已沉淀能力", data={"candidates": []})
            return

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
                "skill_dir": m["skill_dir"],
                "display_name": m.get("display_name", m["skill_id"]),
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

        # 构建能力列表文本
        lines = []
        for m in skill_metas:
            kw_str = "、".join(m.get("keywords", [])[:5])
            qv_str = "、".join(m.get("query_variants", [])[:3])
            lines.append(
                f'skill_id={m["skill_id"]}\n'
                f'  名称: {m.get("display_name", m["skill_id"])}\n'
                f'  场景: {m.get("scene_intro", "")}\n'
                f'  关键词: {kw_str}\n'
                f'  触发问法示例: {qv_str}\n'
                f'  看网逻辑摘要: {m.get("logic_summary", "")[:100]}'
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
            # 兼容旧格式：如果 matches 项是字符串，转为 dict
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

    @staticmethod
    def _load_skill_meta_full(skill_dir: str) -> dict:
        """读取 Skill 元数据：SKILL.md frontmatter + query_variants + 看网逻辑摘要。"""
        skill_md_path = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(skill_md_path):
            return {}

        try:
            with open(skill_md_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 解析 YAML frontmatter
            fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
            if not fm_match:
                return {}
            frontmatter = yaml.safe_load(fm_match.group(1)) or {}

            # 提取看网逻辑摘要（## 看网逻辑 段落）
            logic_match = re.search(r"##\s*看网逻辑\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
            logic_summary = logic_match.group(1).strip()[:200] if logic_match else ""

            # 读取 query_variants
            qv_path = os.path.join(skill_dir, "references", "query_variants.txt")
            query_variants = []
            if os.path.isfile(qv_path):
                with open(qv_path, "r", encoding="utf-8") as f:
                    query_variants = [line.strip() for line in f if line.strip()]

            skill_name = frontmatter.get("name", os.path.basename(skill_dir))
            return {
                "skill_id": skill_name,
                "skill_dir": skill_dir,
                "display_name": frontmatter.get("display_name", skill_name),
                "scene_intro": frontmatter.get("scene_intro", ""),
                "keywords": frontmatter.get("keywords", []) if isinstance(frontmatter.get("keywords"), list) else [],
                "query_variants": query_variants,
                "logic_summary": logic_summary,
            }
        except Exception as e:
            logger.warning(f"加载 Skill 元数据失败: {skill_dir}, {e}")
            return {}
