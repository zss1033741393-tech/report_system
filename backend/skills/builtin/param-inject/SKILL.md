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

# 参数注入

## 适用场景
用户希望在执行数据查询时加入过滤条件或修改阈值。
触发词："只看金融行业"、"阈值改为 XX"、"只看 XX 时间段"、"过滤掉 XX 类型"。

## 使用工具
`inject_params(session_id, param_updates)`

param_updates 示例：
```json
{"industry": ["金融"], "threshold": 0.8, "time_range": "2024Q4"}
```

## 参数类型
- industry: 行业过滤（list）
- threshold: 数值阈值（float）
- time_range: 时间范围（string）
- 其他自定义参数均支持

## 重要后续操作
参数注入完成后，若当前会话已有报告（has_report=true）：
**必须** 调用 `execute_data` → `render_report` 刷新报告
