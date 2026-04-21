"""case_2 单轮工作流：用户输入 → 分析框架大纲（Markdown）。

6 个步骤：
  S1 意图解析（LLM）  → intent
  S2 知识库检索（文本）→ candidates
  S3 锚点选择（LLM）  → anchors
  S4 子树构建（内存）  → subtree
  S5 大纲裁剪（LLM）  → filtered_subtree
  S6 Markdown 渲染    → markdown

LLM 接入：通过 llm_fn 参数注入，签名 async (prompt: str) -> str
可接入任何 OpenAI-compatible API。
"""
import logging

from case_2.kb_store import KBStore
from case_2.steps import s1_intent, s2_search, s3_anchor, s4_subtree, s5_filter, s6_render

logger = logging.getLogger(__name__)

_kb: KBStore | None = None


def _get_kb() -> KBStore:
    global _kb
    if _kb is None:
        _kb = KBStore.load()
        logger.info(f"[workflow] KBStore 已加载：{len(_kb.nodes)} 个节点")
    return _kb


async def run(query: str, llm_fn) -> dict:
    """
    执行完整工作流。

    Args:
        query: 用户输入的自然语言问题
        llm_fn: async callable(prompt: str) -> str

    Returns:
        {
            "query": str,
            "intent": dict,
            "candidates": [(id, score, node), ...],
            "anchors": [dict, ...],
            "subtree": dict,
            "markdown": str,
        }
    """
    kb = _get_kb()

    logger.info(f"\n{'='*60}")
    logger.info(f"[workflow] 开始处理问题: {query!r}")
    logger.info(f"{'='*60}")

    # S1 意图解析
    logger.info("\n── S1 意图解析 ──")
    intent = await s1_intent.run(query, llm_fn)

    # S2 知识库检索
    logger.info("\n── S2 知识库检索 ──")
    candidates = s2_search.run(intent, kb)

    # S3 锚点选择
    logger.info("\n── S3 锚点选择 ──")
    anchors = await s3_anchor.run(query, intent, candidates, llm_fn)

    # S4 子树构建
    logger.info("\n── S4 子树构建 ──")
    subtree = s4_subtree.run(anchors, kb)

    if subtree is None:
        logger.warning("[workflow] 子树为空，无法生成大纲")
        return {
            "query": query,
            "intent": intent,
            "candidates": candidates,
            "anchors": anchors,
            "subtree": None,
            "markdown": "（未能匹配到相关知识节点，请换一种提问方式）",
        }

    # S5 大纲裁剪
    logger.info("\n── S5 大纲裁剪 ──")
    filtered = await s5_filter.run(query, subtree, llm_fn)

    # S6 Markdown 渲染
    logger.info("\n── S6 Markdown 渲染 ──")
    markdown = s6_render.run(filtered)

    logger.info(f"\n{'='*60}")
    logger.info(f"[workflow] 流程完成")
    logger.info(f"{'='*60}")

    return {
        "query": query,
        "intent": intent,
        "candidates": candidates,
        "anchors": anchors,
        "subtree": subtree,
        "markdown": markdown,
    }
