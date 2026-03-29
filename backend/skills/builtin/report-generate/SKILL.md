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
已有大纲且已完成数据执行，需要生成可视化 HTML 报告。

## 工具调用：render_report()
无需传参，自动使用当前会话大纲和最新数据执行结果。

内部流程：
1. 加载当前会话的大纲 JSON
2. 从 step_results 获取 execute_data 的数据结果
3. Jinja2 模板渲染完整 HTML 报告（包含表格/图表/数值）
4. 分块 SSE 推送到前端

## 前置条件（严格要求）
- 必须已有大纲（search_skill 已执行）
- 必须已执行数据查询（execute_data 已执行）

## 报告数据类型
- SINGLE_VALUE：单值指标（如利用率 85%）
- TABLE：表格数据（如站点列表）
- PIE_CHART：饼图（如行业分布）
- HEATMAP：热力图（如时延矩阵）
