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

# 看网能力工厂（元技能）

## 三种模式
- full: 完整六步 + 等待确认 + 沉淀
- preview_only: 前五步（到报告预览），完成后提示是否沉淀
- persist_only: 仅第六步（从 Redis 取缓存 context 执行沉淀）

## Sub-Skills（内部私有）
1. intent-understand: 意图理解与泛化
2. struct-extract: 信息提取与结构化
3. outline-design: 生成可执行大纲
4. data-binding: 数据源绑定
5. report-preview: 报告预览
6. skill-persist: 能力沉淀

## Scripts
- scripts/skill_factory_executor.py
- scripts/sub_skills/intent_understand.py
- scripts/sub_skills/struct_extract.py
- scripts/sub_skills/outline_design.py
- scripts/sub_skills/data_binding.py
- scripts/sub_skills/report_preview.py
- scripts/sub_skills/skill_persist.py
