"""Sub-Step 6：能力沉淀——写文件系统 + Neo4j + FAISS。"""
import json, logging, os
from typing import AsyncGenerator
from sub_skills.base import SubSkillBase
from context import SkillFactoryContext, sse_event
from agent.context import SkillContext

logger = logging.getLogger(__name__)


class SkillPersist(SubSkillBase):
    name = "skill_persist"

    async def execute(self, fc: SkillFactoryContext, ctx: SkillContext) -> AsyncGenerator[str, None]:
        # 1. 写文件系统
        base_dir = f"skills/custom/{fc.skill_name}"
        skill_dir = _resolve_versioned_dir(base_dir)
        os.makedirs(f"{skill_dir}/references", exist_ok=True)

        skill_md = f"""---
name: {fc.skill_name}
display_name: {fc.scene_intro or fc.skill_name}
scene_intro: {fc.scene_intro}
keywords: {json.dumps(fc.keywords, ensure_ascii=False)}
source: {fc.source}
version: {fc.version}
enabled: true
---

## 看网逻辑

{fc.raw_input}

## References

- [大纲结构](references/outline.json)
- [数据绑定](references/bindings.json)
- [触发问法](references/query_variants.txt)
"""
        with open(f"{skill_dir}/SKILL.md", "w", encoding="utf-8") as f:
            f.write(skill_md)

        if fc.outline_json and fc.outline_json.get("children"):
            with open(f"{skill_dir}/references/outline.json", "w", encoding="utf-8") as f:
                json.dump(fc.outline_json, f, ensure_ascii=False, indent=2)
        else:
            logger.warning(f"大纲为空，跳过 outline.json 写入: {skill_dir}")

        with open(f"{skill_dir}/references/bindings.json", "w", encoding="utf-8") as f:
            json.dump({"version": 1, "bindings": fc.bindings}, f, ensure_ascii=False, indent=2)
        with open(f"{skill_dir}/references/query_variants.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(fc.query_variants))

        # 写入 indicators.json（Skill 专属 paragraph 模板，供运行态 IndicatorResolver 优先读取）
        indicators = {}
        for binding in fc.bindings:
            node_id = binding.get("node_id", "")
            if node_id:
                indicators[node_id] = {
                    "indicator_name": binding.get("node_name", ""),
                    "paragraph": binding.get("paragraph", {
                        "content": "", "metrics": [], "tables": [], "data_source": "Mock", "params": {}
                    }),
                }
        with open(f"{skill_dir}/references/indicators.json", "w", encoding="utf-8") as f:
            json.dump(indicators, f, ensure_ascii=False, indent=2)
        logger.info(f"SkillPersist: 写入 indicators.json → {skill_dir}/references/indicators.json，共 {len(indicators)} 个指标")

        fc.skill_dir = skill_dir

        # 2. Neo4j：挂载 skill_path
        if fc.anchor_node_id:
            await self._svc.neo4j.set_skill_path(fc.anchor_node_id, skill_dir)
        if fc.new_nodes:
            await self._svc.neo4j.create_nodes_and_relations(fc.new_nodes)

        yield sse_event("skill_persisted", {
            "skill_name": fc.skill_name, "skill_dir": skill_dir, "version": fc.version,
        })


def _resolve_versioned_dir(base_dir: str) -> str:
    if not os.path.exists(base_dir):
        return base_dir
    v = 2
    while os.path.exists(f"{base_dir}_v{v}"):
        v += 1
    return f"{base_dir}_v{v}"
