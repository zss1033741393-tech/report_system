---
name: data-execute
display_name: 数据执行
description: 按大纲顺序执行各节点的数据绑定（Mock/SQL/API），获取结构化数据，替代原 data-query
enabled: true
params:
  outline_json:
    type: object
    required: false
    description: 要执行的大纲 JSON（不传则用当前会话大纲）
executor:
  module: data_execute_executor
  class: DataExecuteExecutor
  deps:
    - session_service
    - kb_store
---

# 数据执行

## 适用场景

在大纲生成（或裁剪/参数修改）后，需要获取各评估指标的实际数据。
这是生成报告前的必要步骤。

## 工作流（单步调用）

```
execute_data(session_id)
→ 遍历当前大纲的所有 L5 评估指标节点
→ 读取会话级参数条件（行业/阈值等，由 inject_params 注入）
→ 按节点的数据绑定配置（Mock/SQL/API）执行查询
→ 返回结构化数据结果，供 render_report 使用
```

## 关键规则

- **必须在 render_report 之前调用**
- 使用当前会话的大纲和参数条件（自动读取，无需手动传入）
- 数据执行失败的节点会记录错误，不影响其他节点
- 大纲裁剪或参数修改后，必须重新调用此工具（旧数据与新大纲不对应）

## 数据源类型

| 类型 | 说明 | 当前状态 |
|------|------|---------|
| mock | 模拟数据（MockDataService） | 默认启用 |
| sql | SQL 查询 | 预留 |
| api | 外部 API | 预留 |
