"""统一模板加载服务。

加载优先级：
1. custom_dir（调用方传入的自定义目录）
2. skills/builtin/report-generate/templates/report/（默认模板）
3. 硬编码兜底字符串（仅极端情况）
"""
import logging
import os

logger = logging.getLogger(__name__)

_SKILL_TEMPLATE_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "skills", "builtin",
    "report-generate", "templates", "report",
))

_FALLBACK_TEMPLATE = (
    "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'>"
    "<title>{{ title }}</title></head><body>"
    "<h1>{{ title }}</h1>"
    "{% for chapter in chapters %}"
    "<h2>{{ chapter.number }}. {{ chapter.name }}</h2>"
    "{% for section in chapter.sections %}"
    "<h3>{{ section.number }} {{ section.name }}</h3>"
    "{% endfor %}{% endfor %}"
    "</body></html>"
)


def load_report_template(custom_dir: str = "") -> str:
    """加载报告模板字符串，返回 Jinja2 模板文本。"""
    for base in [custom_dir, _SKILL_TEMPLATE_DIR]:
        if not base:
            continue
        for name in ["default.html.j2", "default.html", "report.html.j2"]:
            path = os.path.join(base, name)
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()

    logger.warning("所有模板路径均不可用，使用硬编码兜底模板")
    return _FALLBACK_TEMPLATE
