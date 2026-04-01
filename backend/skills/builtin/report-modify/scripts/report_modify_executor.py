"""报告局部修改执行器。

提供两个入口：
  modify_data(outline, data_results, node_ids, params)
    → 对目标节点重新执行数据查询，返回局部 HTML 片段 + 更新后的 data_results
  modify_text(outline, report_html, node_id, instruction, llm_service)
    → 对目标节点的 narrative 文字用 LLM 改写，返回局部 HTML 片段
"""
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# ─── HTML patch 工具 ───


def extract_node_html(report_html: str, node_id: str) -> str:
    """从报告 HTML 中提取 data-node-id 对应的 DOM 片段（浅层，不含嵌套子节点）。"""
    pattern = rf'(<div[^>]*\bdata-node-id="{re.escape(node_id)}"[^>]*>)(.*?)(</div>)'
    m = re.search(pattern, report_html, re.DOTALL)
    if m:
        return m.group(0)
    return ""


def patch_node_html(report_html: str, node_id: str, new_html: str) -> str:
    """将 report_html 中 data-node-id=node_id 的 div 替换为 new_html。"""
    pattern = rf'(<div[^>]*\bdata-node-id="{re.escape(node_id)}"[^>]*>)(.*?)(</div>)'

    def replacer(m):
        return new_html

    patched, n = re.subn(pattern, replacer, report_html, count=1, flags=re.DOTALL)
    if n == 0:
        logger.warning(f"patch_node_html: 未找到 data-node-id={node_id}")
        return report_html
    return patched


def extract_narrative_text(node_html: str) -> str:
    """从节点 HTML 片段中提取 .narrative 段落的纯文本。"""
    m = re.search(r'<p\s+class="narrative">(.*?)</p>', node_html, re.DOTALL)
    if m:
        # 去除 HTML 标签
        text = re.sub(r'<[^>]+>', '', m.group(1))
        return text.strip()
    return ""


def build_indicator_html(name: str, node_id: str, narrative: str, data: dict) -> str:
    """重新渲染单个 L5 指标的 HTML 片段。"""
    narrative_html = f'<p class="narrative">{narrative}</p>' if narrative else ''
    data_html = _render_data(data)
    return (
        f'<div class="data-section" data-node-id="{node_id}">'
        f'<h4>{name}</h4>'
        f'{narrative_html}'
        f'{data_html}'
        f'</div>'
    )


def _render_data(data: Optional[dict]) -> str:
    """将数据字典渲染为 HTML 片段。"""
    if not data:
        return '<p style="color:#c0c4cc">暂无数据</p>'

    dt = data.get("data_type", "")
    if dt == "SINGLE_VALUE":
        dv = data.get("data", {})
        return (
            f'<span class="single-value">{dv.get("value", "")}</span>'
            f'<span class="single-unit">{dv.get("unit", "")}</span>'
        )
    elif dt == "TABLE":
        cols = data.get("columns", [])
        rows = data.get("data", [])
        if not cols and rows:
            cols = list(rows[0].keys())
        header = "".join(f"<th>{c}</th>" for c in cols)
        body = ""
        for row in rows:
            cells = "".join(f"<td>{row.get(c, '')}</td>" for c in cols)
            body += f"<tr>{cells}</tr>"
        return f"<table><tr>{header}</tr>{body}</table>"
    elif dt in ("PIE_CHART", "BAR_CHART", "LINE_CHART", "HEATMAP"):
        return f'<div class="chart-placeholder">[{dt} 图表: {data.get("title", "")}]</div>'
    return '<p style="color:#c0c4cc">暂无数据</p>'


# ─── 数据层修改 ───


