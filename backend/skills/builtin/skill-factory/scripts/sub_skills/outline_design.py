"""Sub-Step 3：生成可执行大纲 + 知识库后验校验。

LLM 输出节点 ID（而非名字），后处理用 ID 反查 name/level，确保精确匹配。
"""
import json, logging
from typing import AsyncGenerator
from llm.agent_llm import AgentLLM
from llm.config import SKILL_FACTORY_OUTLINE_CONFIG
from sub_skills.base import SubSkillBase
from context import SkillFactoryContext, sse_event
from sub_skills.struct_extract import _flatten_tree
from agent.context import SkillContext

logger = logging.getLogger(__name__)


class OutlineDesign(SubSkillBase):
    name = "outline_design"

    async def execute(self, fc: SkillFactoryContext, ctx: SkillContext) -> AsyncGenerator[str, None]:
        # 1. 基于 dimension_hints 精准获取子树
        if fc.dimension_hints:
            matched_names = [h.get("name", "") for h in fc.dimension_hints if h.get("name")]
            query = " ".join(matched_names) if matched_names else fc.raw_input[:100]
        else:
            query = (fc.scene_intro + " " + " ".join(fc.keywords)).strip() or fc.raw_input[:100]

        qe = await self._svc.embedding.get_embedding(query)
        cands = self._svc.faiss.search(qe, top_k=15, threshold=0.3)

        if not cands:
            fc.outline_json = {"name": fc.skill_name, "level": 2, "children": []}
            fc.outline_md = f"# {fc.skill_name}\n\n（知识库中未找到匹配节点）"
            return
            yield

        ancestor_paths = await self._svc.neo4j.get_ancestor_paths([c.neo4j_id for c in cands])

        # 精准过滤：基于 dimension_hints 匹配到的节点获取子树
        # 支持任意层级（L2/L3/L4/L5），每个匹配节点自身作为子树根
        hint_names = {h.get("name", "").strip(): h.get("level", 0) for h in fc.dimension_hints if h.get("name")}
        subtree_roots = set()
        if hint_names:
            for n in (ancestor_paths or []):
                if n["name"].strip() in hint_names:
                    subtree_roots.add(n["id"])
            # 如果精确匹配失败，按层级逐级 fallback：先找 L3，再找 L2
            if not subtree_roots:
                for lvl in (3, 2):
                    for n in (ancestor_paths or []):
                        if n["level"] == lvl:
                            subtree_roots.add(n["id"])
                    if subtree_roots:
                        break
        else:
            for n in (ancestor_paths or []):
                if n["level"] in (2, 3):
                    subtree_roots.add(n["id"])

        all_nodes = {}
        children_map: dict = {}  # parent_id → [{id, name, level}, ...]
        for root_id in subtree_roots:
            subtree = await self._svc.neo4j.get_subtree(root_id)
            if subtree:
                _flatten_tree(subtree, all_nodes)
                _build_children_map(subtree, children_map)
        if not all_nodes and ancestor_paths:
            for n in ancestor_paths:
                all_nodes[n["id"]] = n

        # 构建 ID→节点 映射表（供后处理使用）
        id_map = {n["id"]: n for n in all_nodes.values()}

        # 知识库清单格式：ID 在前，方便 LLM 输出时直接引用
        kb_node_list = "\n".join(
            f"{n['id']} | L{n['level']} | {n['name']}"
            for n in sorted(all_nodes.values(), key=lambda x: (x.get("level", 0), x.get("name", "")))
        )

        # 2. LLM 生成大纲——输出 ID 而非名字
        prompt = f"""你是报告大纲设计专家。基于用户看网逻辑和知识库节点组织大纲。

## 核心规则（必须遵守）
1. 大纲节点必须来自"知识库节点清单"，使用清单中的 ID 标识
2. 层级：L2→L3→L4→L5，不能跳过（L3下必须先放L4，L4下再放L5）
3. 只选与用户逻辑直接相关的节点，不堆砌
4. 每个 L3 下至少 1 个 L4，L4 下至少 1 个 L5

## 用户看网逻辑
{fc.raw_input}

## Step 2 匹配的核心维度（优先使用）
{json.dumps([h.get("name","") for h in fc.dimension_hints], ensure_ascii=False) if fc.dimension_hints else "无"}

## 知识库节点清单（格式：ID | 层级 | 名称）
{kb_node_list}

## 输出格式（用节点 ID 标识，不输出名字）
```json
{{"id":"L2节点ID","children":[{{"id":"L3节点ID","children":[{{"id":"L4节点ID","children":[{{"id":"L5节点ID","children":[]}}]}}]}}]}}
```

用 ```json ``` 代码块包裹输出。"""

        agent = AgentLLM(self._svc.llm, "", SKILL_FACTORY_OUTLINE_CONFIG,
                         trace_callback=ctx.trace_callback, llm_type="skill_factory", step_name="outline_design")
        try:
            raw_outline = await agent.chat_json(prompt)
        except Exception as e:
            logger.warning(f"Step 3 LLM 失败: {e}")
            raw_outline = {"id": "", "children": []}

        # 3. 后处理：用 ID 反查 name/level，构建完整的 outline_json
        phantom_ids = []
        fc.outline_json = _hydrate_outline(raw_outline, id_map, phantom_ids, fc.skill_name)

        # 后处理：LLM 有时只输出到 L4 而忘记 L5，自动从 KB 补全缺失的 L5 子节点
        _fill_missing_l5(fc.outline_json, children_map)

        if phantom_ids:
            logger.warning(f"Step 3 后验校验：移除无效 ID: {phantom_ids}")
            yield sse_event("kb_validation", {
                "removed": phantom_ids,
                "message": f"大纲中以下节点 ID 无效，已自动移除：{', '.join(phantom_ids)}"
            })

        fc.outline_md = outline_to_md(fc.outline_json)

        # SSE 推送大纲
        yield json.dumps({"type": "outline_chunk", "content": fc.outline_md}, ensure_ascii=False)
        yield json.dumps({"type": "outline_done", "anchor": {"name": fc.outline_json.get("name", fc.skill_name)}},
                         ensure_ascii=False)


