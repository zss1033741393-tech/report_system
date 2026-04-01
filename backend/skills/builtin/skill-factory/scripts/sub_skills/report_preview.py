"""Sub-Step 5：报告预览——MockDataService + Jinja2 渲染。"""
import json, logging, os
from typing import AsyncGenerator
from sub_skills.base import SubSkillBase
from context import SkillFactoryContext
from agent.context import SkillContext

logger = logging.getLogger(__name__)

# 模板目录
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")


class ReportPreview(SubSkillBase):
    name = "report_preview"

    async def execute(self, fc: SkillFactoryContext, ctx: SkillContext) -> AsyncGenerator[str, None]:
        from services.data.data_service_factory import create_data_service
        import asyncio
        mock_svc = create_data_service()
        data_results = {}

        # 1. Mock 数据并行获取
        async def _fetch_one(binding):
            name = binding.get("node_name", "")
            try:
                return name, await mock_svc.execute(binding, {})
            except Exception as e:
                logger.warning(f"Mock 数据获取失败 {name}: {e}")
                return name, None

        results = await asyncio.gather(*[_fetch_one(b) for b in fc.bindings])
        for name, data in results:
            if data is not None:
                data_results[name] = data

        # 2. 构建章节
        chapters = _build_chapters(fc.outline_json, data_results)

        # 3. 构建 intro（直接用原始输入，不依赖 structured_text）
        intro = fc.raw_input[:500] if fc.raw_input else ""
        if fc.dimension_hints:
            intro += "\n\n**知识库节点映射：**\n" + "\n".join(
                f"- {h.get('name','')}" for h in fc.dimension_hints if h.get('name')
            )

        # 4. 渲染 HTML
        fc.report_html = _render_html(fc.scene_intro or fc.skill_name, intro, chapters, data_results, fc)

        # 5. SSE 分块推送
        chunk_size = 4096
        for i in range(0, len(fc.report_html), chunk_size):
            yield json.dumps({"type": "report_chunk", "content": fc.report_html[i:i+chunk_size]}, ensure_ascii=False)
        yield json.dumps({"type": "report_done", "title": fc.scene_intro or fc.skill_name}, ensure_ascii=False)


# ─── 报告构建工具函数 ───

def _render_html(title, intro, chapters, data_results, fc):
    """尝试 Jinja2 渲染，fallback 到内置方法。"""
    template_str = _load_template()
    try:
        from jinja2 import Template
        tmpl = Template(template_str)
        return tmpl.render(title=title, intro=intro, chapters=chapters)
    except Exception as e:
        logger.warning(f"Jinja2 渲染失败（{e}），使用 fallback")
        return _fallback_html(title, intro, chapters)


def _load_template() -> str:
    """加载 Jinja2 模板：优先自有 templates/ 目录，再 template_loader 统一入口。"""
    # 1. 自有模板覆盖
    own = os.path.join(_TEMPLATE_DIR, "report.html.j2")
    if os.path.isfile(own):
        with open(own, "r", encoding="utf-8") as f:
            return f.read()
    # 2. 统一模板加载器（report-generate/templates/report/default.html.j2）
    try:
        from services.template_loader import load_report_template
        return load_report_template()
    except Exception:
        pass
    # 3. 内联 fallback
    return _INLINE_TEMPLATE


def _build_chapters(outline, data_results):
    root_level = outline.get("level", 0)
    children = outline.get("children", [])
    if root_level <= 2:
        chapters, ch = [], 0
        for child in children:
            lv = child.get("level", 0)
            if lv == 3:
                ch += 1; chapters.append(_one_chapter(child, ch, data_results))
            elif lv == 4:
                ch += 1; chapters.append({"number": ch, "name": child.get("name",""), "description": "",
                                          "sections": [_one_section(child, 1, data_results)]})
        return chapters
    elif root_level == 3:
        # 检查 children 是否也有 L3（根节点是"虚拟根"）
        has_l3 = any(c.get("level") == 3 for c in children)
        if has_l3:
            chapters, ch = [], 0
            for child in children:
                lv = child.get("level", 0)
                if lv == 3:
                    ch += 1; chapters.append(_one_chapter(child, ch, data_results))
                elif lv == 4:
                    ch += 1; chapters.append({"number": ch, "name": child.get("name",""), "description": "",
                                              "sections": [_one_section(child, 1, data_results)]})
            return chapters
        return [_one_chapter(outline, 1, data_results)]
    elif root_level == 4:
        return [{"number":1, "name": outline.get("name",""), "description":"",
                 "sections": [_one_section(outline, 1, data_results)]}]
    return []


def _one_chapter(dim, num, dr):
    ch = {"number": num, "name": dim.get("name",""), "description":"", "sections": []}
    sn = 0
    for c in dim.get("children", []):
        if c.get("level") in (4, 5):
            sn += 1; ch["sections"].append(_one_section(c, sn, dr))
    return ch


def _one_section(item, num, dr):
    sec = {"number": num, "name": item.get("name",""), "description":"", "indicators": []}
    for ind in item.get("children", []):
        if ind.get("level") == 5:
            sec["indicators"].append({"name": ind.get("name",""), "data": dr.get(ind.get("name",""))})
    if not item.get("children") and item.get("level") == 5:
        sec["indicators"].append({"name": item.get("name",""), "data": dr.get(item.get("name",""))})
    return sec


