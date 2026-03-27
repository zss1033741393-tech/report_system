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

## 数据源类型
- mock: MockDataService（当前默认）
- sql: SQLDataService（预留）
- api: APIDataService（预留）

## Scripts
- scripts/data_execute_executor.py
