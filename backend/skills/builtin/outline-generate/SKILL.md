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

## Workflow
0. **Skill 库优先匹配**（新增）：FAISS 检索 skill_dir，score > 阈值则直接加载 references/outline.json
1. 语义向量化 → 2. FAISS检索 → 3. 路径补充 → 4. 锚节点选择
5. L5确认 → 6. 子树遍历 → 7. 大纲渲染

## Scripts
- scripts/graph_rag_executor.py
