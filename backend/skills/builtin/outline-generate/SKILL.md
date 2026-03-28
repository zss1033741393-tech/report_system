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

# 大纲生成与运行态操作

## 适用场景
用户提出网络分析需求（如"分析 fgOTN 容量"、"评估政企 OTN 机会点"），需要生成评估大纲。
也适用于对已有大纲进行裁剪（删除节点）或修改后重新生成报告。

## 工作流

### 场景 A：首次生成大纲
1. `search_skill(session_id, query)` — 优先检索已沉淀能力；命中则直接加载，未命中走 GraphRAG
2. （可选）`clip_outline(session_id, instruction)` — 按用户指令删除/保留节点
3. （可选）`inject_params(session_id, param_updates)` — 注入行业/阈值等过滤条件
4. `execute_data(session_id)` — 执行 L5 节点数据查询
5. `render_report(session_id)` — 渲染 HTML 报告

### 场景 B：修改已有大纲后刷新报告
1. `get_current_outline(session_id)` — 确认当前大纲结构
2. `clip_outline` 或 `inject_params`
3. `execute_data(session_id)` + `render_report(session_id)` （有报告时必须）

## 关键规则
- 先调用 `get_session_status` 确认是否已有大纲，避免重复生成
- 用户说"不看XX"/"删除XX"/"去掉XX" → 调用 clip_outline
- 用户说"只看XX行业"/"阈值改为XX" → 调用 inject_params
- 裁剪/注入后如果 has_report=true，**必须**追加 execute_data + render_report
