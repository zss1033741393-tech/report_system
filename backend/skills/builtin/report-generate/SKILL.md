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

在数据执行完成后，渲染生成完整的 HTML 格式看网报告。
这是看网分析流程的最后一步。

## 工作流（单步调用）

```
render_report(session_id)
→ 读取当前会话的大纲结构
→ 读取 execute_data 的数据结果
→ Jinja2 模板渲染完整 HTML 报告
→ SSE 分块推送 report_chunk 事件
→ 报告 HTML 保存到 assistant 消息 metadata
→ yield report_done 事件，前端显示报告
```

## 关键规则

- **必须在 execute_data 之后调用**（需要数据结果）
- **必须在有大纲的情况下调用**（需要大纲结构）
- 大纲裁剪或参数修改后，需要先重新 execute_data，再 render_report
- 报告生成后，右侧面板自动切换到报告视图

## 完整运行态调用序列

用户首次生成报告：
```
search_skill → [outline-generate] → execute_data → render_report
```

裁剪大纲后刷新报告：
```
clip_outline → execute_data → render_report
```

修改参数后刷新报告：
```
inject_params → execute_data → render_report
```
