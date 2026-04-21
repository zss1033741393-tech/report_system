---
name: outline-generate
display_name: 大纲生成
description: 通过 GraphRAG 流程生成分析大纲，支持条件裁剪。已沉淀能力由 skill_router 工具提前路由，本工具专注于 GraphRAG 检索生成
enabled: true
params:
  query:
    type: string
    required: true
    description: 用户的分析需求文本
paradigm: Pipeline
executor:
  module: graph_rag_executor
  class: GraphRAGExecutor
  deps:
    - embedding_service
    - faiss_retriever
    - neo4j_retriever
    - outline_renderer
    - session_service
    - indicator_resolver
  config:
    top_k: 10
    score_threshold: 0.5
---

# 大纲生成（GraphRAG 工作流）

## 适用场景
用户提出网络分析需求（如"分析 fgOTN 容量"、"评估传送网质量"），需要生成分析大纲。

## Metadata
- **paradigm**: Pipeline（多阶段流水线，各阶段职责严格分离）
- **when_to_use**: 用户提出网络分析需求，需生成分析大纲时，通过 `search_skill` 工具调用
- **inputs**: query（用户需求文本）、anchor（tool 层 LLM 预计算的锚点）、remove_nodes（可选）
- **outputs**: subtree（大纲树 JSON）、outline_md（Markdown 大纲）、anchor_info

## When to Use
- ✅ 用户说"分析 XX"/"帮我看 XX"/"评估 XX"
- ✅ skill_router 未找到精确匹配，需临时 GraphRAG 生成
- ❌ 已有大纲且用户只是裁剪/参数调整（改用 clip_outline）

## How to Use（Pipeline 各阶段）

> LLM 推理在 **tool 层**（`tool_definitions._search_skill`）完成，executor 只做纯算法。

**Phase 1：语义检索（executor 执行）**
Embedding → FAISS search（top_k=10, threshold=0.5）→ Neo4j 祖先路径

**Phase 2：锚点选择（tool 层 LLM，结果传入 params.anchor）**
`_llm_select_anchor(query, nodes)` → 选出最合适的 L2~L4 起始节点

**Phase 3：L5 确认（executor 执行，如触发）**
锚点为叶节点（L5）→ 发送 `confirm_required` SSE → 等待用户选择层级

**Phase 4：子树遍历 + 条件裁剪（executor 执行）**
Neo4j get_subtree → 接收 params.remove_nodes 做树剪枝

**Phase 5：paragraph 合并 + 大纲渲染（executor 执行）**
IndicatorResolver 补全 L5 paragraph → OutlineRenderer 流式输出 Markdown

## References
- `references/anchor_select_prompt.md` — 锚点选择 LLM prompt
- `references/condition_filter_prompt.md` — 条件裁剪 LLM prompt
- `references/bottom_up_prompt.md` — 路径B 自底向上大纲组织 prompt

## 关键规则
- executor 不含任何 LLM 调用，所有 LLM 推理由 tool 层统一完成
- 大纲生成后若需报告，必须继续调用 execute_data + render_report
- 若用户附加约束（"不看XX"/"只看XX"），在 search_skill 后追加 clip_outline
