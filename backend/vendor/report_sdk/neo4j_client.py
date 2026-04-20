"""Neo4j 客户端封装——Skill 脚本通过此模块访问知识图谱。"""
from typing import Optional

_retriever = None


def init(neo4j_retriever):
    global _retriever
    _retriever = neo4j_retriever


def _check():
    if _retriever is None:
        raise RuntimeError("neo4j_client 未初始化，请先调用 init()")


async def get_subtree(node_id: str) -> Optional[dict]:
    _check()
    return await _retriever.get_subtree(node_id)


async def get_ancestor_paths(node_ids: list) -> list:
    _check()
    return await _retriever.get_ancestor_paths(node_ids)


async def get_ancestor_chain(node_id: str) -> list:
    _check()
    return await _retriever.get_ancestor_chain(node_id)


async def get_node_by_id(node_id: str) -> Optional[dict]:
    _check()
    return await _retriever.get_node_by_id(node_id)


async def create_nodes_and_relations(nodes: list):
    _check()
    return await _retriever.create_nodes_and_relations(nodes)


async def set_skill_path(node_id: str, skill_path: str):
    _check()
    return await _retriever.set_skill_path(node_id, skill_path)