def _hydrate_outline(raw: dict, id_map: dict, phantom: list, default_name: str = "") -> dict:
    """将 LLM 输出的 ID 树形结构反查为完整的 {id, name, level, children} 树。"""
    nid = raw.get("id", "")
    node_info = id_map.get(nid)

    if node_info:
        result = {"id": nid, "name": node_info["name"], "level": node_info["level"], "children": []}
    elif not nid:
        # 根节点可能没有 ID（LLM 自定义）
        result = {"name": raw.get("name", default_name), "level": raw.get("level", 2), "children": []}
    else:
        phantom.append(nid)
        return None

    for child_raw in raw.get("children", []):
        child = _hydrate_outline(child_raw, id_map, phantom)
        if child:
            result["children"].append(child)

    return result


def _build_children_map(node: dict, cmap: dict) -> None:
    """递归构建 parent_id → [child_info, ...] 映射，保留 KB 真实亲子关系。"""
    nid = node.get("id", "")
    if nid and nid not in cmap:
        cmap[nid] = [
            {"id": c.get("id", ""), "name": c.get("name", ""), "level": c.get("level", 0)}
            for c in node.get("children", [])
        ]
    for child in node.get("children", []):
        _build_children_map(child, cmap)


def _fill_missing_l5(node: dict, children_map: dict) -> None:
    """后处理：LLM 未为 L4 节点生成 L5 子节点时，从 KB 亲子关系自动补全。
    这处理 LLM 只输出到 L4 层就停止的情况（报告 sections 有标题但无数据）。
    """
    if not node:
        return
    if node.get("level") == 4 and not node.get("children"):
        nid = node.get("id", "")
        for child in children_map.get(nid, []):
            if child.get("level") == 5:
                node.setdefault("children", []).append({
                    "id": child["id"], "name": child["name"], "level": 5, "children": [],
                })
        if node.get("children"):
            logger.debug(f"auto-filled L5 for L4={node.get('name','')}: {[c['name'] for c in node['children']]}")
    for child in node.get("children", []):
        _fill_missing_l5(child, children_map)


def outline_to_md(outline: dict, depth: int = 0, numbering: str = "") -> str:
    """渲染大纲为 Markdown，带编号，跳过 L5。"""
    if not outline:
        return ""
    md = ""
    name = outline.get("name", "")
    level = outline.get("level", 0)
    if level == 5:
        return ""
    if name:
        if depth == 0:
            md += f"# {name}\n\n"
        else:
            prefix = "#" * min(depth + 1, 6)
            num_str = f"{numbering} " if numbering else ""
            md += f"{prefix} {num_str}{name}\n\n"
    children = outline.get("children", [])
    visible = [c for c in children if c.get("level", 0) != 5]
    for i, child in enumerate(visible, 1):
        child_num = f"{numbering}{i}" if numbering else str(i)
        md += outline_to_md(child, depth + 1, f"{child_num}.")
    return md
