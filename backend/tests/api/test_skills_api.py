"""测试 Skills API 端点：GET /api/v1/skills 和 PATCH /api/v1/skills/{name}。

使用 FastAPI TestClient + monkeypatch app_state，不需要真实数据库。
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


def _make_mock_registry(skills: list[dict]):
    """创建模拟 SkillRegistry，list_skills 返回指定列表。"""
    registry = MagicMock()
    mock_skills = []
    for s in skills:
        skill = MagicMock()
        skill.name = s["name"]
        skill.description = s.get("description", "")
        skill.source = s.get("source", "builtin")
        skill.enabled = s.get("enabled", True)
        mock_skills.append(skill)
    registry.list_skills = MagicMock(return_value=mock_skills)
    registry.set_enabled = MagicMock(return_value=True)
    registry.get = MagicMock(side_effect=lambda name: next(
        (s for s in mock_skills if s.name == name), None
    ))
    return registry


@pytest.fixture
def client_with_skills(monkeypatch):
    """创建带有 mock app_state 的 TestClient。"""
    import main

    mock_registry = _make_mock_registry([
        {"name": "outline-generate", "description": "生成大纲", "source": "builtin", "enabled": True},
        {"name": "skill-factory", "description": "技能工厂", "source": "builtin", "enabled": True},
        {"name": "custom-skill", "description": "自定义技能", "source": "custom", "enabled": False},
    ])
    monkeypatch.setattr(main, "app_state", {"skill_registry": mock_registry})
    return TestClient(main.app, raise_server_exceptions=False)


class TestSkillsGetEndpoint:

    def test_get_skills_returns_list(self, client_with_skills):
        resp = client_with_skills.get("/api/v1/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert "skills" in data
        assert isinstance(data["skills"], list)

    def test_get_skills_includes_all_registered(self, client_with_skills):
        resp = client_with_skills.get("/api/v1/skills")
        data = resp.json()
        names = {s["name"] for s in data["skills"]}
        assert "outline-generate" in names
        assert "skill-factory" in names
        assert "custom-skill" in names

    def test_get_skills_includes_enabled_field(self, client_with_skills):
        resp = client_with_skills.get("/api/v1/skills")
        data = resp.json()
        for skill in data["skills"]:
            assert "enabled" in skill
            assert "name" in skill

    def test_get_skills_custom_has_correct_source(self, client_with_skills):
        resp = client_with_skills.get("/api/v1/skills")
        data = resp.json()
        custom = next((s for s in data["skills"] if s["name"] == "custom-skill"), None)
        assert custom is not None
        assert custom.get("source") == "custom"


class TestSkillsPatchEndpoint:

    def test_patch_enable_skill(self, client_with_skills):
        resp = client_with_skills.patch(
            "/api/v1/skills/outline-generate",
            json={"enabled": True},
        )
        assert resp.status_code == 200

    def test_patch_disable_skill(self, client_with_skills):
        resp = client_with_skills.patch(
            "/api/v1/skills/skill-factory",
            json={"enabled": False},
        )
        assert resp.status_code == 200

    def test_patch_nonexistent_skill_returns_404(self, client_with_skills):
        import main
        main.app_state["skill_registry"].set_enabled = MagicMock(return_value=False)
        resp = client_with_skills.patch(
            "/api/v1/skills/nonexistent",
            json={"enabled": True},
        )
        # 应返回 404 或类似错误码
        assert resp.status_code in (404, 400, 422)
