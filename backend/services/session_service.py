import json, logging
from typing import Optional
import redis.asyncio as aioredis
logger = logging.getLogger(__name__)

class SessionService:
    def __init__(self, redis_url): self.redis = aioredis.from_url(redis_url, decode_responses=True)
    async def close(self): await self.redis.close()
    async def set_pending_confirm(self, sid, ancestors, ttl=300):
        await self.redis.setex(f"pending_confirm:{sid}", ttl, json.dumps(ancestors, ensure_ascii=False))
    async def get_pending_confirm(self, sid) -> Optional[list]:
        d = await self.redis.get(f"pending_confirm:{sid}"); return json.loads(d) if d else None
    async def delete_pending_confirm(self, sid):
        await self.redis.delete(f"pending_confirm:{sid}")
    async def set_skill_candidates(self, sid, data, ttl=300):
        await self.redis.setex(f"skill_candidates:{sid}", ttl, json.dumps(data, ensure_ascii=False))
    async def get_skill_candidates(self, sid):
        d = await self.redis.get(f"skill_candidates:{sid}")
        return json.loads(d) if d else None
    async def delete_skill_candidates(self, sid):
        await self.redis.delete(f"skill_candidates:{sid}")
