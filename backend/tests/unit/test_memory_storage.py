"""单元测试：MemoryStorage —— 记忆持久化存储。

覆盖：
  - load() 不存在的 session → 返回空结构
  - save() + load() 往返一致
  - merge() 去重（相同 content 只保留一条）
  - merge() 按 confidence 降序排列
  - merge() 超过 20 条时截断
  - clear() 后 load() 返回空结构
"""
import pytest
import os
from agent.memory.storage import MemoryStorage


@pytest.fixture
def storage(tmp_path):
    return MemoryStorage(storage_dir=str(tmp_path / "mem"))


def _fact(content: str, confidence: float = 0.8, category: str = "preference") -> dict:
    return {"content": content, "category": category, "confidence": confidence}


class TestMemoryStorageLoad:
    def test_load_nonexistent_returns_empty(self, storage):
        mem = storage.load("nonexistent-session")
        assert mem["user"]["workContext"]["summary"] == ""
        assert mem["user"]["topOfMind"]["summary"] == ""
        assert mem["facts"] == []

    def test_load_after_save_roundtrip(self, storage):
        data = {
            "user": {
                "workContext": {"summary": "负责 fgOTN 传送"},
                "topOfMind": {"summary": "当前在分析容量"},
            },
            "facts": [_fact("不看低阶交叉", 0.9)],
        }
        storage.save("sess-1", data)
        loaded = storage.load("sess-1")
        assert loaded["user"]["workContext"]["summary"] == "负责 fgOTN 传送"
        assert loaded["user"]["topOfMind"]["summary"] == "当前在分析容量"
        assert len(loaded["facts"]) == 1
        assert loaded["facts"][0]["content"] == "不看低阶交叉"

    def test_load_different_sessions_isolated(self, storage):
        storage.save("sess-a", {"user": {"workContext": {"summary": "A"}, "topOfMind": {"summary": ""}}, "facts": []})
        storage.save("sess-b", {"user": {"workContext": {"summary": "B"}, "topOfMind": {"summary": ""}}, "facts": []})
        assert storage.load("sess-a")["user"]["workContext"]["summary"] == "A"
        assert storage.load("sess-b")["user"]["workContext"]["summary"] == "B"


class TestMemoryStorageMergeDedup:
    def test_merge_dedup_same_content(self, storage):
        """相同 content 的 fact 去重，只保留一条（新的优先）。"""
        existing = {
            "user": {"workContext": {"summary": ""}, "topOfMind": {"summary": ""}},
            "facts": [_fact("不看低阶交叉", 0.8)],
        }
        storage.save("sess-dedup", existing)
        new_memory = {
            "user": {"workContext": {"summary": ""}, "topOfMind": {"summary": ""}},
            "facts": [_fact("不看低阶交叉", 0.95)],  # 相同 content，更高置信度
        }
        merged = storage.merge("sess-dedup", new_memory)
        contents = [f["content"] for f in merged["facts"]]
        assert contents.count("不看低阶交叉") == 1

    def test_merge_different_content_both_kept(self, storage):
        existing = {
            "user": {"workContext": {"summary": ""}, "topOfMind": {"summary": ""}},
            "facts": [_fact("偏好A", 0.8)],
        }
        storage.save("sess-both", existing)
        new_memory = {
            "user": {"workContext": {"summary": ""}, "topOfMind": {"summary": ""}},
            "facts": [_fact("偏好B", 0.9)],
        }
        merged = storage.merge("sess-both", new_memory)
        contents = [f["content"] for f in merged["facts"]]
        assert "偏好A" in contents
        assert "偏好B" in contents


class TestMemoryStorageMergeSort:
    def test_merge_sorts_by_confidence_desc(self, storage):
        """merge 后 facts 按 confidence 降序排列。"""
        new_memory = {
            "user": {"workContext": {"summary": ""}, "topOfMind": {"summary": ""}},
            "facts": [
                _fact("低置信", 0.3),
                _fact("高置信", 0.95),
                _fact("中置信", 0.6),
            ],
        }
        merged = storage.merge("sess-sort", new_memory)
        confs = [f["confidence"] for f in merged["facts"]]
        assert confs == sorted(confs, reverse=True)

    def test_merge_truncates_to_20(self, storage):
        """超过 20 条 facts 时，截断保留置信度最高的 20 条。"""
        facts = [_fact(f"事实{i}", round(i / 30, 2)) for i in range(25)]
        new_memory = {
            "user": {"workContext": {"summary": ""}, "topOfMind": {"summary": ""}},
            "facts": facts,
        }
        merged = storage.merge("sess-trunc", new_memory)
        assert len(merged["facts"]) <= 20


class TestMemoryStorageClear:
    def test_clear_then_load_empty(self, storage):
        storage.save("sess-clear", {
            "user": {"workContext": {"summary": "有内容"}, "topOfMind": {"summary": ""}},
            "facts": [_fact("要被清除的事实")],
        })
        storage.clear("sess-clear")
        mem = storage.load("sess-clear")
        assert mem["user"]["workContext"]["summary"] == ""
        assert mem["facts"] == []

    def test_clear_nonexistent_no_error(self, storage):
        """清除不存在的 session 不应报错。"""
        storage.clear("never-existed-session")  # 不应抛出异常


class TestMemoryStorageUserContext:
    def test_merge_updates_work_context(self, storage):
        """新 memory 的非空 workContext 覆盖旧值。"""
        storage.save("sess-ctx", {
            "user": {"workContext": {"summary": "旧上下文"}, "topOfMind": {"summary": ""}},
            "facts": [],
        })
        new_memory = {
            "user": {"workContext": {"summary": "新上下文"}, "topOfMind": {"summary": ""}},
            "facts": [],
        }
        merged = storage.merge("sess-ctx", new_memory)
        assert merged["user"]["workContext"]["summary"] == "新上下文"

    def test_merge_keeps_old_context_if_new_empty(self, storage):
        """新 memory workContext 为空时，保留旧值。"""
        storage.save("sess-keep", {
            "user": {"workContext": {"summary": "保留"}, "topOfMind": {"summary": ""}},
            "facts": [],
        })
        new_memory = {
            "user": {"workContext": {"summary": ""}, "topOfMind": {"summary": ""}},
            "facts": [],
        }
        merged = storage.merge("sess-keep", new_memory)
        assert merged["user"]["workContext"]["summary"] == "保留"
