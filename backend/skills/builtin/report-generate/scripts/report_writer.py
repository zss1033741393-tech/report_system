"""报告生成执行器 v2：Jinja2 HTML 渲染。

基于大纲 + 数据执行结果，渲染完整 Web HTML 报告。
"""
import json
import logging
import os
from typing import AsyncGenerator, Union

from agent.context import SkillContext, SkillResult
from llm.service import LLMService
from services.kb_content_store import KBContentStore

logger = logging.getLogger(__name__)

# 内置 HTML 模板（当 templates/report/ 目录没有模板时使用）
DEFAULT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }}</title>
<style>
  body { font-family: -apple-system, 'Microsoft YaHei', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; color: #303133; line-height: 1.8; }
  h1 { color: #1a1a2e; border-bottom: 3px solid #409eff; padding-bottom: 10px; }
  h2 { color: #2c3e50; margin-top: 30px; border-left: 4px solid #409eff; padding-left: 12px; }
  h3 { color: #606266; margin-top: 20px; }
  .data-section { background: #f8f9fb; border-radius: 8px; padding: 16px; margin: 12px 0; }
  .data-section h4 { margin: 0 0 8px; color: #409eff; }
  table { width: 100%; border-collapse: collapse; margin: 12px 0; }
  th, td { border: 1px solid #ebeef5; padding: 8px 12px; text-align: left; }
  th { background: #f5f7fa; color: #606266; font-weight: 600; }
  .single-value { font-size: 32px; font-weight: 700; color: #409eff; }
  .single-unit { font-size: 14px; color: #909399; margin-left: 4px; }
  .chart-placeholder { background: #f0f2f5; border-radius: 8px; padding: 40px; text-align: center; color: #c0c4cc; }
  .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #ebeef5; color: #c0c4cc; font-size: 12px; text-align: center; }
  .intro { line-height: 1.8; color: #606266; margin-bottom: 20px; padding: 16px; background: #f8f9fb; border-radius: 8px; border-left: 4px solid #409eff; }
</style>
</head>
<body>
<h1>{{ title }}</h1>
{% if intro %}<div class="intro">{{ intro | replace("\n", "<br>") }}</div>{% endif %}

{% for chapter in chapters %}
<h2>{{ chapter.number }}. {{ chapter.name }}</h2>
{% if chapter.description %}<p>{{ chapter.description }}</p>{% endif %}

{% for section in chapter.sections %}
<h3>{{ chapter.number }}.{{ section.number }} {{ section.name }}</h3>
{% if section.description %}<p>{{ section.description }}</p>{% endif %}

{% for indicator in section.indicators %}
<div class="data-section">
  <h4>{{ indicator.name }}</h4>
  {% if indicator.data %}
    {% if indicator.data.data_type == "SINGLE_VALUE" %}
      <span class="single-value">{{ indicator.data.data.value }}</span>
      <span class="single-unit">{{ indicator.data.data.unit }}</span>
    {% elif indicator.data.data_type == "TABLE" %}
      <table>
        <tr>{% for col in indicator.data.columns %}<th>{{ col }}</th>{% endfor %}</tr>
        {% for row in indicator.data.data %}
        <tr>{% for col in indicator.data.columns %}<td>{{ row[col] }}</td>{% endfor %}</tr>
        {% endfor %}
      </table>
    {% elif indicator.data.data_type in ["PIE_CHART", "BAR_CHART", "LINE_CHART", "HEATMAP"] %}
      <div class="chart-placeholder">[{{ indicator.data.data_type }} 图表: {{ indicator.name }}]</div>
    {% endif %}
  {% else %}
    <p style="color:#c0c4cc">暂无数据</p>
  {% endif %}
</div>
{% endfor %}
{% endfor %}
{% endfor %}

<div class="footer">由智能看网系统自动生成</div>
</body>
</html>"""


def _ts(step, status, detail, data=None):
    p = {"type": "thinking_step", "step": step, "status": status, "detail": detail}
    if data: p["data"] = data
    return json.dumps(p, ensure_ascii=False)


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
            # 尝试从最近的 data-execute 结果中取
            for k, v in ctx.step_results.items():
                if isinstance(v, SkillResult) and v.data.get("data_results"):
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
            # jinja2 未安装，简单拼接
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

        # 根据锚节点层级决定章节构建策略
        if root_level <= 2:
            # 锚节点是 L1/L2：children 中找 L3 作为章
            return self._chapters_from_l3(children, kb_data, data_results)
        elif root_level == 3:
            # 检查 children 是否也有 L3（说明根节点其实是"虚拟根"）
            has_l3_children = any(c.get("level") == 3 for c in children)
            if has_l3_children:
                return self._chapters_from_l3(children, kb_data, data_results)
            # 否则根节点本身就是 L3：整个 outline 就是一个章
            return [self._build_one_chapter(outline, 1, kb_data, data_results)]
        elif root_level == 4:
            # 锚节点是 L4：整个 outline 就是一个小节
            return [{"number": 1, "name": outline.get("name", ""), "description": "",
                     "sections": [self._build_one_section(outline, 1, kb_data, data_results)]}]
        else:
            # L5 或其他：直接作为单章
            return [{"number": 1, "name": outline.get("name", ""), "description": "", "sections": []}]

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
                # 如果 children 直接就是 L4，把它们组合成一个默认章
                ch_num += 1
                chapters.append({"number": ch_num, "name": child.get("name", ""), "description": "",
                                 "sections": [self._build_one_section(child, 1, kb_data, data_results)]})
        return chapters

    def _build_one_chapter(self, dim_node, ch_num, kb_data, data_results):
        dim_kb = kb_data.get(dim_node.get("id", ""), {})
        chapter = {
            "number": ch_num,
            "name": dim_node.get("name", ""),
            "description": dim_kb.get("description", ""),
            "sections": [],
        }
        sec_num = 0
        for child in dim_node.get("children", []):
            level = child.get("level", 0)
            if level == 4:
                sec_num += 1
                chapter["sections"].append(
                    self._build_one_section(child, sec_num, kb_data, data_results))
            elif level == 5:
                # L5 直接挂在 L3 下（跳过了 L4），当作独立小节处理
                sec_num += 1
                ind_data = data_results.get(child.get("name", ""))
                chapter["sections"].append({
                    "number": sec_num,
                    "name": child.get("name", ""),
                    "description": "",
                    "indicators": [{"name": child.get("name", ""), "data": ind_data}],
                })
        return chapter

    def _build_one_section(self, item_node, sec_num, kb_data, data_results):
        """从 L4 节点构建一个小节。"""
        item_kb = kb_data.get(item_node.get("id", ""), {})
        section = {
            "number": sec_num,
            "name": item_node.get("name", ""),
            "description": item_kb.get("chapter_template", "") or item_kb.get("description", ""),
            "indicators": [],
        }
        children = item_node.get("children", [])
        for ind in children:
            if ind.get("level") == 5:
                ind_data = data_results.get(ind.get("name", ""))
                section["indicators"].append({"name": ind.get("name", ""), "data": ind_data})
        # L4 叶子节点（无 L5 子节点）自身作为指标（降级处理）
        if not children:
            ind_data = data_results.get(item_node.get("name", ""))
            section["indicators"].append({"name": item_node.get("name", ""), "data": ind_data})
        return section

    def _load_template(self):
        """加载自定义模板或使用内置模板。"""
        from config import settings
        custom = os.path.join(settings.REPORT_TEMPLATE_DIR, "default.html")
        if os.path.isfile(custom):
            with open(custom, "r", encoding="utf-8") as f:
                return f.read()
        return DEFAULT_TEMPLATE

    @staticmethod
    def _fallback_render(title, intro, chapters):
        parts = [f"<html><head><meta charset='utf-8'><title>{title}</title></head><body>"]
        parts.append(f"<h1>{title}</h1>")
        if intro: parts.append(f"<p>{intro}</p>")
        for ch in chapters:
            parts.append(f"<h2>{ch['number']}. {ch['name']}</h2>")
            if ch.get("description"): parts.append(f"<p>{ch['description']}</p>")
            for sec in ch.get("sections", []):
                parts.append(f"<h3>{ch['number']}.{sec['number']} {sec['name']}</h3>")
                for ind in sec.get("indicators", []):
                    parts.append(f"<p><strong>{ind['name']}</strong>: {'有数据' if ind.get('data') else '暂无'}</p>")
        parts.append("</body></html>")
        return "\n".join(parts)

    @staticmethod
    def _collect_ids(node):
        ids = []
        nid = node.get("id", "")
        if nid: ids.append(nid)
        for c in node.get("children", []):
            ids.extend(ReportWriterExecutor._collect_ids(c))
        return ids
