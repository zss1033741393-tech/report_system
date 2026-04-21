# 意图提取 Prompt

将专家输入的自然语言看网逻辑结构化为 scene_intro / keywords / query_variants / skill_name。

## System Prompt

（空字符串，全部上下文在 user message 中）

## User Message Template

```
你是看网逻辑分析专家。分析看网逻辑文本，提取结构化信息。

## 输出格式
{"scene_intro":"50字以内","keywords":["3-5个关键词"],"query_variants":["3种用户问法"],"skill_name":"英文下划线"}

## 示例
输入: "从传送网络容量角度分析fgOTN部署机会"
{"scene_intro":"分析fgOTN传送网络容量，评估部署机会","keywords":["fgOTN","传送网络","容量分析","部署"],"query_variants":["帮我分析fgOTN网络容量","fgOTN部署机会分析","传送网络容量评估"],"skill_name":"fgOTN_Capacity_Analysis"}

## 看网逻辑
{raw_input}

用 ```json ``` 代码块包裹输出。
```

## 输出字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| scene_intro | string | 50 字以内的场景简介 |
| keywords | list[str] | 3~5 个关键词 |
| query_variants | list[str] | 3 种用户触发问法 |
| skill_name | string | 英文下划线命名的技能标识 |

## 降级策略

LLM 失败时返回 `{"scene_intro":"","keywords":[],"query_variants":[],"skill_name":"unnamed_skill"}`。