def _fallback_html(title, intro, chapters):
    parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'>",
             "<style>body{font-family:-apple-system,'Microsoft YaHei',sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#303133;line-height:1.8}",
             "h1{color:#1a1a2e;border-bottom:3px solid #409eff;padding-bottom:10px}h2{color:#2c3e50;margin-top:30px;border-left:4px solid #409eff;padding-left:12px}",
             "h3{color:#606266}table{width:100%;border-collapse:collapse;margin:12px 0}th,td{border:1px solid #ebeef5;padding:8px 12px}th{background:#f5f7fa}",
             ".chart-ph{background:#f0f2f5;border-radius:8px;padding:30px;text-align:center;color:#909399;margin:12px 0}",
             f"</style></head><body><h1>{title}</h1>"]
    if intro: parts.append(f"<div style='line-height:1.8'>{intro[:500].replace(chr(10),'<br>')}</div>")
    for ch in chapters:
        parts.append(f"<h2>{ch['number']}. {ch['name']}</h2>")
        for sec in ch.get("sections", []):
            parts.append(f"<h3>{ch['number']}.{sec['number']} {sec['name']}</h3>")
            for ind in sec.get("indicators", []):
                d = ind.get("data")
                if d:
                    dt = d.get("data_type", "")
                    if dt == "TABLE" and d.get("data"):
                        cols = d.get("columns", list(d["data"][0].keys()) if d["data"] else [])
                        hdr = "".join(f"<th>{c}</th>" for c in cols)
                        parts.append(f"<h4>{ind['name']}</h4><table><tr>{hdr}</tr>")
                        for row in d["data"][:5]:
                            cells = "".join(f"<td>{row.get(c,'')}</td>" for c in cols)
                            parts.append(f"<tr>{cells}</tr>")
                        parts.append("</table>")
                    elif dt == "SINGLE_VALUE" and d.get("data"):
                        parts.append(f"<h4>{ind['name']}</h4><span style='font-size:32px;font-weight:700;color:#409eff'>{d['data'].get('value','')}{d['data'].get('unit','')}</span>")
                    elif dt in ("PIE_CHART","BAR_CHART","LINE_CHART","HEATMAP"):
                        parts.append(f"<div class='chart-ph'>[{dt}] {ind['name']}</div>")
                else:
                    parts.append(f"<p><strong>{ind['name']}</strong>: 暂无数据</p>")
    parts.append("<div style='margin-top:40px;border-top:1px solid #ebeef5;padding-top:16px;color:#c0c4cc;font-size:12px;text-align:center'>由智能看网系统自动生成</div></body></html>")
    return "\n".join(parts)


_INLINE_TEMPLATE = """<!DOCTYPE html><html><head><meta charset='utf-8'><title>{{ title }}</title>
<style>body{font-family:-apple-system,'Microsoft YaHei',sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#303133;line-height:1.8}
h1{color:#1a1a2e;border-bottom:3px solid #409eff;padding-bottom:10px}h2{color:#2c3e50;margin-top:30px;border-left:4px solid #409eff;padding-left:12px}
h3{color:#606266}table{width:100%;border-collapse:collapse;margin:12px 0}th,td{border:1px solid #ebeef5;padding:8px 12px}th{background:#f5f7fa}
.single-value{font-size:32px;font-weight:700;color:#409eff}.chart-ph{background:#f0f2f5;border-radius:8px;padding:30px;text-align:center;color:#909399;margin:12px 0}
.intro{line-height:1.8;color:#606266;margin-bottom:20px;padding:16px;background:#f8f9fb;border-radius:8px;border-left:4px solid #409eff}</style></head>
<body><h1>{{ title }}</h1>{% if intro %}<div class="intro">{{ intro | replace("\\n", "<br>") }}</div>{% endif %}
{% for ch in chapters %}<h2>{{ ch.number }}. {{ ch.name }}</h2>{% if ch.description %}<p>{{ ch.description }}</p>{% endif %}
{% for sec in ch.sections %}<h3>{{ ch.number }}.{{ sec.number }} {{ sec.name }}</h3>
{% for ind in sec.indicators %}{% if ind.data %}{% if ind.data.data_type == "SINGLE_VALUE" %}<p><strong>{{ ind.name }}</strong>: <span class="single-value">{{ ind.data.data.value }}{{ ind.data.data.unit }}</span></p>
{% elif ind.data.data_type == "TABLE" %}<h4>{{ ind.name }}</h4><table><tr>{% for col in ind.data.columns %}<th>{{ col }}</th>{% endfor %}</tr>{% for row in ind.data.data %}<tr>{% for col in ind.data.columns %}<td>{{ row[col] }}</td>{% endfor %}</tr>{% endfor %}</table>
{% else %}<div class="chart-ph">[{{ ind.data.data_type }}] {{ ind.name }}</div>{% endif %}{% else %}<p>{{ ind.name }}: 暂无数据</p>{% endif %}{% endfor %}
{% endfor %}{% endfor %}<div style="margin-top:40px;border-top:1px solid #ebeef5;padding-top:16px;color:#c0c4cc;font-size:12px;text-align:center">由智能看网系统自动生成</div></body></html>"""
