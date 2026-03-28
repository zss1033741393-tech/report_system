"""Memory API —— 查看/清除跨对话记忆。"""
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


def _storage():
    from main import app_state
    return app_state.get("memory_storage")


@router.get("/{session_id}")
async def get_memory(session_id: str):
    """获取指定会话的记忆 JSON。"""
    storage = _storage()
    if not storage:
        return {"memory": None, "error": "memory not initialized"}
    memory = storage.load(session_id)
    return {"session_id": session_id, "memory": memory}


@router.delete("/{session_id}")
async def clear_memory(session_id: str):
    """清除指定会话的记忆。"""
    storage = _storage()
    if not storage:
        return {"success": False, "error": "memory not initialized"}
    storage.clear(session_id)
    return {"success": True}
