"""报告生成执行器 v3：Jinja2 HTML 渲染（支持 narrative 文字 + data-node-id）。

基于大纲 + 数据执行结果，渲染完整 Web HTML 报告。
模板从 report-generate/templates/report/ 目录加载，通过 template_loader 统一管理。
"""
import json
import logging
import os
import re
from typing import AsyncGenerator, Union

from agent.context import SkillContext, SkillResult
from llm.service import LLMService
from services.kb_content_store import KBContentStore

logger = logging.getLogger(__name__)


def _ts(step, status, detail, data=None):
    p = {"type": "thinking_step", "step": step, "status": status, "detail": detail}
    if data:
        p["data"] = data
    return json.dumps(p, ensure_ascii=False)


def _gen_narrative(paragraph: dict, data: dict) -> str:
    """从 paragraph 模板 + metric_values 生成 narrative 文字。"""
    content = paragraph.get("content", "")
    if not content:
        return ""

    # 合并参数（paragraph.params 提供默认值，metric_values 提供实际值）
    merged = {}
    for k, v in paragraph.get("params", {}).items():
        merged[k] = v.get("value", "") if isinstance(v, dict) else v
    merged.update((data or {}).get("metric_values", {}))

    def replace(m):
        key = m.group(1)
        val = merged.get(key)
        if val is None:
            return f"[{key}]"
        return str(val)

    return re.sub(r'\{(\w+)\}', replace, content)


