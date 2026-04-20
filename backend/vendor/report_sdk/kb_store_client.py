"""KBContentStore 客户端封装。"""
from typing import Optional

_store = None


def init(kb_store):
    global _store
    _store = kb_store


def _check():
    if _store is None:
        raise RuntimeError("kb_store_client 未初始化，请先调用 init()")


async def get(node_id: str) -> Optional[dict]:
    _check()
    return await _store.get(node_id)


async def get_batch(node_ids: list) -> dict:
    _check()
    results = {}
    for nid in node_ids:
        item = await _store.get(nid)
        if item:
            results[nid] = item
    return results


async def set(node_id: str, content: dict):
    _check()
    return await _store.set(node_id, content)
