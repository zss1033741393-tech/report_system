"""Memory 持久化存储 —— 原子读写 JSON 文件。

每个 session 对应一个独立的 memory JSON 文件。
写操作通过 temp-file + rename 保证原子性，避免并发写导致文件损坏。
"""
import json
import logging
import os
import tempfile
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_EMPTY_MEMORY: dict = {
    "user": {
        "workContext": {"summary": ""},
        "topOfMind": {"summary": ""},
    },
    "facts": [],
}


class MemoryStorage:

    def __init__(self, storage_dir: str = "./data/memory"):
        self._dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

    def _path(self, session_id: str) -> str:
        # 用 session_id 的安全化形式作为文件名
        safe = session_id.replace("/", "_").replace("\\", "_")
        return os.path.join(self._dir, f"{safe}.json")

    def load(self, session_id: str) -> dict:
        """加载 session 的 memory，不存在则返回空结构。"""
        path = self._path(session_id)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except FileNotFoundError:
            return dict(_EMPTY_MEMORY)
        except Exception as e:
            logger.warning(f"Memory 读取失败 ({session_id}): {e}，返回空记忆")
            return dict(_EMPTY_MEMORY)

    def save(self, session_id: str, memory: dict):
        """原子写入 memory（temp file + rename）。"""
        path = self._path(session_id)
        dir_ = os.path.dirname(path)
        try:
            # 写入临时文件
            fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(memory, f, ensure_ascii=False, indent=2)
            # 原子替换
            os.replace(tmp_path, path)
        except Exception as e:
            logger.error(f"Memory 写入失败 ({session_id}): {e}")
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def merge(self, session_id: str, new_memory: dict) -> dict:
        """将新 memory 与现有 memory 合并后写入。

        合并策略：
        - user.workContext / topOfMind: 用新值覆盖（非空时）
        - facts: 合并去重（按 content 去重），按 confidence 排序，最多保留 20 条
        """
        current = self.load(session_id)
        merged = _merge_memory(current, new_memory)
        self.save(session_id, merged)
        return merged

    def clear(self, session_id: str):
        """清除 session 的 memory。"""
        path = self._path(session_id)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Memory 清除失败 ({session_id}): {e}")

    def list_sessions(self) -> list[str]:
        """列出所有有 memory 的 session ID。"""
        try:
            files = [f for f in os.listdir(self._dir) if f.endswith(".json")]
            return [f[:-5] for f in files]  # 去掉 .json 后缀
        except Exception:
            return []


def _merge_memory(current: dict, new: dict) -> dict:
    result = {
        "user": {
            "workContext": {"summary": ""},
            "topOfMind": {"summary": ""},
        },
        "facts": [],
    }

    # user context
    cur_user = current.get("user", {})
    new_user = new.get("user", {})

    def _pick_summary(cur_section, new_section):
        new_s = (new_section or {}).get("summary", "")
        cur_s = (cur_section or {}).get("summary", "")
        return new_s if new_s else cur_s

    result["user"]["workContext"]["summary"] = _pick_summary(
        cur_user.get("workContext"), new_user.get("workContext")
    )
    result["user"]["topOfMind"]["summary"] = _pick_summary(
        cur_user.get("topOfMind"), new_user.get("topOfMind")
    )

    # facts 合并去重
    all_facts: list[dict] = []
    seen_content: set[str] = set()

    for fact in (new.get("facts") or []):
        content = fact.get("content", "").strip()
        if content and content not in seen_content:
            seen_content.add(content)
            all_facts.append({
                "id": fact.get("id") or str(uuid.uuid4())[:8],
                "content": content,
                "category": fact.get("category", "preference"),
                "confidence": float(fact.get("confidence", 0.8)),
            })

    for fact in (current.get("facts") or []):
        content = fact.get("content", "").strip()
        if content and content not in seen_content:
            seen_content.add(content)
            all_facts.append({
                "id": fact.get("id") or str(uuid.uuid4())[:8],
                "content": content,
                "category": fact.get("category", "preference"),
                "confidence": float(fact.get("confidence", 0.8)),
            })

    # 按置信度降序，最多保留 20 条
    all_facts.sort(key=lambda x: x["confidence"], reverse=True)
    result["facts"] = all_facts[:20]

    return result
