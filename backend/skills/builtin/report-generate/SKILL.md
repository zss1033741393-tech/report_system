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

## 适用场景
用户需要查看完整的分析报告（HTML 格式）。必须在 execute_data 成功后调用。
触发词："生成报告"、"展示报告"、"看结果"，或在大纲/参数修改后自动触发。

## 使用工具
`render_report(session_id)`

## 渲染内容
- 读取当前会话大纲结构（L1-L5 层次）
- 读取 execute_data 的数据结果
- 用 Jinja2 模板生成完整 HTML 报告
- SSE 分块流式推送到前端（report_chunk 事件）

## 完整报告生成流程
```
search_skill(query) 或已有大纲
  → [可选] clip_outline / inject_params
  → execute_data
  → render_report   ← 本步骤
```

## 注意
- 如果 execute_data 尚未执行，render_report 会使用空数据（报告显示"暂无数据"）
- 每次大纲或参数变更后都需重新执行此流程
