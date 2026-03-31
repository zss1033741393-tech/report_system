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
    - indicator_resolver
  config:
    top_k: 10
    score_threshold: 0.5
---

# 大纲生成（GraphRAG 工作流）

## 适用场景
用户提出网络分析需求（如"分析 fgOTN 容量"、"评估传送网质量"），需要生成分析大纲。

## 工具调用：search_skill(query)
这是运行态大纲生成的统一入口，内部自动执行以下 7 步流程：

**Step 0：Skill 库优先匹配**
FAISS 检索已沉淀的看网能力（score > 0.7），命中则直接加载预设大纲。

**Step 1-2：语义检索**
用户查询向量化 → FAISS 搜索知识库（top_k=10, threshold=0.5），返回候选节点。

**Step 3：路径补充**
Neo4j 路径分析，补全候选节点的完整祖先链（L1→L5）。

**Step 4：锚节点选择（LLM）**
LLM 从候选节点中选择最合适的起始锚点（L2-L4 层）。

**Step 5：L5 确认（如触发）**
若锚点为叶节点（L5），向用户提示选择分析层级，等待确认后继续。

**Step 6：子树遍历**
从锚点向下遍历子树，按约束条件过滤节点。

**Step 7：大纲渲染**
生成带层级编号的 Markdown 大纲，流式输出。

## 关键规则
- 大纲生成后若需要报告，必须继续调用 execute_data + render_report
- 若用户附加约束（"不看XX"/"只看XX"），在 search_skill 后追加 clip_outline
- L5 确认等待用户回复后，由系统自动继续生成
