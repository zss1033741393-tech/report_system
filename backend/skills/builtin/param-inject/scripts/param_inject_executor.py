"""参数透传注入执行器。替代原 threshold-modify。"""
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
        target = ctx.params.get("target_node", "")
        pk = ctx.params.get("param_key", "")
        pv = ctx.params.get("param_value", "")

        if not pk or not pv:
            yield SkillResult(False, "缺少参数名或参数值",
                              need_user_input=True, user_prompt="请指明要修改哪个参数及其新值")
            return

        yield json.dumps({"type": "thinking_step", "step": "param_inject",
                          "status": "running", "detail": f"注入参数: {pk}={pv}"}, ensure_ascii=False)

        # 存到 Redis 会话条件
        key = f"conditions:{ctx.session_id}"
        raw = await self._session.redis.get(key)
        conditions = json.loads(raw) if raw else {}
        conditions[pk] = {"value": pv, "target_node": target, "display": f"{pk}={pv}"}
        await self._session.redis.setex(key, 3600, json.dumps(conditions, ensure_ascii=False))

        yield json.dumps({"type": "thinking_step", "step": "param_inject",
                          "status": "done", "detail": f"参数已注入: {pk}={pv}"}, ensure_ascii=False)

        yield SkillResult(True, f"已注入参数 {pk}={pv}",
                          data={"param_key": pk, "param_value": pv,
                                "target_node": target, "all_conditions": conditions})
