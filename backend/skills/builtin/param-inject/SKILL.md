---
name: param-inject
display_name: 参数透传注入
description: 将用户指定的参数（行业、阈值、时间范围等）注入对应节点的数据绑定配置，替代原 threshold-modify
enabled: true
params:
  target_node:
    type: string
    required: false
    description: 目标节点名称
  param_key:
    type: string
    required: true
    description: 参数名
  param_value:
    type: string
    required: true
    description: 参数值
executor:
  module: param_inject_executor
  class: ParamInjectExecutor
  deps:
    - session_service
---

# 参数透传注入

## 适用场景
已有大纲，用户要求修改过滤条件或阈值（如"只看金融行业"、"阈值改为 90%"）。

## 工具调用：inject_params(param_key, param_value, target_node?)
将参数存入 Redis，后续 execute_data 执行时自动应用。

常见参数：
- industry: 行业过滤（如"金融"、"能源"）
- threshold: 阈值（如"0.9"）
- time_range: 时间范围（如"2024Q1"）
- region: 区域过滤

## 关键规则
- inject_params 后**必须**重新执行 execute_data + render_report
- target_node 为空时全局注入（所有节点生效）
- 参数累积：多次调用会叠加，不会覆盖其他参数
