"""参数透传注入执行器。精准到 node_id，支持运算符。"""
import json
import logging
from typing import AsyncGenerator, Union
from agent.context import SkillContext, SkillResult
from services.session_service import SessionService

logger = logging.getLogger(__name__)


class ParamInjectExecutor:

    def __init__(self, session_service: SessionService):
        self._session = session_service

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        node_id = ctx.params.get("node_id", "")
        pk = ctx.params.get("param_key", "")
        pv = ctx.params.get("param_value", "")
        operator = ctx.params.get("operator", "eq")

        if not pk or not pv:
            yield SkillResult(False, "缺少参数名或参数值",
                              need_user_input=True, user_prompt="请指明要修改哪个参数及其新值")
            return

        yield json.dumps({"type": "thinking_step", "step": "param_inject",
                          "status": "running",
                          "detail": f"注入参数: {pk} {operator} {pv} → {'节点 ' + node_id if node_id else '全局'}"},
                         ensure_ascii=False)

        param_info = {
            "value": pv,
            "operator": operator,
            "display": f"{pk} {operator} {pv}",
        }

        if node_id:
            # 精准到 L5 节点
            key = f"node_params:{ctx.session_id}:{node_id}"
        else:
            # 全局注入（兼容旧逻辑）
            key = f"conditions:{ctx.session_id}"

        raw = await self._session.redis.get(key)
        params_store = json.loads(raw) if raw else {}
        params_store[pk] = param_info
        await self._session.redis.setex(key, 3600, json.dumps(params_store, ensure_ascii=False))

        # 同时将参数写入会话大纲对应 L5 节点的 paragraph.params（就地更新并持久化）
        if node_id:
            await self._update_outline_node_params(ctx, node_id, pk, param_info)

        yield json.dumps({"type": "thinking_step", "step": "param_inject",
                          "status": "done",
                          "detail": f"参数已注入: {pk} {operator} {pv}"},
                         ensure_ascii=False)

        yield SkillResult(True, f"已注入参数 {pk} {operator} {pv} → {'节点 ' + node_id if node_id else '全局'}",
                          data={"node_id": node_id, "param_key": pk, "param_value": pv,
                                "operator": operator, "params_store": params_store})

    async def _update_outline_node_params(self, ctx: SkillContext, node_id: str, param_key: str, param_info: dict):
        """将参数写入会话大纲对应 L5 节点的 paragraph.params，并持久化。"""
        try:
            from main import app_state
            chat_history = app_state.get("chat_history")
            if not chat_history:
                return
            state = await chat_history.get_outline_state(ctx.session_id)
            if not state or not state.get("outline_json"):
                return
            outline = state["outline_json"]
            node = _find_node_by_id(outline, node_id)
            if node:
                node.setdefault("paragraph", {}).setdefault("params", {})[param_key] = param_info
                await chat_history.save_outline_state(ctx.session_id, outline)
        except Exception as e:
            logger.warning(f"更新大纲节点参数失败 node_id={node_id}: {e}")


def _find_node_by_id(node: dict, target_id: str) -> dict | None:
    """在大纲树中按 id 查找节点。"""
    if node.get("id") == target_id:
        return node
    for child in node.get("children", []):
        result = _find_node_by_id(child, target_id)
        if result:
            return result
    return None
