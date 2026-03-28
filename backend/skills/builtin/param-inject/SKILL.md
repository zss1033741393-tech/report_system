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

用户要求修改分析的过滤条件或参数：
- "只看金融行业" → inject industry=金融
- "阈值改为 0.8" → inject threshold=0.8
- "时间改为 2024Q1" → inject time_range=2024Q1
- "只看A城市" → inject city=A

**前提：当前会话必须已有大纲。**

## 工作流（按序调用工具）

```
1. inject_params(session_id, param_key, param_value, target_node?)
   → 将参数注入到会话级条件存储（Redis）
   → 下次数据执行时自动应用这些条件

2. [如果当前已有报告] → execute_data(session_id) + render_report(session_id)
   → 参数注入后必须重新执行数据查询和报告生成，否则报告仍是旧参数的结果
```

## 关键规则

- **已有报告时，注入后必须追加 execute_data + render_report**
- target_node 为空时，参数全局生效（应用于所有节点）
- 多个参数同时修改时，多次调用 inject_params（每次一个参数）
- 参数注入是累积的，不会清除之前注入的参数

## 常用参数名映射

| 用户说法 | param_key | 示例值 |
|---------|-----------|--------|
| 只看XX行业 | industry | 金融、政府、能源 |
| 阈值改为XX | threshold | 0.8、500、1000 |
| 只看XX城市 | city | 北京、上海 |
| 时间改为XX | time_range | 2024Q1、2024H1 |
