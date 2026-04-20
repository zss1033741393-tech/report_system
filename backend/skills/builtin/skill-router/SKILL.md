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
executor:
  module: skill_router_executor
  class: SkillRouterExecutor
  deps:
    - llm_service
    - outline_store
    - session_service
  config: {}
---

# 看网能力路由（Skill Router）

## 适用场景
用户提出看网分析需求时，优先检索已沉淀的看网能力，通过 LLM 精排返回候选列表，
让用户从中选择，或直接进入 GraphRAG 流程。

## 工作流：skill_router(query)

**Step 1：查询 outlines 表**
调用 `outline_store.list_active_outlines_for_router()` 获取 status IN ('active','approved') 的大纲记录。

**Step 2：构建元数据列表**
从 DB 记录中提取 skill_name、display_name、scene_intro、keywords、query_variants。

**Step 3：LLM 精排**
将用户 query 和所有元数据发给 LLM，返回匹配的 Skill ID 列表（最多 5 个）。

**Step 4：构建候选列表**
将匹配 Skill 的展示信息（display_name、scene_intro、keywords、outline_id）组装成候选项。

**Step 5：推送 SSE + 保存 Redis**
发送 `skill_candidates` 事件到前端，同时将候选列表保存到 Redis（TTL=300s）。

## 关键规则
- 若无已沉淀 Skill 或 LLM 精排无匹配，直接返回空候选列表
- LeadAgent 在下一轮消息中读取 Redis 中的候选列表，拦截用户选择
- 用户选择后由 LeadAgent 直接加载对应 Skill 大纲，不再调用 search_skill
