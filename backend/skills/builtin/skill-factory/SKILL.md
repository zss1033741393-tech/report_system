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

用户输入了超过 80 字的自然语言看网逻辑描述，希望系统将其结构化并沉淀为可复用的看网能力。

触发信号：用户描述了一套完整的分析思路，包含场景、指标、判断逻辑等要素。

## 工作流（按序调用工具）

```
1. understand_intent(expert_input)
   → 提取场景简介、触发关键词、用户问法变体
   → 结果注入 session 上下文

2. extract_structure(raw_input)
   → 将看网逻辑格式化为结构化 Markdown
   → 映射五层知识架构（场景→维度→指标→子指标→评估点）

3. design_outline()
   → 基于结构化文本生成五层大纲 JSON
   → 大纲保存到当前会话

4. bind_data()
   → 为大纲底层评估指标节点绑定数据源（SQL/API/Mock）

5. preview_report()
   → 生成预览版报告 HTML，供用户确认
   → 完成后等待用户确认

6. [等待用户明确说"保存/沉淀/确认"] → persist_skill(context_key)
   → 将设计态成果写入知识库，成为可复用能力
```

## 关键规则

- 步骤 1-5 按序执行，每步等待结果后再执行下一步
- **步骤 6（persist_skill）必须等用户明确说"保存/沉淀/确认"才执行，不得自动触发**
- design_outline 失败时，说明知识库中哪些节点无法匹配，请用户补充信息
- 整个流程是独立入口，不与运行态步骤（clip_outline/execute_data 等）组合使用

## 三种执行模式

| 模式 | 含义 | 触发条件 |
|------|------|---------|
| preview_only | 执行步骤 1-5，预览后等待确认 | 用户输入长文本但未明确要沉淀 |
| full | 执行步骤 1-6，全流程 | 用户明确表示要沉淀 |
| persist_only | 仅执行步骤 6 | 用户说"保存/沉淀"且已有预览缓存 |
