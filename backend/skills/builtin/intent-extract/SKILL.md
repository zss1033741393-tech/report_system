---
name: intent-extract
display_name: 意图提取与双路径检索
description: 分析专家输入的看网逻辑文本，提取结构化意图，执行双路径检索（路径A自顶向下/路径B自底向上），输出检索结果供大纲设计使用。替代原 skill-factory 的 Step1+Step2。
enabled: true
params:
  expert_input:
    type: string
    required: true
    description: 专家输入的看网逻辑原文（>80字）
executor:
  module: intent_extract_executor
  class: IntentExtractExecutor
  deps:
    - llm_service
    - embedding_service
    - faiss_retriever
    - neo4j_retriever
    - session_service
    - kb_store
  config:
    top_k: 20
    score_threshold: 0.3
    l14_confidence_threshold: 0.7
---

# 意图提取与双路径检索

## 适用场景
用户输入超过 80 字的看网逻辑描述时，由 `extract_intent` 工具调用此技能。

## 工作流

### Step 1：意图提取（LLM）
分析用户看网逻辑，提取：
- `scene_intro`：50字以内场景简介
- `keywords`：3-5个关键词
- `query_variants`：3种触发问法
- `skill_name`：英文下划线格式技能名

### Step 2：语义检索（算法）
1. 将 scene_intro + keywords 拼接为检索文本，向量化
2. FAISS 搜索，top_k=20，threshold=0.3
3. Neo4j 获取候选节点祖先路径

### Step 3：路径判断（算法，无 LLM）
- **路径 A（自顶向下）**：候选中存在 L1~L4 score > 0.7 的高置信度命中
  - 取最高分 L1~L4 节点作为锚点，拉取子树
- **路径 B（自底向上）**：仅命中 L5 指标节点（L1~L4 score 均 < 0.7）
  - 收集所有 L5 候选，从 KBContentStore 加载 expand_logic/chapter_template

### 输出
```json
{
  "path": "top_down" | "bottom_up" | "no_match",
  "intent": { "scene_intro": "", "keywords": [], "query_variants": [], "skill_name": "" },
  "top_down": { "anchor": {}, "subtree": {} },
  "bottom_up": { "indicators": [], "kb_contents": {}, "existing_l3l4": [] }
}
```
