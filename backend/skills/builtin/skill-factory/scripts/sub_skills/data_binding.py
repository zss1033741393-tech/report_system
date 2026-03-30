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
    if node.get("level") == 5:
        bindings.append({
            "node_id": node.get("id", ""),
            "node_name": node.get("name", ""),
            "binding_type": "mock",
            "mock_config": {"data_type": "", "params": {}},  # 留空让 MockDataService 查 MOCK_DATA_REGISTRY
            "sql_config": None, "api_config": None,
        })
    for child in node.get("children", []):
        _collect_l5_bindings(child, bindings)
