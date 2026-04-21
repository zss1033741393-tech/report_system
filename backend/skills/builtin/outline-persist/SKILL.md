---
name: outline-persist
display_name: 大纲沉淀
description: 将设计态大纲沉淀到数据库（outlines/outline_nodes/node_bindings 三张表）。替代原 skill-factory 的 SkillPersist。user_defined 节点写为 draft 状态，待审核通过后写入 Neo4j。
enabled: true
params:
  context_key:
    type: string
    required: false
    description: Redis 缓存 key（通常为 session_id），用于恢复 intent-extract 产出的上下文
paradigm: Generator
executor:
  module: outline_persist_executor
  class: OutlinePersistExecutor
  deps:
    - outline_store
    - session_service
    - neo4j_retriever
    - faiss_retriever
    - embedding_service
---

# 大纲沉淀（DB 存储）

## 适用场景
用户在设计态完成大纲预览后，明确说"保存/沉淀"时，由 `persist_outline` 工具调用此技能。

## 沉淀流程

### Step 1：写 outlines 表（元数据）
记录 skill_name、scene_intro、keywords、query_variants、raw_input，status=draft。

### Step 2：写 outline_nodes 表（节点树）
- L5（kb 节点）：neo4j_node_id 指向 Neo4j 已有节点，status=approved
- L2~L4（kb 节点）：同上
- L2~L4（user_defined 节点）：status=draft，等待审核

### Step 3：写 node_bindings 表（数据绑定）
- 每个 L5 节点（UNIQUE 约束），跨场景复用
- paragraph_template 来自大纲节点的 paragraph 字段

### Step 4：更新 FAISS 索引
将 scene_intro + keywords 向量化，写入 FAISS（供 skill-router 检索）。

### 审核后（由 review 接口触发）
- user_defined 节点 draft → approved
- 写入 Neo4j 知识图谱

## 注意
- 沉淀完成后发送 skill_persisted SSE 事件
- 不再写文件系统（skills/custom/ 目录），改为 DB 存储
