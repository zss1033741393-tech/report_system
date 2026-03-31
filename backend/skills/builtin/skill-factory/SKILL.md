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
    - indicator_resolver
---

# 看网能力工厂（设计态六步工作流）

## 适用场景
用户输入了超过 80 字的自然语言看网逻辑描述，希望将其结构化并固化为可复用的分析能力。

## 工具调用顺序（严格按序执行）

### 第一步：understand_intent(expert_input)
理解专家输入的看网逻辑，提取：
- scene_intro：50字以内的场景简介
- keywords：3-5个关键词
- query_variants：3种用户可能的问法变体
- skill_name：英文下划线格式的技能名称

### 第二步：extract_structure(expert_input)
将看网逻辑格式化为五层知识场景架构的结构化文本：
- L1 场景（如 政企OTN升级）
- L2 子场景（如 fgOTN部署）
- L3 评估维度（如 传送企业价值分析、传送网络容量分析）
- L4 评估项（如 企业分布分析、站点设备低阶交叉资源分析）
- L5 评估指标（如 潜在安全需求企业安全等级分布）→ 对应具体 API/SQL 数据调用

### 第三步：design_outline(expert_input)
基于结构化文本生成可执行大纲 JSON（五层树形结构）。
若知识库中某些节点无法匹配，说明缺失节点并继续设计可用的部分。

### 第四步：bind_data(expert_input)
为大纲底层 L5 指标节点绑定数据源（SQL/API/Mock）。
每个 L5 节点需指定：data_type, source_type, query_template, display_config。

### 第五步：preview_report(expert_input)
生成预览版报告 HTML，向用户展示最终效果。
预览完成后，必须向用户发送如下确认消息："报告预览已完成，是否将此看网能力保存为可复用能力？请回复"保存"或"不保存"。"
然后等待用户回复，不得自动执行第六步。

### 第六步：persist_skill(context_key)
【严格禁止自动执行】此步骤只能在以下条件同时满足时才调用：
1. 用户在第五步预览后明确回复了"保存"/"沉淀"/"确认保存"等肯定指令
2. 不得因"流程"或"默认行为"自动触发

将设计态成果写入系统：SKILL.md + outline.json + bindings.json + Neo4j + FAISS。

## 关键规则
- 步骤 1-5 自动按序执行，每步等待结果后再执行下一步
- 步骤 5 完成后必须停下来询问用户，等待明确确认后才能执行步骤 6
- 步骤 6 绝不自动执行，即使流程已走到第五步也不例外
- design_outline 失败时说明知识库中哪些节点无法匹配，继续处理可用部分
- 整个流程中保持 expert_input 一致（作为各步骤的上下文参考）
