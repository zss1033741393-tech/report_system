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
paradigm: Pipeline
executor:
  module: intent_extract_executor
  class: IntentExtractExecutor
  deps:
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

## Metadata
- **paradigm**: Pipeline（Step1 由 tool 层 LLM 完成，Step2~3 由 executor 纯算法完成）
- **when_to_use**: 专家输入超过 80 字的看网逻辑，由 `extract_intent` 工具调用
- **inputs**: expert_input（原文）、intent（tool 层 LLM 预计算，含 scene_intro/keywords/...）
- **outputs**: path（top_down/bottom_up/no_match）、intent、top_down 或 bottom_up 数据

## When to Use
- ✅ 用户输入超过 80 字的设计态看网逻辑描述
- ❌ 运行态用户查询（使用 search_skill / skill_router）

## How to Use

> Step 1 LLM 意图提取在 **tool 层**（`tool_definitions._llm_extract_intent`）完成。

**Step 1（tool 层 LLM）**：`_llm_extract_intent(expert_input)` → intent JSON
**Step 2（executor 算法）**：Embedding + FAISS 检索，top_k=20, threshold=0.3
**Step 3（executor 算法）**：Neo4j 祖先路径 → 纯算法路径判断（score_threshold=0.7）

## References
- `references/intent_prompt.md` — 意图提取 LLM prompt

## 输出格式
```json
{
  "path": "top_down" | "bottom_up" | "no_match",
  "intent": { "scene_intro": "", "keywords": [], "query_variants": [], "skill_name": "" },
  "top_down": { "anchor": {}, "subtree": {} },
  "bottom_up": { "indicators": [], "kb_contents": {}, "existing_l3l4": [] }
}
```
