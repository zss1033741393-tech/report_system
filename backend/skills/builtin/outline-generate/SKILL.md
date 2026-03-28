---
name: outline-generate
display_name: 大纲生成
description: 先检索已沉淀 Skill（Step 0），命中则直接加载大纲；未命中走 GraphRAG 流程生成临时大纲，支持条件裁剪
enabled: true
params:
  query:
    type: string
    required: true
    description: 用户的分析需求文本
executor:
  module: graph_rag_executor
  class: GraphRAGExecutor
  deps:
    - llm_service
    - embedding_service
    - faiss_retriever
    - neo4j_retriever
    - outline_renderer
    - session_service
  config:
    top_k: 10
    score_threshold: 0.5
---

# 大纲生成

## 适用场景

用户提出分析需求（短文本查询），需要系统生成对应的看网大纲。
例如："帮我分析 fgOTN 容量"、"从传送网角度看设备分布"。

## 工作流（按序调用工具）

```
1. search_skill(query)
   → 在知识库检索是否有匹配的已沉淀看网能力（score > 0.5）
   → 命中：直接加载该能力的大纲 JSON（跳到步骤 4）
   → 未命中：继续步骤 2

2. [GraphRAG 流程（内部自动执行）]
   → 语义向量化 → FAISS 检索 → 路径补充 → 锚节点选择
   → 若存在 L5 层级需确认，yield awaiting_confirm 事件，等待用户选择

3. [可选] 等待 L5 层级确认
   → 用户选择后，继续子树遍历和大纲渲染

4. 大纲保存到当前会话（自动）
   → 告知用户大纲已生成，请查看右侧面板
```

## 关键规则

- search_skill 是首要步骤，不能跳过（避免重复生成已有能力）
- 存在已有大纲时，询问用户是否替换，不要直接覆盖
- 大纲生成后，若用户需要报告，继续调用 execute_data + render_report
