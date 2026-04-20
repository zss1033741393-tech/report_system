# 看网报告系统 (report_system)

智能化的看网（网络评估与洞察）报告生成系统，支持**设计态**（专家沉淀看网能力）与**运行态**（用户动态生成报告）两大核心模式。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11, FastAPI, SQLite (aioSQLite), Redis |
| LLM | OpenAI-compatible API (Qwen3, function calling) |
| 图数据库 | Neo4j（网络知识图谱，L1→L5 层级）|
| 向量搜索 | FAISS |
| 前端 | Vue 3 (Composition API), Vite, SSE |

---

## 目录结构

```
report_system/
├── backend/
│   ├── agent/                  # ReAct 引擎、工具注册、Memory
│   ├── llm/                    # LLMService（流式 + function calling）
│   ├── pipeline/               # FAISSRetriever, Neo4jRetriever
│   ├── services/
│   │   ├── outline_store.py    # 三张 DB 表（outlines/outline_nodes/node_bindings）
│   │   ├── review_service.py   # 审核流程（draft→approved→Neo4j）
│   │   └── ...
│   ├── skills/builtin/
│   │   ├── intent-extract/     # 意图提取 + 双路径检索（Step1 LLM + Step2 纯算法）
│   │   ├── outline-generate/   # 大纲生成（路径A 自顶向下 + 路径B 自底向上）
│   │   ├── outline-persist/    # 大纲沉淀到 DB 三张表
│   │   ├── skill-router/       # 已沉淀能力路由（查 outlines 表 + LLM 精排）
│   │   ├── param-inject/       # 运行时参数注入
│   │   ├── data-execute/       # 数据查询执行
│   │   ├── report-generate/    # 报告生成
│   │   └── report-modify/      # 报告修改
│   ├── routers/
│   │   ├── chat.py             # 对话接口
│   │   ├── review.py           # 审核接口（approve/reject）
│   │   └── ...
│   ├── vendor/report_sdk/      # 全局服务客户端（Neo4j/FAISS/KB/Embedding/OutlineDB）
│   ├── main.py                 # FastAPI 入口
│   └── tests/                  # pytest 测试
└── frontend/
    └── src/                    # Vue 3 前端
```

---

## 核心架构

### 设计态流程（v2，2 次 LLM 调用）

```
专家输入看网逻辑
    ↓
extract_intent（意图提取 + 双路径检索）
    ├─ Step1: LLM 提取 scene_intro/keywords/skill_name
    └─ Step2: 纯算法 FAISS 检索 → 路径判断
         ├─ 路径A（命中 L1~L4）→ 自顶向下，直接返回子树大纲
         └─ 路径B（仅命中 L5）→ 自底向上，LLM 自由组织 L2~L4 结构
    ↓
用户确认是否保存（persist_prompt SSE）
    ↓
persist_outline（沉淀到 DB 三张表）
    ├─ outlines：元数据（skill_name, scene_intro, keywords, query_variants）
    ├─ outline_nodes：节点树（kb 节点=approved，user_defined=draft）
    └─ node_bindings：L5 数据绑定（UNIQUE 约束，跨场景复用）
    ↓
审核流程（user_defined 节点）
    POST /api/outlines/{id}/approve → 写入 Neo4j，状态改为 active
    POST /api/outlines/{id}/reject  → 状态改为 rejected
```

### 存储层（三张 DB 表）

| 表 | 说明 |
|----|------|
| `outlines` | 大纲元数据，status: draft→pending_review→active/rejected |
| `outline_nodes` | 大纲节点树，source: kb（approved）/ user_defined（需审核）|
| `node_bindings` | L5 节点数据绑定，UNIQUE(node_id) 保证跨场景复用 |

### 审核 API

```
GET  /api/outlines/pending           # 列出待审核大纲
GET  /api/outlines/pending/nodes     # 列出待审核节点
POST /api/outlines/{id}/approve      # 审核通过（写 Neo4j）
POST /api/outlines/{id}/reject       # 拒绝
POST /api/outlines/nodes/{id}/approve # 单节点审核通过
```

---

## 快速开始

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 前端
cd frontend
npm install && npm run dev

# 测试
cd backend
pytest tests/ -v
```

---

## 开发分支

- 主开发分支：`dev_skill`
- 架构重构版本：v2（2025-04）
  - 将 skill-factory 拆分为 intent-extract / outline-generate / outline-persist 三个独立 Skill
  - 存储从文件系统改为 SQLite DB 三张表
  - 设计态 LLM 调用从 3~4 次降为 2 次
  - 新增双路径匹配（路径A 自顶向下 / 路径B 自底向上）
  - 新增 user_defined 节点审核流程
