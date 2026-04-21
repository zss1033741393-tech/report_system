---
name: skill-router
display_name: 看网能力路由
description: 检索已沉淀的看网能力，通过 LLM 精排返回候选列表供用户选择。用户提出看网分析需求时首先调用。
enabled: true
params:
  query:
    type: string
    required: true
    description: 用户的分析需求描述
paradigm: Tool Wrapper
executor:
  module: skill_router_executor
  class: SkillRouterExecutor
  deps:
    - outline_store
    - session_service
  config: {}
---

# 看网能力路由（Skill Router）

## 适用场景
用户提出看网分析需求时，优先检索已沉淀的看网能力，返回候选列表让用户选择，
或在无匹配时直接进入 GraphRAG 流程。

## Metadata
- **paradigm**: Tool Wrapper（LLM 精排在 tool 层完成，executor 只做纯算法）
- **when_to_use**: 用户提出看网分析需求时，通过 `skill_router` 工具调用
- **inputs**: query（用户需求）、matched_ids（tool 层 LLM 预计算的精排结果）
- **outputs**: candidates（候选能力列表）

## When to Use
- ✅ 用户提出看网分析需求，需检索已有能力
- ❌ 已明确选择某个 Skill 后（直接加载大纲）

## How to Use

> LLM 精排在 **tool 层**（`tool_definitions._skill_router`）完成，executor 只做纯算法。

**Step 1（executor）**：查询 outlines 表，获取 status IN ('active','approved') 的记录，构建元数据列表
**Step 2（tool 层 LLM）**：`_llm_route_skills(query, skill_metas)` → matched_ids（最多 5 个）
**Step 3（executor）**：接收 `params.matched_ids`，构建候选列表，推送 SSE + 保存 Redis

## References
- `references/router_system_prompt.md` — 精排 LLM system prompt

## 关键规则
- 若无已沉淀 Skill 或 LLM 精排无匹配，直接返回空候选列表
- LeadAgent 在下一轮消息中读取 Redis 中的候选列表，拦截用户选择
- 用户选择后由 LeadAgent 直接加载对应 Skill 大纲，不再调用 search_skill
