"""S2: 知识库检索 —— 纯文本关键词打分，无 LLM 调用。

输入：意图解析结果（topics）
输出：候选节点列表 [(node_id, score, node_dict), ...]
"""
import logging

logger = logging.getLogger(__name__)

TOP_K = 10  # 最多取前 K 个候选节点


def run(intent: dict, kb) -> list[tuple[str, int, dict]]:
    """
    kb: KBStore 实例
    返回 [(node_id, score, node), ...] 按 score 降序
    """
    topics: list[str] = intent.get("topics", [])
    if not topics:
        logger.warning("[S2-知识库检索] topics 为空，跳过检索")
        return []

    logger.info(f"[S2-知识库检索] 检索 topics: {topics}")

    scored = kb.search_by_keywords(topics)
    results = []
    for nid, score in scored[:TOP_K]:
        node = kb.get_node(nid)
        if node:
            results.append((nid, score, node))

    if results:
        logger.info(f"[S2-知识库检索] 命中 {len(results)} 个候选节点:")
        for nid, score, node in results:
            logger.info(f"  [{score:2d}] {nid} {node['name']}")
    else:
        logger.info("[S2-知识库检索] 未命中任何节点")

    return results
