"""Skills 管理 API。"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


def _registry():
    from main import app_state
    return app_state.get("skill_registry")


class SkillToggle(BaseModel):
    enabled: bool


@router.get("")
async def list_skills(reg=None):
    try:
        from main import app_state
        reg = app_state.get("skill_registry")
        if not reg:
            return {"skills": []}
        skills = []
        for s in reg.get_all():
            skills.append({
                "name": s.name,
                "display_name": s.display_name,
                "description": s.description,
                "enabled": s.enabled,
                "source": s.source,
                "skill_dir": s.skill_dir,
            })
        return {"skills": skills}
    except Exception as e:
        raise HTTPException(500, f"获取技能列表失败: {e}")


@router.patch("/{name}")
async def toggle_skill(name: str, body: SkillToggle):
    try:
        from main import app_state
        reg = app_state.get("skill_registry")
        if not reg:
            raise HTTPException(404, "SkillRegistry 未初始化")
        meta = reg.get(name)
        if not meta:
            raise HTTPException(404, f"技能 '{name}' 不存在")
        meta.enabled = body.enabled
        return {"name": name, "enabled": meta.enabled}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"更新技能状态失败: {e}")