class ReportWriterExecutor:

    def __init__(self, llm_service: LLMService, kb_store: KBContentStore):
        self._llm = llm_service
        self._kb = kb_store

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        outline = ctx.current_outline
        if not outline:
            yield SkillResult(False, "当前没有大纲，请先生成大纲")
            return

        yield _ts("report_generate", "running", "正在生成报告...")

        # 从 step_results 获取数据执行结果
        data_results = ctx.step_results.get("data_results", {})
        if not data_results:
            for k, v in ctx.step_results.items():
                if isinstance(v, SkillResult) and isinstance(v.data, dict) and v.data.get("data_results"):
                    data_results = v.data["data_results"]
                    break

        # 获取 kb_contents 描述
        node_ids = self._collect_ids(outline)
        kb_data = await self._kb.get_batch(node_ids) if node_ids else {}

        # 构建模板数据
        title = outline.get("name", "看网分析报告")
        root_kb = kb_data.get(outline.get("id", ""), {})
        intro = root_kb.get("expand_logic", "") or root_kb.get("description", "")

        chapters = self._build_chapters(outline, kb_data, data_results)

        # Jinja2 渲染
        try:
            from jinja2 import Template
            template = Template(self._load_template())
            html = template.render(title=title, intro=intro, chapters=chapters)
        except ImportError:
            html = self._fallback_render(title, intro, chapters)
        except Exception as e:
            logger.warning(f"Jinja2 渲染失败: {e}")
            html = self._fallback_render(title, intro, chapters)

        # SSE 分块推送
        chunk_size = 4096
        for i in range(0, len(html), chunk_size):
            yield json.dumps({"type": "report_chunk", "content": html[i:i+chunk_size]}, ensure_ascii=False)

        yield json.dumps({"type": "report_done", "title": title}, ensure_ascii=False)
        yield _ts("report_generate", "done", f"报告生成完成，共 {len(chapters)} 章")

        yield SkillResult(True, f"已生成「{title}」报告，共 {len(chapters)} 章",
                          data={"report_html": html, "chapter_count": len(chapters)})

    def _build_chapters(self, outline, kb_data, data_results):
        """从大纲构建报告章节——支持任意层级的锚节点。"""
        root_level = outline.get("level", 0)
        children = outline.get("children", [])

        if root_level <= 2:
            return self._chapters_from_l3(children, kb_data, data_results)
        elif root_level == 3:
            has_l3_children = any(c.get("level") == 3 for c in children)
            if has_l3_children:
                return self._chapters_from_l3(children, kb_data, data_results)
            return [self._build_one_chapter(outline, 1, kb_data, data_results)]
        elif root_level == 4:
            return [{"number": 1, "name": outline.get("name", ""), "node_id": outline.get("id", ""),
                     "description": "",
                     "sections": [self._build_one_section(outline, 1, kb_data, data_results)]}]
        else:
            return [{"number": 1, "name": outline.get("name", ""), "node_id": outline.get("id", ""),
                     "description": "", "sections": []}]

    def _chapters_from_l3(self, children, kb_data, data_results):
        chapters = []
        ch_num = 0
        for child in children:
            level = child.get("level", 0)
            if level == 3:
                ch_num += 1
                chapters.append(self._build_one_chapter(child, ch_num, kb_data, data_results))
            elif level == 2:
                for gc in child.get("children", []):
                    if gc.get("level") == 3:
                        ch_num += 1
                        chapters.append(self._build_one_chapter(gc, ch_num, kb_data, data_results))
            elif level == 4:
                ch_num += 1
                chapters.append({"number": ch_num, "name": child.get("name", ""),
                                  "node_id": child.get("id", ""), "description": "",
                                  "sections": [self._build_one_section(child, 1, kb_data, data_results)]})
        return chapters

    def _build_one_chapter(self, dim_node, ch_num, kb_data, data_results):
        dim_kb = kb_data.get(dim_node.get("id", ""), {})
        chapter = {
            "number": ch_num,
            "name": dim_node.get("name", ""),
            "node_id": dim_node.get("id", ""),
            "description": dim_kb.get("description", ""),
            "sections": [],
        }
        sec_num = 0
        for child in dim_node.get("children", []):
            if child.get("level") == 4:
                sec_num += 1
                chapter["sections"].append(
                    self._build_one_section(child, sec_num, kb_data, data_results)
                )
        return chapter

    def _build_one_section(self, item_node, sec_num, kb_data, data_results):
        item_kb = kb_data.get(item_node.get("id", ""), {})
        section = {
            "number": sec_num,
            "name": item_node.get("name", ""),
            "node_id": item_node.get("id", ""),
            "description": item_kb.get("chapter_template", "") or item_kb.get("description", ""),
            "indicators": [],
        }
        for ind in item_node.get("children", []):
            if ind.get("level") == 5:
                ind_name = ind.get("name", "")
                ind_data = data_results.get(ind_name)
                paragraph = ind.get("paragraph", {})
                narrative = _gen_narrative(paragraph, ind_data) if paragraph else ""
                section["indicators"].append({
                    "name": ind_name,
                    "node_id": ind.get("id", ""),
                    "data": ind_data,
                    "narrative": narrative,
                })
        return section

    def _load_template(self):
        """通过统一 template_loader 加载模板。"""
        from config import settings
        from services.template_loader import load_report_template
        return load_report_template(custom_dir=settings.REPORT_TEMPLATE_DIR)

    @staticmethod
    def _fallback_render(title, intro, chapters):
        parts = [f"<html><head><meta charset='utf-8'><title>{title}</title></head><body>"]
        parts.append(f"<h1>{title}</h1>")
        if intro:
            parts.append(f"<p>{intro}</p>")
        for ch in chapters:
            parts.append(f"<h2>{ch['number']}. {ch['name']}</h2>")
            if ch.get("description"):
                parts.append(f"<p>{ch['description']}</p>")
            for sec in ch.get("sections", []):
                parts.append(f"<h3>{ch['number']}.{sec['number']} {sec['name']}</h3>")
                for ind in sec.get("indicators", []):
                    narrative = ind.get("narrative", "")
                    if narrative:
                        parts.append(f"<p>{narrative}</p>")
                    parts.append(f"<p><strong>{ind['name']}</strong>: {'有数据' if ind.get('data') else '暂无'}</p>")
        parts.append("</body></html>")
        return "\n".join(parts)

    @staticmethod
    def _collect_ids(node):
        ids = []
        nid = node.get("id", "")
        if nid:
            ids.append(nid)
        for c in node.get("children", []):
            ids.extend(ReportWriterExecutor._collect_ids(c))
        return ids
