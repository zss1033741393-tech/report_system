"""审核服务 —— 管理 user_defined 节点的 draft → approved 流转，审核通过后写入 Neo4j。"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ReviewService:
    """处理大纲及节点的审核流程。"""

    def __init__(self, outline_store, neo4j_retriever):
        self._store = outline_store
        self._neo4j = neo4j_retriever

    async def approve_outline(self, outline_id: str, approved_by: str = "admin") -> dict:
        """审核通过一个大纲：将所有 draft 节点设为 approved，并写入 Neo4j。"""
        outline = await self._store.get_outline(outline_id)
        if not outline:
            return {"success": False, "message": f"大纲 {outline_id} 不存在"}

        # 获取所有待审核节点
        nodes = await self._store.get_nodes_by_outline(outline_id)
        draft_nodes = [n for n in nodes if n.get("status") == "draft"]

        neo4j_written = 0
        for node in draft_nodes:
            try:
                await self._write_node_to_neo4j(node, outline)
                await self._store.approve_node(node["id"])
                neo4j_written += 1
            except Exception as e:
                logger.error(f"ReviewService: Neo4j 写入失败 node={node['id']}: {e}", exc_info=True)

        # 更新大纲状态为 approved/active
        final_status = "active"
        await self._store.update_outline_status(outline_id, final_status, approved_by=approved_by)
        logger.info(
            f"ReviewService: 大纲 {outline_id} 审核通过，"
            f"写入 Neo4j {neo4j_written}/{len(draft_nodes)} 个节点"
        )
        return {
            "success": True,
            "outline_id": outline_id,
            "approved_nodes": neo4j_written,
            "total_draft": len(draft_nodes),
            "status": final_status,
        }

    async def reject_outline(self, outline_id: str, reason: str = "") -> dict:
        """拒绝一个大纲，状态设为 rejected。"""
        outline = await self._store.get_outline(outline_id)
        if not outline:
            return {"success": False, "message": f"大纲 {outline_id} 不存在"}

        await self._store.update_outline_status(outline_id, "rejected")
        logger.info(f"ReviewService: 大纲 {outline_id} 已拒绝，reason={reason!r}")
        return {"success": True, "outline_id": outline_id, "status": "rejected"}

    async def approve_node(self, node_id: str) -> dict:
        """单独审核通过一个节点并写入 Neo4j。"""
        nodes = await self._store._db.execute(
            "SELECT n.*, o.skill_name FROM outline_nodes n "
            "JOIN outlines o ON n.outline_id = o.id WHERE n.id=?",
            (node_id,),
        )
        row = await nodes.fetchone()
        if not row:
            return {"success": False, "message": f"节点 {node_id} 不存在"}

        node = dict(row)
        try:
            outline = await self._store.get_outline(node["outline_id"])
            await self._write_node_to_neo4j(node, outline or {})
        except Exception as e:
            logger.warning(f"ReviewService: 单节点 Neo4j 写入失败 {node_id}: {e}")

        await self._store.approve_node(node_id)
        return {"success": True, "node_id": node_id, "status": "approved"}

    async def _write_node_to_neo4j(self, node: dict, outline: dict) -> None:
        """将 user_defined 节点写入 Neo4j 知识图谱。"""
        if not self._neo4j:
            return
        skill_name = outline.get("skill_name", "")
        await self._neo4j.create_nodes_and_relations([{
            "id": node["id"],
            "name": node["name"],
            "level": node["level"],
            "source": "user_defined",
            "parent_id": node.get("parent_id", ""),
            "skill_name": skill_name,
        }])

    async def list_pending_outlines(self) -> list:
        """列出所有待审核大纲（status=pending_review）。"""
        c = await self._store._db.execute(
            "SELECT * FROM outlines WHERE status='pending_review' ORDER BY created_at DESC"
        )
        return [dict(r) for r in await c.fetchall()]

    async def list_pending_nodes(self) -> list:
        """列出所有待审核节点。"""
        return await self._store.get_pending_nodes()
