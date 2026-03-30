"""Sub-Step 4：数据源绑定。"""
from typing import AsyncGenerator
from sub_skills.base import SubSkillBase
from context import SkillFactoryContext
from agent.context import SkillContext


class DataBinding(SubSkillBase):
    name = "data_binding"

    async def execute(self, fc: SkillFactoryContext, ctx: SkillContext) -> AsyncGenerator[str, None]:
        bindings = []
        _collect_l5_bindings(fc.outline_json, bindings)
        fc.bindings = bindings
        return
        yield


def _collect_l5_bindings(node: dict, bindings: list):
    if not node:
        return
    level = node.get("level", 0)
    children = node.get("children", [])
    # L5 指标节点，或无子节点的 L4 叶子节点（大纲未包含 L5 时的降级处理）
    if level == 5 or (level == 4 and not children):
        bindings.append({
            "node_id": node.get("id", ""),
            "node_name": node.get("name", ""),
            "binding_type": "mock",
            "mock_config": {"data_type": "TABLE", "params": {}},
            "sql_config": None, "api_config": None,
        })
    for child in children:
        _collect_l5_bindings(child, bindings)
