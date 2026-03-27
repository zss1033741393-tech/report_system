---
name: report-generate
display_name: 报告生成
description: 基于大纲和数据执行结果，使用 Jinja2 渲染完整 Web HTML 报告
enabled: true
params:
  style:
    type: string
    required: false
    description: 报告风格
executor:
  module: report_writer
  class: ReportWriterExecutor
  deps:
    - llm_service
    - kb_store
---

# 报告生成

## Workflow
1. 加载大纲 + 数据执行结果
2. Jinja2 模板渲染 HTML
3. SSE 分块推送

## Scripts
- scripts/report_writer.py
