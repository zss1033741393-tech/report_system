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
    - skill_registry
    - session_service
  config: {}
---

# 看网能力路由（Skill Router）

## 适用场景
用户提出看网分析需求时，优先检索已沉淀的看网能力，通过 LLM 精排返回候选列表，
让用户从中选择，或直接进入 GraphRAG 流程。

## 工作流：skill_router(query)

**Step 1：扫描自定义 Skill 目录**
遍历 `skills/custom/` 下所有有效 Skill 目录，读取元数据。

**Step 2：加载 Skill 元数据**
读取每个 Skill 的 SKILL.md frontmatter + references/query_variants.txt + 看网逻辑摘要。

**Step 3：LLM 精排**
将用户 query 和所有 Skill 元数据发给 LLM，返回匹配的 Skill ID 列表（最多 5 个）。

**Step 4：构建候选列表**
将匹配 Skill 的展示信息（display_name、scene_intro、keywords、skill_dir）组装成候选项。

**Step 5：推送 SSE + 保存 Redis**
发送 `skill_candidates` 事件到前端，同时将候选列表保存到 Redis（TTL=300s）。

## 关键规则
- 若无已沉淀 Skill 或 LLM 精排无匹配，直接返回空候选列表
- LeadAgent 在下一轮消息中读取 Redis 中的候选列表，拦截用户选择
- 用户选择后由 LeadAgent 直接加载对应 Skill 大纲，不再调用 search_skill
