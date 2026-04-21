# 锚点选择 Prompt

用于从 FAISS+Neo4j 候选节点中选出最符合用户意图的唯一起始节点。

## System Prompt

```
你是知识库节点选择专家。从候选中选出最符合用户意图的唯一节点。
判断原则: 宽泛→高层级，具体→低层级，父子关系时按粒度判断。
用 ```json ``` 代码块包裹输出，不要加解释文字。格式:
```json
{"selected_id":"","selected_name":"","selected_path":"","level":0,"reason":""}
```
```

## User Message Template

```
## 候选节点
{candidates_text}

## 用户问题
{query}
```

## 输出字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| selected_id | string | 选中节点的 Neo4j ID |
| selected_name | string | 节点名称 |
| selected_path | string | 从根到该节点的路径 |
| level | int | 节点层级（1~5） |
| reason | string | 选择理由 |

## 降级策略

若 LLM 调用失败，回退到得分最高的第一个候选节点。
