"""API 契约测试：Skills 端点（Phase 3 新增）。

验证：
  GET /api/v1/skills           → 返回技能列表
  GET /api/v1/skills/{name}    → 返回指定技能详情
  GET /api/v1/skills/nonexist  → 返回 null + error
"""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


class TestSkillsListEndpoint:
    def test_list_skills_returns_list(self, client):
        r = client.get("/api/v1/skills")
        assert r.status_code == 200
        data = r.json()
        assert "skills" in data
        assert isinstance(data["skills"], list)

    def test_list_skills_count(self, client):
        """Mock registry 提供 6 个技能。"""
        r = client.get("/api/v1/skills")
        skills = r.json()["skills"]
        assert len(skills) == 6

    def test_skill_has_required_fields(self, client):
        r = client.get("/api/v1/skills")
        skill = r.json()["skills"][0]
        for field in ["name", "display_name", "description", "enabled", "source"]:
            assert field in skill, f"字段 {field} 缺失"

    def test_skill_enabled_is_bool(self, client):
        r = client.get("/api/v1/skills")
        for skill in r.json()["skills"]:
            assert isinstance(skill["enabled"], bool)

    def test_skill_source_valid(self, client):
        r = client.get("/api/v1/skills")
        for skill in r.json()["skills"]:
            assert skill["source"] in ("builtin", "custom")

    def test_builtin_skills_present(self, client):
        r = client.get("/api/v1/skills")
        names = [s["name"] for s in r.json()["skills"]]
        for expected in ["outline-generate", "report-generate", "data-execute"]:
            assert expected in names

    def test_skill_executor_field(self, client):
        """executor 字段存在（可为 None 或含 module/cls）。"""
        r = client.get("/api/v1/skills")
        for skill in r.json()["skills"]:
            assert "executor" in skill
            if skill["executor"] is not None:
                assert "module" in skill["executor"] or "cls" in skill["executor"]


class TestSkillDetailEndpoint:
    def test_get_existing_skill(self, client):
        r = client.get("/api/v1/skills/outline-generate")
        assert r.status_code == 200
        data = r.json()
        assert "skill" in data
        assert data["skill"] is not None
        assert data["skill"]["name"] == "outline-generate"

    def test_get_skill_full_fields(self, client):
        r = client.get("/api/v1/skills/report-generate")
        skill = r.json()["skill"]
        for field in ["name", "display_name", "description", "enabled", "source"]:
            assert field in skill

    def test_get_nonexistent_skill(self, client):
        r = client.get("/api/v1/skills/nonexistent-skill-xyz")
        assert r.status_code == 200
        data = r.json()
        assert data["skill"] is None
        assert "error" in data
        assert "nonexistent-skill-xyz" in data["error"]

    def test_get_skill_factory(self, client):
        r = client.get("/api/v1/skills/skill-factory")
        assert r.status_code == 200
        assert r.json()["skill"]["name"] == "skill-factory"
