"""数据执行器。按大纲顺序执行各节点的数据绑定，支持 node_id 精准参数注入。"""
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

        # 全局条件（兼容旧逻辑）
        global_key = f"conditions:{ctx.session_id}"
        raw = await self._session.redis.get(global_key)
        global_conditions = json.loads(raw) if raw else {}

        yield json.dumps({"type": "thinking_step", "step": "data_execute",
                          "status": "running", "detail": "正在执行数据查询..."}, ensure_ascii=False)

        results = {}
        l5_nodes = []
        self._collect_l5(outline, l5_nodes)

        for node in l5_nodes:
            node_id = node.get("id", "")
            node_name = node.get("name", "")
            paragraph = node.get("paragraph", {})

            yield json.dumps({"type": "data_executing", "node_name": node_name, "status": "running"}, ensure_ascii=False)

            # 合并参数（优先级从低到高：全局条件 < 节点精准注入 < paragraph.params 内置）
            merged_params: dict = {}

            # 1. 全局条件（最低优先级）
            for pk, pv_info in global_conditions.items():
                if isinstance(pv_info, dict):
                    merged_params[pk] = pv_info.get("value", "")
                else:
                    merged_params[pk] = pv_info

            # 2. 节点精准注入参数（覆盖全局）
            if node_id:
                node_key = f"node_params:{ctx.session_id}:{node_id}"
                raw_node = await self._session.redis.get(node_key)
                node_params = json.loads(raw_node) if raw_node else {}
                for pk, pv_info in node_params.items():
                    if isinstance(pv_info, dict):
                        merged_params[pk] = pv_info.get("value", "")
                    else:
                        merged_params[pk] = pv_info

            # 3. paragraph.params 内置参数（最高优先级）
            for pk, pv_info in paragraph.get("params", {}).items():
                if isinstance(pv_info, dict):
                    merged_params[pk] = pv_info.get("value", "")
                else:
                    merged_params[pk] = pv_info

            # 构建 binding_config（兼容 MockDataService.execute 接口）
            binding_config = {
                "node_name": node_name,
                "binding_type": paragraph.get("data_source", "Mock").lower() if paragraph else "mock",
                "mock_config": {"data_type": "", "params": {}},
            }

            try:
                data = await self._mock.execute(binding_config, merged_params)
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
        if node.get("level") == 5:
            result.append(node)
        for child in node.get("children", []):
            DataExecuteExecutor._collect_l5(child, result)
