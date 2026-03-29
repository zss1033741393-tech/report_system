"""API 契约测试：Memory 端点（Phase 2 新增）。

验证：
  GET    /api/v1/memory/{session_id}  → 返回记忆结构
  DELETE /api/v1/memory/{session_id}  → 清除记忆
"""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


class TestMemoryGetEndpoint:
    def test_get_memory_empty_session(self, client):
        r = client.get("/api/v1/memory/new-session-xyz")
        assert r.status_code == 200
        data = r.json()
        assert "session_id" in data
        assert "memory" in data

    def test_get_memory_structure(self, client):
        r = client.get("/api/v1/memory/test-mem-001")
        data = r.json()
        mem = data["memory"]
        assert "user" in mem
        assert "workContext" in mem["user"]
        assert "topOfMind" in mem["user"]
        assert "facts" in mem

    def test_get_memory_after_save(self, client, memory_storage):
        """storage 中有数据时，API 返回正确内容。"""
        memory_storage.save("saved-session", {
            "user": {
                "workContext": {"summary": "fgOTN 专家"},
                "topOfMind": {"summary": ""},
            },
            "facts": [
                {"content": "不看低阶交叉", "category": "preference", "confidence": 0.9}
            ],
        })
        r = client.get("/api/v1/memory/saved-session")
        assert r.status_code == 200
        data = r.json()
        assert data["memory"]["user"]["workContext"]["summary"] == "fgOTN 专家"
        assert len(data["memory"]["facts"]) == 1

    def test_get_memory_returns_session_id(self, client):
        r = client.get("/api/v1/memory/my-session-id")
        assert r.json()["session_id"] == "my-session-id"


class TestMemoryDeleteEndpoint:
    def test_delete_memory_returns_success(self, client):
        r = client.delete("/api/v1/memory/delete-test-session")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_delete_then_get_empty(self, client, memory_storage):
        """清除后 GET 返回空 facts。"""
        memory_storage.save("to-delete", {
            "user": {"workContext": {"summary": "X"}, "topOfMind": {"summary": ""}},
            "facts": [{"content": "临时事实", "category": "preference", "confidence": 0.8}],
        })
        # 清除
        r = client.delete("/api/v1/memory/to-delete")
        assert r.json()["success"] is True
        # 重新获取
        r2 = client.get("/api/v1/memory/to-delete")
        assert r2.json()["memory"]["facts"] == []

    def test_delete_nonexistent_no_error(self, client):
        """清除不存在的 session 也返回 success=True，不报错。"""
        r = client.delete("/api/v1/memory/never-existed-xyz")
        assert r.status_code == 200
        assert r.json()["success"] is True
