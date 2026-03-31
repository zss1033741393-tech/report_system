"""Sub-Step 4.5：段落模板上下文裁剪对齐。

结合用户看网逻辑，并发对每个 L5 节点的 paragraph.content 做裁剪对齐：
- 删除与用户逻辑无关的 metrics 占位符
- 细微调整 content 措辞以贴合场景
- 失败不阻断，保留原模板
"""
import asyncio
import json
import logging
from typing import AsyncGenerator

from llm.agent_llm import AgentLLM
from llm.config import SKILL_FACTORY_JSON_CONFIG
from sub_skills.base import SubSkillBase
from context import SkillFactoryContext
from agent.context import SkillContext

logger = logging.getLogger(__name__)


class ParagraphAlign(SubSkillBase):
    name = "paragraph_align"

    async def execute(self, fc: SkillFactoryContext, ctx: SkillContext) -> AsyncGenerator[str, None]:
        l5_nodes: list[dict] = []
        _collect_l5_nodes(fc.outline_json, l5_nodes)

        # 只对有非空 content 的节点做对齐
        alignable = [n for n in l5_nodes if n.get("paragraph", {}).get("content")]
        if not alignable:
            return
            yield

        await asyncio.gather(*[self._align_one(node, fc.raw_input, ctx) for node in alignable])

        # 同步更新 fc.bindings 中的 paragraph（bindings 是独立列表）
        bindings_by_id = {b["node_id"]: b for b in fc.bindings}
        for node in l5_nodes:
            nid = node.get("id", "")
            if nid in bindings_by_id:
                bindings_by_id[nid]["paragraph"] = node.get("paragraph", {})

        return
        yield

    async def _align_one(self, node: dict, raw_input: str, ctx: SkillContext):
        paragraph = node.get("paragraph", {})
        content = paragraph.get("content", "")
        metrics = paragraph.get("metrics", [])

        prompt = f"""你是报告段落优化专家。基于用户看网逻辑，判断当前段落模板是否需要裁剪。

## 用户看网逻辑
{raw_input[:800]}

## 当前段落模板
指标名称：{node.get("name", "")}
content：{content}
metrics：{json.dumps(metrics, ensure_ascii=False)}

## 任务
1. 如果某个 metric 变量与用户看网逻辑完全无关，从 metrics 列表和 content 占位符中删除它
2. 可对 content 措辞做小幅调整以贴合用户场景（行业名称、分析角度等）
3. 如果不需要修改，原样返回

输出 JSON（```json ``` 代码块包裹）：
{{"content": "调整后或原模板", "metrics": ["保留的指标列表"]}}"""

        agent = AgentLLM(
            self._svc.llm, "", SKILL_FACTORY_JSON_CONFIG,
            trace_callback=ctx.trace_callback,
            llm_type="skill_factory",
            step_name="paragraph_align",
        )
        try:
            result = await agent.chat_json(prompt)
            if result.get("content"):
                paragraph["content"] = result["content"]
            if isinstance(result.get("metrics"), list):
                paragraph["metrics"] = result["metrics"]
        except Exception as e:
            logger.warning(f"paragraph_align 单节点失败 node={node.get('name')}: {e}")


def _collect_l5_nodes(node: dict, result: list):
    """递归收集所有 L5 节点的引用（就地修改用）。"""
    if not node:
        return
    if node.get("level") == 5:
        result.append(node)
        return
    for child in node.get("children", []):
        _collect_l5_nodes(child, result)
