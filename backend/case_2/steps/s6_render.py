"""S6: Markdown 渲染 —— 将嵌套树转换为 Markdown 大纲，无 LLM 调用。

输出格式：
  # L1 节点名
  ## L2 节点名
  ### L3 节点名
  #### L4 节点名
  - L5 节点名：描述
"""
import logging

logger = logging.getLogger(__name__)

# L5 节点用列表项而非标题
_HEADING_LEVELS = {1: "#", 2: "##", 3: "###", 4: "####"}


def _render_node(node: dict, lines: list[str]) -> None:
    level = node.get("level", 0)
    name = node.get("name", "")
    description = node.get("description", "")

    if level in _HEADING_LEVELS:
        prefix = _HEADING_LEVELS[level]
        lines.append(f"{prefix} {name}")
        if description and level >= 3:
            lines.append(f"> {description}")
        lines.append("")
    elif level == 5:
        short_desc = description[:40] + ("..." if len(description) > 40 else "")
        lines.append(f"- **{name}**：{short_desc}")
    else:
        lines.append(f"- {name}")

    for child in node.get("children", []):
        _render_node(child, lines)

    if level == 5 and node.get("children"):
        lines.append("")


def run(subtree: dict) -> str:
    """返回 Markdown 字符串。"""
    lines: list[str] = []
    _render_node(subtree, lines)

    # 去除末尾多余空行
    while lines and not lines[-1].strip():
        lines.pop()

    markdown = "\n".join(lines)
    logger.info(f"[S6-渲染] Markdown 输出 ({len(markdown)}ch):\n{markdown}")
    return markdown
