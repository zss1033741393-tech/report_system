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
在生成大纲、裁剪大纲或注入参数之后，需要获取各评估指标的实际数据。
是渲染报告（render_report）的前置步骤，必须先执行。

## 使用工具
`execute_data(session_id)`

无需额外参数，自动读取当前会话的大纲和注入的过滤条件。

## 执行内容
- 遍历大纲中所有 L5（评估指标）节点
- 根据每个节点的数据绑定配置（Mock/SQL/API）获取数据
- 合并用户通过 inject_params 注入的过滤参数

## 数据源类型（当前支持）
- mock: MockDataService（默认，用于演示）
- sql / api: 预留扩展接口

## 执行顺序
大纲已就绪 → execute_data → render_report
