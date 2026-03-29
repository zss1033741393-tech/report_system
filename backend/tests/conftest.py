"""全局 pytest fixtures —— 提供 FastAPI TestClient + 关键 Mock 对象。

所有 app_state 依赖通过 monkeypatch 注入，避免真实的 LLM / Neo4j / Redis / FAISS 调用。
"""
import json
import sys
import os
import asyncio
import tempfile
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# 将 backend/ 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ─── 测试异步模式 ────────────────────────────────────────────────────────────
pytest_plugins = ("pytest_asyncio",)


# ─── 基础服务 fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """会话级 event loop，供异步 fixture 共用。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def chat_history():
    """使用 :memory: SQLite 的 ChatHistoryService，每个测试独立。"""
    from services.chat_history import ChatHistoryService
    svc = ChatHistoryService(db_path=":memory:")
    await svc.init()
    yield svc
    await svc.close()


@pytest.fixture(scope="function")
def memory_storage_dir(tmp_path):
    """临时目录，用于 MemoryStorage。"""
    return str(tmp_path / "memory")


@pytest.fixture(scope="function")
def memory_storage(memory_storage_dir):
    """使用临时目录的 MemoryStorage 实例。"""
    from agent.memory.storage import MemoryStorage
    return MemoryStorage(storage_dir=memory_storage_dir)


@pytest.fixture(scope="function")
def mock_llm():
    """Mock LLMService，默认返回简单对话（无工具调用）。"""
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value={
        "content": "这是测试回答。",
        "tool_calls": [],
        "finish_reason": "stop",
    })
    llm.complete = AsyncMock(return_value="测试摘要内容。")
    llm._parse_json = MagicMock(return_value={"user": {"workContext": {"summary": ""}, "topOfMind": {"summary": ""}}, "facts": []})
    return llm


@pytest.fixture(scope="function")
def mock_skill_registry():
    """Mock SkillRegistry，返回 6 个内置技能的元数据列表。"""
    from agent.skill_registry import SkillMeta, ExecutorMeta
    skills = [
        SkillMeta(name="outline-generate", display_name="大纲生成",
                  description="先检索已沉淀 Skill", enabled=True, source="builtin",
                  executor=ExecutorMeta(module="graph_rag_executor", cls="GraphRAGExecutor",
                                       deps=["llm_service"])),
        SkillMeta(name="outline-clip", display_name="大纲动态裁剪",
                  description="裁剪大纲节点", enabled=True, source="builtin",
                  executor=ExecutorMeta(module="outline_clip_executor", cls="OutlineClipExecutor",
                                       deps=["llm_service"])),
        SkillMeta(name="report-generate", display_name="报告生成",
                  description="渲染 HTML 报告", enabled=True, source="builtin",
                  executor=ExecutorMeta(module="report_writer", cls="ReportWriterExecutor",
                                       deps=["llm_service"])),
        SkillMeta(name="data-execute", display_name="数据执行",
                  description="执行数据绑定", enabled=True, source="builtin",
                  executor=ExecutorMeta(module="data_execute_executor", cls="DataExecuteExecutor",
                                       deps=["session_service"])),
        SkillMeta(name="param-inject", display_name="参数注入",
                  description="注入参数", enabled=True, source="builtin",
                  executor=ExecutorMeta(module="param_inject_executor", cls="ParamInjectExecutor",
                                       deps=["session_service"])),
        SkillMeta(name="skill-factory", display_name="看网能力工厂",
                  description="设计态六步流程", enabled=True, source="builtin",
                  executor=ExecutorMeta(module="skill_factory_executor", cls="SkillFactoryExecutor",
                                       deps=["llm_service"])),
    ]
    reg = MagicMock()
    reg.get_all.return_value = skills
    reg.get = MagicMock(side_effect=lambda name: next((s for s in skills if s.name == name), None))
    return reg


# ─── FastAPI 测试应用 ────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def app_state_fixture(chat_history, memory_storage, mock_llm, mock_skill_registry):
    """组装完整的 app_state，注入各测试 mock。"""
    mock_session_service = MagicMock()
    mock_session_service.redis = AsyncMock()
    mock_session_service.redis.get = AsyncMock(return_value=None)
    mock_faiss = MagicMock()
    mock_faiss.total = 0

    mock_skill_loader = MagicMock()
    mock_skill_loader.get_executor = MagicMock(return_value=None)

    mock_lead_agent = MagicMock()

    async def _mock_handle(session_id, msg):
        yield json.dumps({"type": "chat_reply", "content": "Mock 回答"})
        yield json.dumps({"type": "done"})

    mock_lead_agent.handle_message = _mock_handle

    state = {
        "lead_agent": mock_lead_agent,
        "chat_history": chat_history,
        "llm_service": mock_llm,
        "session_service": mock_session_service,
        "faiss_retriever": mock_faiss,
        "memory_storage": memory_storage,
        "skill_registry": mock_skill_registry,
    }
    return state


@pytest.fixture(scope="function")
def client(app_state_fixture):
    """
    FastAPI TestClient，路由通过 monkeypatch 绑定 app_state。
    使用 httpx.AsyncClient 通过 ASGITransport 调用。
    """
    import importlib
    import main as main_module

    # 注入 mock app_state
    original_state = dict(main_module.app_state)
    main_module.app_state.update(app_state_fixture)

    from fastapi.testclient import TestClient
    # 创建不执行 lifespan 的测试 app
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from routers.chat import router as chat_router
    from routers.memory import router as memory_router
    from routers.skills import router as skills_router

    test_app = FastAPI()
    test_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    test_app.include_router(chat_router)
    test_app.include_router(memory_router)
    test_app.include_router(skills_router)

    @test_app.get("/health")
    def health():
        fr = main_module.app_state.get("faiss_retriever")
        return {"status": "ok", "version": "3.1.0", "faiss_vectors": fr.total if fr else 0}

    with TestClient(test_app, raise_server_exceptions=True) as c:
        yield c

    # 恢复原始 app_state
    main_module.app_state.clear()
    main_module.app_state.update(original_state)


# ─── SSE 解析工具 ─────────────────────────────────────────────────────────────

def parse_sse_events(raw: bytes) -> list[dict]:
    """将 SSE 响应体解析为事件列表。"""
    events = []
    for line in raw.decode("utf-8").split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events
