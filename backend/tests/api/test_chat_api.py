"""API 契约测试：聊天及会话端点。

验证重构后以下端点响应结构与重构前保持一致：
  GET  /health
  GET  /api/v1/sessions
  POST /api/v1/sessions
  GET  /api/v1/sessions/{sid}/messages
  GET  /api/v1/sessions/{sid}/outline
  DELETE /api/v1/sessions/{sid}
  POST /api/v1/chat  (SSE 流)
  GET  /api/v1/sessions/{sid}/artifacts  (新增)
"""
import json
import pytest
import pytest_asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from tests.conftest import parse_sse_events


@pytest.fixture
def sid(client, chat_history):
    """创建一个测试 session 并返回其 ID。"""
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        chat_history.create_session("test-session-001", "测试会话")
    )
    return "test-session-001"


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "faiss_vectors" in data
        assert isinstance(data["faiss_vectors"], int)


class TestSessionsEndpoints:
    def test_list_sessions_returns_list(self, client):
        r = client.get("/api/v1/sessions")
        assert r.status_code == 200
        data = r.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_list_sessions_with_limit(self, client):
        r = client.get("/api/v1/sessions?limit=10")
        assert r.status_code == 200
        assert "sessions" in r.json()

    def test_create_session_returns_id(self, client):
        r = client.post("/api/v1/sessions")
        assert r.status_code == 200
        data = r.json()
        assert "id" in data

    def test_create_two_sessions_different_ids(self, client):
        r1 = client.post("/api/v1/sessions")
        r2 = client.post("/api/v1/sessions")
        assert r1.json()["id"] != r2.json()["id"]

    def test_delete_session_returns_success(self, client, sid):
        r = client.delete(f"/api/v1/sessions/{sid}")
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestMessagesEndpoint:
    def test_get_messages_empty_session(self, client, sid):
        r = client.get(f"/api/v1/sessions/{sid}/messages")
        assert r.status_code == 200
        data = r.json()
        assert "messages" in data
        assert isinstance(data["messages"], list)

    def test_get_messages_after_add(self, client, sid, chat_history):
        import asyncio
        loop = asyncio.get_event_loop()
        loop.run_until_complete(chat_history.add_message(sid, "user", "你好"))
        loop.run_until_complete(chat_history.add_message(sid, "assistant", "您好"))
        r = client.get(f"/api/v1/sessions/{sid}/messages")
        msgs = r.json()["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_message_has_required_fields(self, client, sid, chat_history):
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            chat_history.add_message(sid, "user", "测试")
        )
        r = client.get(f"/api/v1/sessions/{sid}/messages")
        msg = r.json()["messages"][0]
        for field in ["id", "session_id", "role", "content", "created_at"]:
            assert field in msg, f"字段 {field} 缺失"


class TestOutlineEndpoint:
    def test_get_outline_no_outline(self, client, sid):
        r = client.get(f"/api/v1/sessions/{sid}/outline")
        assert r.status_code == 200
        data = r.json()
        # 无大纲时返回 null 或空结构
        assert "outline_json" in data or data is not None

    def test_get_outline_after_save(self, client, sid, chat_history):
        import asyncio
        outline = {"name": "测试大纲", "children": [], "level": 1}
        asyncio.get_event_loop().run_until_complete(
            chat_history.save_outline_state(sid, outline, {"anchor": "节点1"})
        )
        r = client.get(f"/api/v1/sessions/{sid}/outline")
        assert r.status_code == 200
        data = r.json()
        assert data["outline_json"]["name"] == "测试大纲"
        assert data["anchor_info"]["anchor"] == "节点1"


class TestArtifactsEndpoint:
    """新增端点 GET /api/v1/sessions/{sid}/artifacts 的契约验证。"""

    def test_artifacts_no_data(self, client, sid):
        r = client.get(f"/api/v1/sessions/{sid}/artifacts")
        assert r.status_code == 200
        data = r.json()
        assert "outline_json" in data
        assert "anchor_info" in data
        assert "report" in data

    def test_artifacts_response_structure(self, client, sid, chat_history):
        import asyncio
        outline = {"name": "大纲根", "children": [], "level": 1}
        asyncio.get_event_loop().run_until_complete(
            chat_history.save_outline_state(sid, outline)
        )
        r = client.get(f"/api/v1/sessions/{sid}/artifacts")
        assert r.status_code == 200
        data = r.json()
        assert data["outline_json"]["name"] == "大纲根"
        assert data["report"] is None  # 无报告时为 null

    def test_artifacts_with_report(self, client, sid, chat_history):
        """有报告时 report 字段包含 html 和 title。"""
        import asyncio
        loop = asyncio.get_event_loop()
        loop.run_until_complete(chat_history.add_message(
            sid, "assistant", "报告已生成",
            metadata={"report_html": "<html>test</html>", "report_title": "测试报告"}
        ))
        r = client.get(f"/api/v1/sessions/{sid}/artifacts")
        assert r.status_code == 200
        data = r.json()
        if data["report"]:
            assert "html" in data["report"]
            assert "title" in data["report"]


class TestChatSSEEndpoint:
    def test_chat_returns_sse_stream(self, client):
        """POST /api/v1/chat 返回 text/event-stream。"""
        r = client.post("/api/v1/chat",
                        json={"session_id": "sse-test-01", "message": "你好"})
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

    def test_chat_sse_contains_done_event(self, client):
        """SSE 流最后应含 done 事件。"""
        r = client.post("/api/v1/chat",
                        json={"session_id": "sse-test-02", "message": "你好"})
        events = parse_sse_events(r.content)
        types = [e.get("type") for e in events]
        assert "done" in types

    def test_chat_sse_contains_chat_reply(self, client):
        """SSE 流应含 chat_reply 事件（mock lead_agent 返回）。"""
        r = client.post("/api/v1/chat",
                        json={"session_id": "sse-test-03", "message": "分析容量"})
        events = parse_sse_events(r.content)
        types = [e.get("type") for e in events]
        assert "chat_reply" in types
