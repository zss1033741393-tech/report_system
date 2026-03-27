from abc import ABC
from agent.context import AgentContext

class AgentMiddleware(ABC):
    async def before_agent(self, ctx: AgentContext) -> AgentContext: return ctx
    async def after_skill(self, ctx, result): pass

class MiddlewareChain:
    def __init__(self, mws=None): self._mw = mws or []
    def add(self, mw): self._mw.append(mw)
    async def run_before(self, ctx):
        for m in self._mw: ctx = await m.before_agent(ctx)
        return ctx
