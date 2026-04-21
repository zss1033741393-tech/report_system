"""S4: 子树构建 —— 从锚点出发，在内存邻接表上向上找根、向下展开子树。

对于每个锚点：
  1. 向上 BFS 找到 L1 根节点（取路径上最浅层的祖先）
  2. 从该根节点向下构建完整嵌套树
  3. 合并多个锚点产生的子树（共享节点只展开一次）

最终返回一棵完整的嵌套树，与 GraphRAG 流程的 subtree 格式相同。
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _find_l1_root(anchor_id: str, kb) -> Optional[str]:
    """从锚点向上找 L1 节点。若锚点自身即 L1，直接返回。"""
    node = kb.get_node(anchor_id)
    if node and node.get("level") == 1:
        return anchor_id

    # BFS 向上
    queue = [anchor_id]
    visited = {anchor_id}
    while queue:
        nid = queue.pop(0)
        for pid in kb.get_parent_ids(nid):
            if pid in visited:
                continue
            visited.add(pid)
            pnode = kb.get_node(pid)
            if pnode and pnode.get("level") == 1:
                return pid
            queue.append(pid)
    return None


def run(anchors: list[dict], kb) -> Optional[dict]:
    """
    anchors: [{"id": ..., "name": ..., "reason": ...}, ...]
    返回合并后的嵌套树 dict，或 None（无有效锚点时）
    """
    if not anchors:
        logger.warning("[S4-子树构建] 无锚点，跳过")
        return None

    # 找到所有锚点对应的 L1 根
    root_ids = set()
    for a in anchors:
        rid = _find_l1_root(a["id"], kb)
        if rid:
            root_ids.add(rid)
            logger.info(f"[S4-子树构建] 锚点 {a['id']} {a['name']} → 根节点 {rid}")
        else:
            logger.warning(f"[S4-子树构建] 锚点 {a['id']} 未找到 L1 根，作为局部根使用")
            root_ids.add(a["id"])

    if len(root_ids) == 1:
        root_id = next(iter(root_ids))
        subtree = kb.build_subtree(root_id)
        node_count = _count(subtree)
        logger.info(f"[S4-子树构建] 从根 {root_id} 构建子树，共 {node_count} 个节点")
        return subtree

    # 多个根：取 L1 最浅的（通常唯一），否则取第一个
    # 若全都是 L1，找共同祖先（理论上只有一个 L1）
    l1_roots = [rid for rid in root_ids if kb.get_node(rid) and kb.get_node(rid).get("level") == 1]
    if l1_roots:
        root_id = l1_roots[0]
    else:
        root_id = next(iter(root_ids))

    subtree = kb.build_subtree(root_id)
    node_count = _count(subtree)
    logger.info(f"[S4-子树构建] 多根合并，选用根 {root_id}，共 {node_count} 个节点")
    return subtree


def _count(node: dict) -> int:
    return 1 + sum(_count(c) for c in node.get("children", []))
