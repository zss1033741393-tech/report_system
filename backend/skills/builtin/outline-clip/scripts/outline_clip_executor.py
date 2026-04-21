"""大纲动态裁剪执行器——纯算法，不含 LLM 调用。

LLM 裁剪指令解析已上移至 tool_definitions._clip_outline。
executor 只负责：接收结构化操作列表 → 纯算法执行裁剪 → 返回更新后的大纲。
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


class OutlineClipExecutor:

    def __init__(self):
        pass

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        outline = ctx.current_outline
        if not outline:
            yield SkillResult(False, "当前没有大纲，请先生成大纲")
            return

        # 接收 tool 层 LLM 预计算的结构化操作列表
        clip_instructions = ctx.params.get("clip_instructions")
        if not clip_instructions:
            # 降级：尝试从自然语言 instruction 参数生成最简单的操作（无 LLM）
            instruction = ctx.params.get("instructions", ctx.user_message)
            yield SkillResult(False, f"缺少 clip_instructions 参数，无法执行裁剪（instruction={instruction!r}）")
            return

        yield _ts("outline_clip", "running", f"正在执行 {len(clip_instructions)} 条裁剪操作...")

        deleted_nodes = []
        modified_params = []
        for inst in clip_instructions:
            t = inst.get("type")
            if t == "delete_node":
                target = inst.get("target_name", "")
                if target:
                    outline = self._delete_node(outline, target)
                    deleted_nodes.append(target)
            elif t == "filter_param":
                target = inst.get("target_name", "")
                pk = inst.get("param_key", "")
                pv = inst.get("param_value", "")
                if target and pk:
                    modified_params.append({"node": target, pk: pv})
            elif t == "keep_only":
                targets = inst.get("target_names", [])
                if targets:
                    outline = self._keep_only(outline, set(targets))

        yield _ts("outline_clip", "done",
                  f"裁剪完成: 删除{len(deleted_nodes)}个节点, 修改{len(modified_params)}个参数")

        yield json.dumps({"type": "outline_clipped",
                          "deleted_nodes": deleted_nodes,
                          "modified_params": modified_params}, ensure_ascii=False)
        yield json.dumps({"type": "outline_updated", "outline_json": outline}, ensure_ascii=False)

        yield SkillResult(
            True,
            "大纲裁剪完成",
            data={
                "updated_outline": outline,
                "deleted_nodes": deleted_nodes,
                "modified_params": modified_params,
            },
        )

    @staticmethod
    def collect_nodes_text(node, depth=0):
        """供 tool 层收集节点文本，用于构造 LLM prompt。"""
        lines = []
        name = node.get("name", "")
        level = node.get("level", 0)
        if name:
            lines.append(f"{'  ' * depth}- {name} (L{level})")
        for child in node.get("children", []):
            lines.append(OutlineClipExecutor.collect_nodes_text(child, depth + 1))
        return "\n".join(lines)

    @staticmethod
    def _delete_node(node, target_name):
        if not node.get("children"):
            return node
        node["children"] = [
            OutlineClipExecutor._delete_node(c, target_name)
            for c in node["children"]
            if c.get("name") != target_name
        ]
        return node

    @staticmethod
    def _keep_only(node, target_names):
        if not node.get("children"):
            return node
        node["children"] = [
            OutlineClipExecutor._keep_only(c, target_names)
            for c in node["children"]
            if c.get("name") in target_names or OutlineClipExecutor._has_descendant(c, target_names)
        ]
        return node

    @staticmethod
    def _has_descendant(node, names):
        if node.get("name") in names:
            return True
        return any(OutlineClipExecutor._has_descendant(c, names) for c in node.get("children", []))
