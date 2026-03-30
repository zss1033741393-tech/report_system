# 看网报告系统 — 项目规范

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11, FastAPI, SQLite (aioSQLite), Redis |
| LLM | OpenAI-compatible API (Qwen3, function calling) |
| 图数据库 | Neo4j (网络知识图谱) |
| 向量搜索 | FAISS |
| 前端 | Vue 3 (Composition API), Vite, SSE |

## 目录结构

```
report_system/
├── backend/
│   ├── agent/          # ReAct 引擎、工具注册、Memory、循环检测
│   │   ├── memory/     # MemoryStore / MemoryQueue / MemoryUpdater
│   │   ├── middleware/ # HistoryMiddleware / OutlineStateMiddleware
│   │   ├── lead_agent.py       # 入口：构建 prompt + 调 ReAct 引擎
│   │   ├── react_engine.py     # SimpleReActEngine：LLM 自驱工具调用循环
│   │   ├── tool_registry.py    # 工具注册 / 执行
│   │   ├── tool_definitions.py # 12 个工具 schema + 函数
│   │   ├── loop_detector.py    # 循环检测（warn/stop）
│   │   └── context_compressor.py # 长上下文压缩
│   ├── llm/            # LLMService（流式 + function calling）
│   ├── pipeline/       # FAISSRetriever, Neo4jRetriever
│   ├── services/       # ChatHistoryService, SessionService, EmbeddingService
│   ├── skills/
│   │   ├── builtin/    # 内置技能（每个目录含 SKILL.md + scripts/）
│   │   └── custom/     # 用户自定义技能（Git 忽略）
│   ├── routers/        # FastAPI 路由：chat / skills / memory
│   ├── tests/          # 所有测试（pytest），在 backend/ 下
│   │   ├── conftest.py
│   │   ├── unit/
│   │   ├── integration/
│   │   └── api/
│   ├── main.py         # FastAPI 入口，lifespan 初始化
│   └── config.py       # Settings（pydantic BaseSettings）
└── frontend/
    └── src/
        ├── components/ # Vue 组件
        ├── composables/ # useConversation 等
        ├── utils/sse.js # SSE 事件处理 + API 封装
        └── views/      # MainView 等页面
```

## 核心架构规范

### 技能（Skill）规范
- 每个技能目录必须含 `SKILL.md`（YAML frontmatter + 工作流正文）
- Executor 放在 `scripts/` 子目录，实现 `async def execute(ctx) -> AsyncGenerator`
- SKILL.md body 是 LLM 可读的工作流指导，供 `read_skill_file` 工具读取

### 工具（Tool）规范
- 工具函数签名：`async def fn(args: dict, tool_ctx: ToolContext) -> AsyncGenerator[dict, None]`
- `yield {"sse": str}` → 透传 SSE 事件给前端
- `yield {"result": SkillResult}` → 工具执行结果（最后一次 yield）
- 工具通过 `ToolRegistry.register()` 注册，统一由 `register_all_tools()` 在启动时调用

### SSE 事件规范
已有事件类型，**只能新增，不可重命名/删除**：
```
chat_reply, thinking_step, outline_chunk, outline_done,
report_chunk, report_done, data_executing, data_done,
error, done, tool_call, tool_result
```

### 不变边界（严禁修改）
```
backend/skills/builtin/*/scripts/*.py
backend/services/chat_history.py
backend/services/data/
backend/agent/skill_registry.py
backend/agent/context.py
backend/agent/skill_loader.py
```

## 开发规范

### 代码风格
- Python：遵循 PEP8，使用 `async/await`，类型注解可选但建议
- Vue：Composition API + `<script setup>`，composable 按功能拆分
- 注释：中文（项目面向中文用户），复杂逻辑才加注释

### 测试规范
- 框架：`pytest` + `pytest-asyncio`（asyncio_mode = auto）
- 测试目录：`backend/tests/`（unit / integration / api 三层）
- 原则：零真实外部依赖（no real LLM / no real DB）
  - LLM → `FakeLLMService`（轮次预设 chunks，见 `tests/conftest.py`）
  - DB → `tmp_path` SQLite / monkeypatch
  - Executor → `AsyncMock` 或自定义 fake
- 运行：`cd backend && pytest tests/ -v`

### Git 规范
- 开发分支：`claude/add-github-copilot-mcp-zLgYT`
- 提交信息：中文描述，简明扼要
- **push 规则（重要）**：
  - 必须使用 `git push -u origin <branch>` 通过 PAT URL 直接推送
  - `origin` remote 已设置为 PAT URL：`https://zss1033741393-tech:<PAT>@github.com/zss1033741393-tech/report_system.git`
  - **严禁使用 GitHub MCP Server 工具（mcp__github__push_files 等）提交代码**，速度极慢
  - 如果 `git push origin` 失败，检查 remote URL 是否仍为 PAT URL（`git remote get-url origin`）
  - 推送后执行 `git fetch origin <branch>:refs/remotes/origin/<branch>` 同步本地跟踪引用，避免 stop-hook 误报
- 禁止 --force 到 main/master

## 关键依赖

```bash
# 后端核心
fastapi, uvicorn, aiohttp, aiosqlite, redis, faiss-cpu, neo4j

# 测试
pytest>=8.0, pytest-asyncio>=0.23
```

## 本地运行

```bash
# 后端
cd backend
uvicorn main:app --reload --port 8000

# 前端
cd frontend
npm install && npm run dev

# 测试
cd backend
pytest tests/ -v
```
