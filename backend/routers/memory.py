"""Memory API 路由。

GET  /api/v1/memory        → 读取当前 memory 数据
DELETE /api/v1/memory      → 清空 memory 数据
"""

import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


def _agent():
    from main import app_state
    return app_state["lead_agent"]


@router.get("")
async def get_memory(agent=__import__('fastapi').Depends(_agent)):
    """返回当前 memory 数据（供前端 MemoryPanel 展示）。"""
    storage = getattr(agent, "_memory_storage", None)
    if not storage:
        return {"version": "1.0", "user": {}, "history": {}, "facts": []}
    return storage.load()


@router.delete("")
async def clear_memory(agent=__import__('fastapi').Depends(_agent)):
    """清空所有 memory 数据。"""
    storage = getattr(agent, "_memory_storage", None)
    if storage:
        storage.clear()
    return {"success": True, "message": "Memory 已清空"}
