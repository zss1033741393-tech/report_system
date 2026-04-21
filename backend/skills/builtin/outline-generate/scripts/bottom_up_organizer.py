"""路径 B：自底向上大纲组织器——纯算法，不含 LLM 调用。

LLM 大纲组织（raw_outline JSON）已上移至 tool_definitions._extract_intent。
executor 只负责：接收预生成的 raw_outline → _hydrate_l5 补全 → paragraph 合并 → Markdown 渲染。
"""
import json
import logging
from typing import AsyncGenerator, Union

from agent.context import SkillContext, SkillResult

logger = logging.getLogger(__name__)


def _ts(step, status, detail):
    return json.dumps({"type": "thinking_step", "step": step, "status": status, "detail": detail},
                      ensure_ascii=False)


def _design(step, status):
    return json.dumps({"type": "design_step", "step": step, "status": status}, ensure_ascii=False)


class BottomUpOrganizer:
    """路径 B 自底向上大纲组织器（纯算法后处理）。"""

    def __init__(self, indicator_resolver=None):
        self._indicator_resolver = indicator_resolver

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        intent = ctx.params.get("intent", {})
        bottom_up = ctx.params.get("bottom_up", {})

        indicators = bottom_up.get("indicators", [])
        if not indicators:
            yield SkillResult(False, "路径B：没有可用的 L5 指标节点")
            return

        raw_outline = ctx.params.get("raw_outline")
        if not raw_outline:
            yield SkillResult(False, "缺少预生成的 raw_outline 参数（由 tool 层 LLM 生成）")
            return

        yield _design("outline_design", "running")
        yield _ts("bottom_up_outline", "running", "正在后处理自底向上大纲...")

        indicator_map = {n["id"]: n for n in indicators}
        _hydrate_l5(raw_outline, indicator_map)

        if self._indicator_resolver:
            _merge_paragraph(raw_outline, self._indicator_resolver)

        yield _design("outline_design", "done")

        skill_name = intent.get("skill_name", "unnamed_skill")
        outline_md = _outline_to_md(raw_outline)

        yield json.dumps({"type": "outline_chunk", "content": outline_md}, ensure_ascii=False)
        yield json.dumps({"type": "outline_done",
                          "anchor": {"name": raw_outline.get("name", skill_name)}},
                         ensure_ascii=False)
        yield _ts("bottom_up_outline", "done", "自底向上大纲后处理完成")

        yield SkillResult(
            True,
            "路径B大纲生成完成",
            data={
                "subtree": raw_outline,
                "anchor": {"id": "", "name": raw_outline.get("name", skill_name), "level": 2},
                "outline_md": outline_md,
                "path": "bottom_up",
            },
        )

    @staticmethod
    def build_llm_prompt(intent: dict, bottom_up: dict, raw_input: str) -> tuple:
        """供 tool 层调用，返回 (system_prompt, user_message)，用于 LLM 生成 raw_outline。"""
        system_prompt = """你是报告大纲设计专家。用户输入了一段看网逻辑，你需要基于匹配到的评估指标（L5）自底向上组织一份分析大纲。

## 输出规则
1. L5 节点必须使用提供列表中的 node_id，不得新编（source: "kb"）
2. L2~L4 层可以使用可复用已有节点中的 ID（source: "kb"），也可以自由创建新节点（source: "user_defined"）
3. 已有节点格式: {"id": "xxx", "name": "xxx", "level": N, "source": "kb", "children": [...]}
4. 新建节点格式: {"name": "xxx", "level": N, "source": "user_defined", "children": [...]}
5. 层级顺序：L2 → L3 → L4 → L5，不可跳层
6. 每个 L3 下至少 1 个 L4，L4 下至少 1 个 L5
7. 根据用户看网逻辑意图组织层级，不要机械堆砌所有指标
8. 每个 L5 节点的 expand_logic 已提供，可用于理解指标含义、组织上层结构

用  代码块包裹输出，格式为完整大纲树（根节点为 L2）：
{"name":"根节点名","level":2,"source":"kb"|"user_defined","children":[...]}"""

        indicators = bottom_up.get("indicators", [])
        kb_contents = bottom_up.get("kb_contents", {})
        existing_l3l4 = bottom_up.get("existing_l3l4", [])

        indicator_lines = []
        for node in indicators[:15]:
            nid = node["id"]
            name = node["name"]
            kb = kb_contents.get(nid, {})
            expand_logic = kb.get("expand_logic", "") or kb.get("content", "")
            if expand_logic:
                line = f"- {name} (ID: {nid})\n  分析逻辑：{expand_logic[:100]}"
            else:
                line = f"- {name} (ID: {nid})"
            indicator_lines.append(line)

        existing_lines = [f"- {n['name']} (L{n['level']}, ID: {n['id']})" for n in existing_l3l4[:20]]

        user_msg = f"""## 用户看网逻辑
{raw_input}

## 场景简介
{intent.get("scene_intro", "")}

## 匹配到的评估指标（L5，ID 不可改变）
{chr(10).join(indicator_lines)}

## 可复用的已有节点（优先使用，避免重复创建）
{chr(10).join(existing_lines) if existing_lines else "（暂无可复用节点）"}

请基于以上信息，组织一份结构合理的大纲树。"""

        return system_prompt, user_msg


def _hydrate_l5(node: dict, indicator_map: dict) -> None:
    if not node:
        return
    nid = node.get("id", "")
    if nid and nid in indicator_map:
        ind = indicator_map[nid]
        node.setdefault("name", ind["name"])
        node.setdefault("level", 5)
        node.setdefault("source", "kb")
    for child in node.get("children", []):
        _hydrate_l5(child, indicator_map)


def _merge_paragraph(node: dict, resolver) -> None:
    if node.get("level") == 5 and "paragraph" not in node:
        node["paragraph"] = resolver.resolve(
            node_id=node.get("id", ""),
            node_name=node.get("name", ""),
            skill_dir="",
        )
    for child in node.get("children", []):
        _merge_paragraph(child, resolver)


def _outline_to_md(outline: dict, depth: int = 0, numbering: str = "") -> str:
    if not outline:
        return ""
    level = outline.get("level", 0)
    name = outline.get("name", "")
    if level == 5:
        return ""
    md = ""
    if name:
        if depth == 0:
            md += f"# {name}\n\n"
        else:
            prefix = "#" * min(depth + 1, 6)
            num_str = f"{numbering} " if numbering else ""
            md += f"{prefix} {num_str}{name}\n\n"
    visible = [c for c in outline.get("children", []) if c.get("level", 0) != 5]
    for i, child in enumerate(visible, 1):
        child_num = f"{numbering}{i}" if numbering else str(i)
        md += _outline_to_md(child, depth + 1, f"{child_num}.")
    return md
