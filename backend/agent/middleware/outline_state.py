from agent.middleware.base import AgentMiddleware
from agent.context import AgentContext
from services.chat_history import ChatHistoryService

class OutlineStateMiddleware(AgentMiddleware):
    def __init__(self, ch: ChatHistoryService): self._ch = ch
    async def before_agent(self, ctx: AgentContext):
        s = await self._ch.get_outline_state(ctx.session_id)
        if s and s.get("outline_json"):
            ctx.has_outline = True; ctx.current_outline = s["outline_json"]
            names = []; self._col(s["outline_json"], names, 0, 3)
            ctx.outline_summary = ", ".join(names[:30])
        else: ctx.has_outline = False; ctx.current_outline = None; ctx.outline_summary = ""
        return ctx
    def _col(self, n, names, d, md):
        if d > md: return
        nm = n.get("name","")
        if nm: names.append(nm)
        for c in n.get("children",[]): self._col(c, names, d+1, md)
