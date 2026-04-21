"""意图提取与双路径检索执行器——纯算法，不含 LLM 调用。

LLM 意图提取（intent JSON）已上移至 tool_definitions._extract_intent。
executor 只负责：接收预计算的 intent → FAISS 检索 → 纯算法路径判断 → 返回路径结果。
"""
import json
import logging
from typing import AsyncGenerator, Union

from agent.context import SkillContext, SkillResult

logger = logging.getLogger(__name__)


def _ts(step, status, detail, data=None):
    p = {"type": "thinking_step", "step": step, "status": status, "detail": detail}
    if data:
        p["data"] = data
    return json.dumps(p, ensure_ascii=False)


def _design(step, status):
    return json.dumps({"type": "design_step", "step": step, "status": status}, ensure_ascii=False)


class IntentExtractExecutor:
    """意图提取 + 双路径检索执行器（纯算法路径判断）。"""

    def __init__(self, embedding_service, faiss_retriever,
                 neo4j_retriever, session_service, kb_store,
                 top_k: int = 20, score_threshold: float = 0.3,
                 l14_confidence_threshold: float = 0.7):
        self._emb = embedding_service
        self._faiss = faiss_retriever
        self._neo4j = neo4j_retriever
        self._session = session_service
        self._kb = kb_store
        self._top_k = top_k
        self._threshold = score_threshold
        self._l14_threshold = l14_confidence_threshold

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        expert_input = ctx.params.get("expert_input", ctx.user_message)
        if not expert_input:
            yield SkillResult(False, "缺少 expert_input 参数")
            return

        # 从 params 接收 tool 层 LLM 预计算的 intent
        intent = ctx.params.get("intent")
        if not intent:
            yield SkillResult(False, "缺少预计算的 intent 参数（由 tool 层 LLM 生成）")
            return

        yield _design("intent_understand", "done")

        # ── Step 2：语义检索（纯算法）──
        yield _design("struct_extract", "running")
        query = (intent.get("scene_intro", "") + " " + " ".join(intent.get("keywords", []))).strip() or expert_input[:200]
        yield _ts("semantic_search", "running", "正在向量化检索知识库...")
        qe = await self._emb.get_embedding(query)
        cands = self._faiss.search(qe, self._top_k, self._threshold)
        yield _ts("semantic_search", "done", f"找到 {len(cands)} 个候选节点")

        if not cands:
            yield _design("struct_extract", "done")
            yield SkillResult(
                True,
                "检索无结果，走路径B（自底向上）",
                data={
                    "path": "no_match",
                    "intent": intent,
                    "bottom_up": {"indicators": [], "kb_contents": {}, "existing_l3l4": []},
                },
            )
            return

        # 获取祖先路径
        yield _ts("path_analysis", "running", "分析节点路径...")
        ancestor_paths = await self._neo4j.get_ancestor_paths([c.neo4j_id for c in cands])
        yield _ts("path_analysis", "done", f"{len(ancestor_paths)} 条路径")

        # ── Step 3：路径判断（纯算法）──
        score_map = {c.neo4j_id: c.score for c in cands}

        l14_hits = [
            n for n in ancestor_paths
            if n.get("level", 5) <= 4 and score_map.get(n["id"], 0) >= self._l14_threshold
        ]
        l5_hits = [n for n in ancestor_paths if n.get("level") == 5]

        yield _design("struct_extract", "done")

        if l14_hits:
            best = max(l14_hits, key=lambda x: score_map.get(x["id"], 0))
            yield _ts("path_decision", "done",
                      f"路径A（自顶向下）: 锚点「{best['name']}」(L{best['level']}) score={score_map.get(best['id'], 0):.2f}")
            yield _design("outline_design", "running")
            subtree = await self._neo4j.get_subtree(best["id"])
            yield _design("outline_design", "done")
            yield SkillResult(
                True,
                f"路径A: 命中「{best['name']}」",
                data={
                    "path": "top_down",
                    "intent": intent,
                    "top_down": {
                        "anchor": {"id": best["id"], "name": best["name"], "level": best["level"]},
                        "subtree": subtree,
                    },
                },
            )
        elif l5_hits:
            yield _ts("path_decision", "done",
                      f"路径B（自底向上）: 仅命中 {len(l5_hits)} 个 L5 指标节点")
            l5_sorted = sorted(l5_hits, key=lambda x: score_map.get(x["id"], 0), reverse=True)[:15]
            kb_contents = {}
            for node in l5_sorted:
                try:
                    content = await self._kb.get(node["id"])
                    if content:
                        kb_contents[node["id"]] = content
                except Exception as e:
                    logger.debug(f"KB 内容加载失败 {node['id']}: {e}")

            existing_l3l4 = [
                {"id": n["id"], "name": n["name"], "level": n["level"]}
                for n in ancestor_paths if n.get("level") in (3, 4)
            ]
            seen = set()
            existing_l3l4 = [x for x in existing_l3l4 if not (x["id"] in seen or seen.add(x["id"]))]

            yield SkillResult(
                True,
                f"路径B: {len(l5_sorted)} 个 L5 指标",
                data={
                    "path": "bottom_up",
                    "intent": intent,
                    "bottom_up": {
                        "indicators": [
                            {"id": n["id"], "name": n["name"], "level": n["level"],
                             "score": score_map.get(n["id"], 0)}
                            for n in l5_sorted
                        ],
                        "kb_contents": kb_contents,
                        "existing_l3l4": existing_l3l4,
                    },
                },
            )
        else:
            yield SkillResult(
                True,
                "未找到高置信度匹配，走路径B",
                data={
                    "path": "no_match",
                    "intent": intent,
                    "bottom_up": {"indicators": [], "kb_contents": {}, "existing_l3l4": []},
                },
            )
