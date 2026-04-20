"""大纲沉淀执行器——将设计态产物写入 DB 三张表。

替代原 SkillPersist（写文件系统），改为写 outlines/outline_nodes/node_bindings 表。
user_defined 节点写为 draft 状态，审核通过后才写入 Neo4j。
"""
import json
import logging
from typing import AsyncGenerator, Union

from agent.context import SkillContext, SkillResult

logger = logging.getLogger(__name__)


def _sse(event_type: str, data: dict) -> str:
    return json.dumps({"type": event_type, **data}, ensure_ascii=False)


def _design(step: str, status: str) -> str:
    return json.dumps({"type": "design_step", "step": step, "status": status}, ensure_ascii=False)


class OutlinePersistExecutor:
    """大纲沉淀执行器。"""

    def __init__(self, outline_store, session_service, neo4j_retriever,
                 faiss_retriever, embedding_service):
        self._store = outline_store
        self._session = session_service
        self._neo4j = neo4j_retriever
        self._faiss = faiss_retriever
        self._emb = embedding_service

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        context_key = ctx.params.get("context_key", ctx.session_id)

        # 从 Redis 恢复 intent-extract 缓存的上下文
        cached = await self._session.redis.get(f"skill_factory_ctx:{context_key}")
        if not cached:
            yield SkillResult(False, "缓存已过期，请重新执行设计态流程")
            return

        fc = json.loads(cached)
        outline_json = fc.get("outline_json")
        if not outline_json:
            yield SkillResult(False, "缓存中无大纲数据")
            return

        intent = fc.get("intent", {})
        skill_name = intent.get("skill_name", fc.get("skill_name", "unnamed_skill"))
        scene_intro = intent.get("scene_intro", fc.get("scene_intro", ""))
        keywords = intent.get("keywords", fc.get("keywords", []))
        query_variants = intent.get("query_variants", fc.get("query_variants", []))
        raw_input = fc.get("raw_input", "")

        yield _design("skill_persist", "running")

        # ── Step 1：写 outlines 表 ──
        outline_id = await self._store.create_outline(
            skill_name=skill_name,
            display_name=scene_intro or skill_name,
            raw_input=raw_input,
            scene_intro=scene_intro,
            keywords=keywords,
            query_variants=query_variants,
        )
        logger.info(f"OutlinePersist: outlines 记录已创建 id={outline_id} skill={skill_name}")

        # ── Step 2：写 outline_nodes 表（递归写整棵树）──
        await self._store.bulk_create_nodes_from_outline_tree(outline_id, outline_json)
        logger.info(f"OutlinePersist: outline_nodes 写入完成 outline_id={outline_id}")

        # ── Step 3：写 node_bindings 表（L5 节点数据绑定）──
        await self._store.bulk_upsert_bindings_from_outline(outline_json)

        # 统计 user_defined 节点数量（需要审核）
        user_defined_count = _count_user_defined(outline_json)
        logger.info(f"OutlinePersist: node_bindings 写入完成，user_defined 节点数={user_defined_count}")

        # ── Step 4：更新 FAISS 索引（供 skill-router 语义检索）──
        try:
            search_text = (scene_intro + " " + " ".join(keywords)).strip() or skill_name
            embedding = await self._emb.get_embedding(search_text)
            self._faiss.add_batch([outline_id], [embedding])
            logger.info(f"OutlinePersist: FAISS 索引已更新 outline_id={outline_id}")
        except Exception as e:
            logger.warning(f"OutlinePersist: FAISS 索引更新失败（可忽略）: {e}")

        # ── 激活大纲 ──
        # 若无 user_defined 节点，直接设为 active；否则设为 pending_review
        final_status = "pending_review" if user_defined_count > 0 else "active"
        await self._store.update_outline_status(outline_id, final_status)

        yield _sse("skill_persisted", {
            "outline_id": outline_id,
            "skill_name": skill_name,
            "status": final_status,
            "user_defined_count": user_defined_count,
            "message": (
                f"大纲「{skill_name}」已保存（id={outline_id}）。"
                + (f"其中 {user_defined_count} 个新节点待审核后生效。" if user_defined_count > 0 else "")
            ),
        })

        yield _design("skill_persist", "done")

        yield SkillResult(
            True,
            f"大纲「{skill_name}」已沉淀（{final_status}）",
            data={
                "outline_id": outline_id,
                "skill_name": skill_name,
                "status": final_status,
                "user_defined_count": user_defined_count,
            },
        )


def _count_user_defined(node: dict) -> int:
    """统计大纲树中 user_defined 节点数量。"""
    count = 1 if node.get("source") == "user_defined" else 0
    for child in node.get("children", []):
        count += _count_user_defined(child)
    return count
