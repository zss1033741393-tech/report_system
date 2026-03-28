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

## Scripts
- scripts/param_inject_executor.py
