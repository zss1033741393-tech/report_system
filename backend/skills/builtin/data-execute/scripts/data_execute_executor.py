"""数据执行器。按大纲顺序执行各节点的数据绑定。"""
import json
import logging
from typing import AsyncGenerator, Union
from agent.context import SkillContext, SkillResult
from services.session_service import SessionService
from services.kb_content_store import KBContentStore
from services.data.mock_data_service import MockDataService

logger = logging.getLogger(__name__)


class DataExecuteExecutor:

    def __init__(self, session_service: SessionService, kb_store: KBContentStore):
        self._session = session_service
        self._kb = kb_store
        self._mock = MockDataService()

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        outline = ctx.params.get("outline_json") or ctx.current_outline
        if not outline:
            yield SkillResult(False, "没有可执行的大纲")
            return

        # 从 Redis 取会话条件
        key = f"conditions:{ctx.session_id}"
        raw = await self._session.redis.get(key)
        conditions = json.loads(raw) if raw else {}

        # 从会话或参数取绑定配置
        bindings_raw = ctx.params.get("bindings", [])
        bindings_map = {b["node_name"]: b for b in bindings_raw} if bindings_raw else {}

        yield json.dumps({"type": "thinking_step", "step": "data_execute",
                          "status": "running", "detail": "正在执行数据查询..."}, ensure_ascii=False)

        # 遍历大纲，收集 L5 节点并执行
        results = {}
        l5_nodes = []
        self._collect_l5(outline, l5_nodes)

        for node in l5_nodes:
            node_name = node.get("name", "")
            yield json.dumps({"type": "data_executing", "node_name": node_name, "status": "running"}, ensure_ascii=False)

            # 取绑定配置（优先参数传入，其次从 kb_contents 匹配）
            binding = bindings_map.get(node_name, {
                "node_name": node_name, "binding_type": "mock",
                "mock_config": {"data_type": "TABLE", "params": {}},
            })

            # 合并条件参数
            params = dict(binding.get("mock_config", {}).get("params", {}))
            for pk, pv_info in conditions.items():
                if isinstance(pv_info, dict):
                    target = pv_info.get("target_node", "")
                    if not target or target == node_name:
                        params[pk] = pv_info.get("value", "")
                else:
                    params[pk] = pv_info

            try:
                data = await self._mock.execute(binding, params)
                results[node_name] = data
                yield json.dumps({"type": "data_executed", "node_name": node_name,
                                  "data_preview": {"data_type": data.get("data_type"), "title": data.get("title")}},
                                 ensure_ascii=False)
            except Exception as e:
                logger.warning(f"数据执行失败 {node_name}: {e}")
                yield json.dumps({"type": "data_executed", "node_name": node_name,
                                  "data_preview": {"error": str(e)}}, ensure_ascii=False)

        yield json.dumps({"type": "thinking_step", "step": "data_execute",
                          "status": "done", "detail": f"数据查询完成，共 {len(results)} 个指标"}, ensure_ascii=False)

        yield SkillResult(True, f"数据执行完成，{len(results)} 个指标",
                          data={"data_results": results, "executed_count": len(results)})

    @staticmethod
    def _collect_l5(node, result):
        level = node.get("level", 0)
        children = node.get("children", [])
        # L5 指标节点，或无子节点的 L4 叶子节点（大纲未包含 L5 时的降级处理）
        if level == 5 or (level == 4 and not children):
            result.append(node)
        for child in children:
            DataExecuteExecutor._collect_l5(child, result)
