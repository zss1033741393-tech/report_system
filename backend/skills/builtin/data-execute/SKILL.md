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
已有大纲，需要查询各指标的实际数据（用于生成报告）。
**必须在 render_report 之前执行**。

## 工具调用：execute_data()
无需传参，自动使用当前会话大纲执行所有 L5 指标节点的数据查询。

内部流程：
1. 遍历大纲树，收集所有 L5 叶节点
2. 从 Redis 读取当前会话的过滤参数（如行业条件）
3. 按数据源类型（mock/sql/api）执行查询
4. 返回结构化数据字典（用于报告渲染）

## 关键规则
- 必须先有大纲（search_skill 或 clip_outline 后）才能执行
- 执行成功后，立即调用 render_report 生成报告
- 大纲被修改（clip/inject）后必须重新执行 execute_data
