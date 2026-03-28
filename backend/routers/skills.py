"""Skills API —— 查询已注册的看网技能列表。"""
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


def _registry():
    from main import app_state
    return app_state.get("skill_registry")


@router.get("")
async def list_skills():
    """列出所有已注册的看网技能。"""
    registry = _registry()
    if not registry:
        return {"skills": [], "error": "skill registry not initialized"}
    skills = []
    for meta in registry.get_all():
        executor_info = None
        if meta.executor:
            executor_info = {"module": meta.executor.module, "cls": meta.executor.cls}
        skills.append({
            "name": meta.name,
            "display_name": meta.display_name,
            "description": meta.description,
            "enabled": meta.enabled,
            "source": meta.source,
            "executor": executor_info,
        })
    return {"skills": skills}


@router.get("/{skill_name}")
async def get_skill(skill_name: str):
    """获取指定技能的详细信息。"""
    registry = _registry()
    if not registry:
        return {"skill": None, "error": "skill registry not initialized"}
    meta = registry.get(skill_name)
    if not meta:
        return {"skill": None, "error": f"技能不存在: {skill_name}"}
    executor_info = None
    if meta.executor:
        executor_info = {
            "module": meta.executor.module,
            "cls": meta.executor.cls,
            "deps": meta.executor.deps,
            "config": meta.executor.config,
        }
    return {"skill": {
        "name": meta.name,
        "display_name": meta.display_name,
        "description": meta.description,
        "enabled": meta.enabled,
        "source": meta.source,
        "params": meta.params,
        "executor": executor_info,
        "skill_md_path": meta.skill_md_path,
    }}
