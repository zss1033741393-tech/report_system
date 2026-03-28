---
name: skill-factory
display_name: 看网能力工厂
description: 元技能，封装设计态六步流程（意图理解→信息提取→大纲生成→数据绑定→报告预览→能力沉淀），支持 full/preview_only/persist_only 三种模式
enabled: true
params:
  mode:
    type: string
    required: false
    description: 执行模式（full/preview_only/persist_only），默认 full
  expert_input:
    type: string
    required: false
    description: 专家输入的看网逻辑文本（full/preview_only 模式必填）
  saved_context:
    type: string
    required: false
    description: 缓存的 context key（persist_only 模式必填）
executor:
  module: skill_factory_executor
  class: SkillFactoryExecutor
  deps:
    - llm_service
    - embedding_service
    - faiss_retriever
    - neo4j_retriever
    - outline_renderer
    - session_service
    - kb_store
---

# 看网能力工厂（设计态六步流程）

## 适用场景
用户输入了超过 80 字的自然语言看网逻辑描述，希望系统将其结构化并沉淀为可复用能力。
典型触发词：用户粘贴了一大段业务分析逻辑、说"帮我把这段逻辑沉淀下来"、"从这段描述生成看网能力"。

## 工作流（严格按序调用工具）

**第 1 步：** `understand_intent(session_id, expert_input)`
→ 理解专家逻辑，提取场景简介、关键词、问法变体

**第 2 步：** `extract_structure(session_id, raw_input)`
→ 将逻辑文本映射为五层知识架构（场景→维度→指标→子指标→评估点）

**第 3 步：** `design_outline(session_id, structured_text)`
→ 生成可执行大纲 JSON，并为 L5 节点绑定数据源

**第 4 步：** `preview_report(session_id)`
→ 执行数据并渲染预览报告，供用户验证逻辑正确性

**第 5 步：等待用户确认**
→ 向用户展示预览结果，询问是否满意并保存

**第 6 步（仅在用户明确确认后）：** `persist_skill(session_id, context_key)`
→ 将设计态成果写入 skills/custom/ 成为可复用能力

## 关键规则
- 第 1-4 步严格顺序执行，每步等待结果后再继续
- **persist_skill 绝对不能在用户未明确确认（"保存"/"沉淀"/"好的，保存"）前调用**
- 若第 3 步（design_outline）失败，说明知识库中哪些节点无法匹配，请求用户调整描述
- 若用户已有缓存的设计态上下文（get_session_status 返回 has_cached_context=true），可直接调用 persist_skill