async def modify_data(
    outline: dict,
    report_html: str,
    target_node_ids: list,
    updated_params: dict,
    data_service,
) -> dict:
    """对目标节点重新执行数据查询并生成局部 HTML 补丁。

    Args:
        outline: 当前大纲 JSON
        report_html: 当前完整报告 HTML
        target_node_ids: 目标节点 node_id 列表
        updated_params: 更新后的参数字典
        data_service: 数据服务实例

    Returns:
        {"patches": [{"node_id": ..., "html": ...}], "new_data_results": {...}}
    """
    # section_resolver 已通过 sys.path 注入可直接导入
    from section_resolver import collect_l5_nodes_under
    # _gen_narrative 来自 report_writer，通过动态导入避免循环
    import importlib.util as _ilu, os as _os
    _rw_path = _os.path.normpath(_os.path.join(
        _os.path.dirname(__file__), "..", "..", "report-generate", "scripts", "report_writer.py"
    ))
    _rw_spec = _ilu.spec_from_file_location("_report_writer", _rw_path)
    _rw_mod = _ilu.module_from_spec(_rw_spec)
    _rw_spec.loader.exec_module(_rw_mod)
    _gen_narrative = _rw_mod._gen_narrative

    l5_nodes = collect_l5_nodes_under(outline, target_node_ids)
    patches = []
    new_data_results = {}

    for node in l5_nodes:
        node_id = node.get("id", "")
        node_name = node.get("name", "")
        paragraph = node.get("paragraph", {})

        binding_config = {
            "node_name": node_name,
            "binding_type": "mock",
            "mock_config": {"data_type": "", "params": {}},
        }

        try:
            data = await data_service.execute(binding_config, updated_params)
            new_data_results[node_name] = data
        except Exception as e:
            logger.warning(f"重新执行数据查询失败 {node_name}: {e}")
            data = None

        narrative = _gen_narrative(paragraph, data) if paragraph else ""
        new_html = build_indicator_html(node_name, node_id, narrative, data)
        patches.append({"node_id": node_id, "html": new_html})

    # 逐个 patch 报告 HTML
    patched_html = report_html
    for patch in patches:
        patched_html = patch_node_html(patched_html, patch["node_id"], patch["html"])

    return {
        "patches": patches,
        "new_report_html": patched_html,
        "new_data_results": new_data_results,
    }


# ─── 文本层修改 ───


async def modify_text(
    outline: dict,
    report_html: str,
    target_node_id: str,
    instruction: str,
    node_name: str,
    llm_service,
) -> dict:
    """对目标节点的 narrative 文字用 LLM 改写。

    Args:
        outline: 当前大纲 JSON
        report_html: 当前完整报告 HTML
        target_node_id: 目标 L5 节点 node_id
        instruction: 用户的改写要求
        node_name: 节点名称（用于 Prompt 上下文）
        llm_service: LLM 服务实例

    Returns:
        {"patch": {"node_id": ..., "html": ...}, "new_report_html": ...}
    """
    # 提取当前文字
    current_html = extract_node_html(report_html, target_node_id)
    current_text = extract_narrative_text(current_html)

    prompt = (
        f"你是专业的网络分析报告撰写专家。\n\n"
        f"## 指标名称\n{node_name}\n\n"
        f"## 当前分析文字\n{current_text or '（暂无）'}\n\n"
        f"## 修改要求\n{instruction}\n\n"
        f"请输出修改后的段落文字，保持专业严谨的风格，不超过200字。只输出文字内容，不加标题或额外格式。"
    )

    try:
        new_text = await llm_service.complete(prompt)
        new_text = new_text.strip()
    except Exception as e:
        logger.error(f"LLM 改写失败: {e}")
        return {"patch": None, "new_report_html": report_html, "error": str(e)}

    # 替换 .narrative 段落
    if current_html:
        new_narrative_html = f'<p class="narrative">{new_text}</p>'
        if '<p class="narrative">' in current_html:
            new_node_html = re.sub(
                r'<p\s+class="narrative">.*?</p>',
                new_narrative_html,
                current_html,
                count=1,
                flags=re.DOTALL,
            )
        else:
            # 在 <h4> 后插入
            new_node_html = re.sub(
                r'(</h4>)',
                rf'\1{new_narrative_html}',
                current_html,
                count=1,
            )
        patched_html = patch_node_html(report_html, target_node_id, new_node_html)
    else:
        patched_html = report_html

    patch = {"node_id": target_node_id, "html": new_node_html if current_html else ""}
    return {"patch": patch, "new_report_html": patched_html}
