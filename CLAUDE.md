# 看网报告系统 — 项目规范

## 项目目标

本系统的目标是打造一套智能化的**看网（网络评估与洞察）报告生成系统**，包含两大核心能力机制，分别服务于业务专家与看网用户：

**设计态（看网方案设计与沉淀）**
允许专家输入自然语言形式的"看网逻辑"，系统自动将其结构化，并沉淀为可复用的报告生成大纲及执行逻辑（Skills）。

**运行态（智能问答与动态生成）**
允许看网用户通过自然语言提问。系统精准复用设计态沉淀的报告能力，或根据用户的特定约束（如指定行业、删减指标、修改阈值）动态调整生成逻辑，实时输出定制化的看网报告。

---

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
│   │   ├── tool_definitions.py # 工具 schema + 函数（search_skill / inject_params 等）
│   │   ├── loop_detector.py    # 循环检测（warn/stop）
│   │   └── context_compressor.py # 长上下文压缩
│   ├── llm/            # LLMService（流式 + function calling）
│   ├── pipeline/       # FAISSRetriever, Neo4jRetriever
│   ├── services/       # ChatHistoryService, SessionService, EmbeddingService
│   ├── skills/
│   │   ├── builtin/    # 内置技能（outline-generate / param-inject / skill-factory 等）
│   │   │   └── */scripts/  # 各技能执行器（GraphRAGExecutor / SkillFactoryExecutor 等）
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
        ├── components/ # Vue 组件（AnchorConfirm / RightPanel 等）
        ├── composables/ # useConversation 等
        ├── utils/sse.js # SSE 事件处理 + API 封装
        └── views/      # MainView / OutlineView 等页面
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
chat_reply, thinking_step, thinking_complete,
tool_call, tool_result,
outline_chunk, outline_done, outline_updated, outline_clipped,
report_chunk, report_done,
design_step, persist_prompt, skill_persisted, skill_factory_done,
data_executing, data_executed,
awaiting_confirm, confirm_required,
error, done
```

## 开发规范

### 代码风格

**Python**
- 遵循 PEP8，使用 `async/await`，类型注解可选但建议
- 注释用中文，复杂逻辑才加注释

**Vue / JavaScript**
- Composition API + `<script setup>`，composable 按功能拆分
- 每个 `ref` / `const` / `let` 独占一行，禁止逗号连写多个声明
- 每条语句独占一行，禁止用分号将多条语句堆在同一行
- 运算符、关键字前后保留空格：`a === b`、`if (x)`、`{ key: val }`
- Template 中每个组件属性独占一行（超过 1 个属性时）
- CSS 每条规则独占一行，禁止将多条声明写在同一行（如 `.cls{a:1;b:2;c:3}`）
- 数组 / 对象字面量超过 2 项时换行书写

### 测试规范
- 框架：`pytest` + `pytest-asyncio`（asyncio_mode = auto）
- 测试目录：`backend/tests/`（unit / integration / api 三层）
- 原则：零真实外部依赖（no real LLM / no real DB）
  - LLM → `FakeLLMService`（轮次预设 chunks，见 `tests/conftest.py`）
  - DB → `tmp_path` SQLite / monkeypatch
  - Executor → `AsyncMock` 或自定义 fake
- 运行：`cd backend && pytest tests/ -v`

### Git 规范
- 开发分支：`claude/configure-git-pat-02FTx`
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
