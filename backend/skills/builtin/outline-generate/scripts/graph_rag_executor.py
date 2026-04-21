"""GraphRAG 大纲生成执行器——纯算法，不含 LLM 调用。

LLM 调用（锚点选择、条件裁剪）已上移至 tool_definitions._search_skill。
executor 只负责：FAISS 检索 → Neo4j 子树 → paragraph 合并 → 大纲渲染。
"""
import json
import logging
from typing import AsyncGenerator, Union

from agent.context import SkillContext, SkillResult
from pipeline.faiss_retriever import FAISSRetriever
from pipeline.neo4j_retriever import Neo4jRetriever
from pipeline.outline_renderer import OutlineRenderer
from services.embedding_service import EmbeddingService
from services.session_service import SessionService
from utils.trace_logger import TraceLogger

logger = logging.getLogger(__name__)


def _ts(step, status, detail, data=None):
    p = {"type": "thinking_step", "step": step, "status": status, "detail": detail}
    if data:
        p["data"] = data
    return json.dumps(p, ensure_ascii=False)


class GraphRAGExecutor:
    def __init__(self, embedding_service, faiss_retriever, neo4j_retriever,
                 outline_renderer, session_service, indicator_resolver=None,
                 top_k=10, score_threshold=0.5):
        self._emb = embedding_service
        self._faiss = faiss_retriever
        self._neo4j = neo4j_retriever
        self._render = outline_renderer
        self._session = session_service
        self._indicator_resolver = indicator_resolver
        self._top_k = top_k
        self._threshold = score_threshold

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        query = ctx.params.get("query", ctx.user_message)
        sid = ctx.session_id
        trace = TraceLogger(session_id=sid).child("skill.outline_generate")

        # Step 1: Embedding
        yield _ts("embedding", "running", "正在转换语义向量...")
        trace.start_timer("s1")
        qe = await self._emb.get_embedding(query)
        trace.log_timed("s1", "s1")
        yield _ts("embedding", "done", "语义向量完成")

        # Step 2: FAISS 检索
        yield _ts("knowledge_search", "running", "正在检索知识库...")
        trace.start_timer("s2")
        cands = self._faiss.search(qe, self._top_k, self._threshold)
        trace.log_timed("s2", "s2")
        if not cands:
            yield _ts("knowledge_search", "done", "未找到相关知识")
            yield SkillResult(False, f"未找到与「{query}」相关的知识")
            return
        yield _ts("knowledge_search", "done", f"找到 {len(cands)} 个节点",
                  data={"top_matches": [{"name": c.name, "score": f"{c.score:.2f}"} for c in cands[:5]]})

        # Step 3: Neo4j 祖先路径
        yield _ts("path_analysis", "running", "正在分析知识路径...")
        trace.start_timer("s3")
        nodes = await self._neo4j.get_ancestor_paths([c.neo4j_id for c in cands])
        trace.log_timed("s3", "s3")
        if not nodes:
            yield _ts("path_analysis", "done", "路径异常")
            yield SkillResult(False, "路径查询异常")
            return
        yield _ts("path_analysis", "done", f"{len(nodes)} 条路径")

        # Step 4: 从 params 接收 LLM 预计算的锚点（由 tool_definitions 提供）
        anchor = ctx.params.get("anchor")
        if not anchor:
            # 降级：取 FAISS 得分最高的节点
            anchor = {
                "selected_id": nodes[0]["id"],
                "selected_name": nodes[0]["name"],
                "selected_path": nodes[0].get("path", ""),
                "level": nodes[0]["level"],
                "reason": "fallback",
            }
        yield _ts("anchor_select", "done",
                  f'选择「{anchor["selected_name"]}」(L{anchor["level"]})',
                  data={"reason": anchor.get("reason", "")})

        # Step 5: L5 层级确认（叶子节点）
        if anchor["level"] == 5:
            yield _ts("level_check", "done", "叶子节点，需确认层级")
            ancs = await self._neo4j.get_ancestor_chain(anchor["selected_id"])
            await self._session.set_pending_confirm(sid, ancs, 300)
            trace.log("s5_l5_confirm", data={"ancestors": ancs})
            yield SkillResult(
                True,
                f"指标「{anchor['selected_name']}」需确认层级",
                need_user_input=True,
                data={
                    "type": "confirm_required",
                    "indicator_name": anchor["selected_name"],
                    "full_path": anchor["selected_path"],
                    "ancestors": ancs,
                },
                user_prompt=f'找到「{anchor["selected_name"]}」，请选择起始层级。',
            )
            return

        # Step 6: 子树遍历
        yield _ts("subtree_fetch", "running", "正在获取子树...")
        trace.start_timer("s6")
        subtree = await self._neo4j.get_subtree(anchor["selected_id"])
        trace.log_timed("s6", "s6")
        if not subtree:
            yield _ts("subtree_fetch", "done", "子树为空")
            yield SkillResult(False, "子树为空")
            return
        yield _ts("subtree_fetch", "done", "子树获取完成")

        # Step 6.5: 条件裁剪（从 params 接收 LLM 预计算的 remove_nodes 集合）
        remove_nodes = ctx.params.get("remove_nodes")
        if remove_nodes:
            yield _ts("condition_filter", "running", "正在根据条件裁剪大纲...")
            subtree = self._prune_tree(subtree, set(remove_nodes))
            remaining = self._count_children(subtree)
            yield _ts("condition_filter", "done", f"裁剪完成，保留 {remaining} 个节点")

        # Step 6.8: 合并 paragraph 到 L5 节点
        self.merge_paragraph(subtree, skill_dir="")

        # Step 7: 渲染大纲
        yield _ts("outline_render", "running", "正在生成大纲...")
        trace.start_timer("s7")
        chunks = []
        async for c in self._render.render_stream(subtree, anchor):
            chunks.append(c)
            yield json.dumps({"type": "outline_chunk", "content": c}, ensure_ascii=False)
        md = "".join(chunks)
        ai = {
            "id": anchor["selected_id"],
            "name": anchor["selected_name"],
            "level": anchor["level"],
        }
        yield json.dumps({"type": "outline_done", "anchor": ai}, ensure_ascii=False)
        trace.log_timed("s7", "s7", data={"chunks": len(chunks)})
        yield _ts("outline_render", "done", f"大纲完成，{len(chunks)} 章节")
        yield SkillResult(
            True,
            f"已生成「{anchor['selected_name']}」的大纲",
            data={"subtree": subtree, "anchor": ai, "outline_md": md},
        )

    async def execute_from_node(self, ctx: SkillContext, node_id: str) -> AsyncGenerator[Union[str, SkillResult], None]:
        ni = await self._neo4j.get_node_by_id(node_id)
        if not ni:
            yield SkillResult(False, "节点不存在")
            return
        yield _ts("subtree_fetch", "running", "获取子树...")
        subtree = await self._neo4j.get_subtree(node_id)
        if not subtree:
            yield _ts("subtree_fetch", "done", "空")
            yield SkillResult(False, "子树为空")
            return
        yield _ts("subtree_fetch", "done", "完成")
        self.merge_paragraph(subtree, skill_dir="")
        anchor = {"selected_id": ni["id"], "selected_name": ni["name"], "level": ni["level"]}
        yield _ts("outline_render", "running", "生成大纲...")
        chunks = []
        async for c in self._render.render_stream(subtree, anchor):
            chunks.append(c)
            yield json.dumps({"type": "outline_chunk", "content": c}, ensure_ascii=False)
        ai = {"id": ni["id"], "name": ni["name"], "level": ni["level"]}
        yield json.dumps({"type": "outline_done", "anchor": ai}, ensure_ascii=False)
        yield _ts("outline_render", "done", f"{len(chunks)} 章节")
        yield SkillResult(
            True,
            f"已生成「{ni['name']}」大纲",
            data={"subtree": subtree, "anchor": ai, "outline_md": "".join(chunks)},
        )

    @staticmethod
    def _collect_candidate_nodes(nodes: list) -> list:
        """从 Neo4j 路径中提取 L1~L4 候选锚点（供 tool 层 LLM 选锚使用）。"""
        return [
            {"id": n["id"], "name": n["name"], "level": n["level"], "path": n.get("path", "")}
            for n in nodes
        ]

    @staticmethod
    def _prune_tree(node: dict, remove_names: set) -> dict:
        if not node.get("children"):
            return node
        node["children"] = [
            GraphRAGExecutor._prune_tree(c, remove_names)
            for c in node["children"]
            if c.get("name") not in remove_names
        ]
        return node

    @staticmethod
    def _count_children(node: dict) -> int:
        count = 1
        for c in node.get("children", []):
            count += GraphRAGExecutor._count_children(c)
        return count

    def merge_paragraph(self, node: dict, skill_dir: str = "") -> None:
        if not self._indicator_resolver:
            return
        self.merge_paragraph_node(node, skill_dir)

    def merge_paragraph_node(self, node: dict, skill_dir: str) -> None:
        if node.get("level") == 5 and "paragraph" not in node:
            node["paragraph"] = self._indicator_resolver.resolve(
                node_id=node.get("id", ""),
                node_name=node.get("name", ""),
                skill_dir=skill_dir,
            )
        for child in node.get("children", []):
            self.merge_paragraph_node(child, skill_dir)

    @staticmethod
    def load_skill_outline(skill_dir: str):
        import os
        outline_path = os.path.join(skill_dir, "references", "outline.json")
        if not os.path.isfile(outline_path):
            return None
        try:
            with open(outline_path, "r", encoding="utf-8") as f:
                outline_json = json.load(f)
            if not outline_json or not outline_json.get("children"):
                return None
            md = GraphRAGExecutor._outline_json_to_md(outline_json)
            return outline_json, md
        except Exception as e:
            logger.warning(f"加载 Skill 大纲失败: {outline_path}, {e}")
            return None

    @staticmethod
    def _outline_json_to_md(node: dict, depth: int = 0, numbering: str = "") -> str:
        if not node:
            return ""
        md = ""
        name = node.get("name", "")
        level = node.get("level", 0)
        if level == 5:
            return ""
        if name:
            if depth == 0:
                md += f"# {name}\n\n"
            else:
                prefix = "#" * min(depth + 1, 6)
                num_str = f"{numbering} " if numbering else ""
                md += f"{prefix} {num_str}{name}\n\n"
        children = node.get("children", [])
        visible = [c for c in children if c.get("level", 0) != 5]
        for i, child in enumerate(visible, 1):
            child_num = f"{numbering}{i}" if numbering else str(i)
            md += GraphRAGExecutor._outline_json_to_md(child, depth + 1, f"{child_num}.")
        return md
