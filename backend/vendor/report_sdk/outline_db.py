"""OutlineStore 客户端封装——Skill 脚本通过此模块读写大纲三张表。"""
from typing import Optional

_store = None


def init(outline_store):
    global _store
    _store = outline_store


def _check():
    if _store is None:
        raise RuntimeError("outline_db 未初始化，请先调用 init()")


async def create_outline(skill_name: str, display_name: str, raw_input: str = "",
                          scene_intro: str = "", keywords: list = None,
                          query_variants: list = None) -> str:
    _check()
    return await _store.create_outline(
        skill_name=skill_name, display_name=display_name,
        raw_input=raw_input, scene_intro=scene_intro,
        keywords=keywords, query_variants=query_variants,
    )


async def get_outline(outline_id: str) -> Optional[dict]:
    _check()
    return await _store.get_outline(outline_id)


async def list_outlines(status: str = None, limit: int = 50) -> list:
    _check()
    return await _store.list_outlines(status=status, limit=limit)


async def bulk_create_nodes(outline_id: str, outline_json: dict) -> str:
    _check()
    return await _store.bulk_create_nodes_from_outline_tree(outline_id, outline_json)


async def bulk_upsert_bindings(outline_json: dict):
    _check()
    return await _store.bulk_upsert_bindings_from_outline(outline_json)


async def get_binding(node_id: str) -> Optional[dict]:
    _check()
    return await _store.get_binding(node_id)


async def list_active_outlines() -> list:
    _check()
    return await _store.list_active_outlines_for_router()
