from agent.middleware.base import AgentMiddleware
from agent.context import AgentContext
from services.session_service import SessionService

class PendingConfirmMiddleware(AgentMiddleware):
    def __init__(self, ss: SessionService): self._ss = ss
    async def before_agent(self, ctx: AgentContext):
        p = await self._ss.get_pending_confirm(ctx.session_id)
        ctx.has_pending_confirm = p is not None; ctx.pending_confirm_options = p; return ctx
