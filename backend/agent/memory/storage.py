"""Memory 存储层 —— 原子读写 JSON 文件。

使用 temp 文件 + rename 确保写入原子性，防止进程崩溃时数据损坏。
"""

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 默认存储路径
DEFAULT_MEMORY_PATH = "./data/memory.json"

# 初始空白 memory 结构
_EMPTY_MEMORY = {
    "version": "1.0",
    "lastUpdated": "",
    "user": {
        "workContext":    {"summary": "", "updatedAt": ""},
        "topOfMind":      {"summary": "", "updatedAt": ""},
    },
    "history": {
        "recentMonths":   {"summary": "", "updatedAt": ""},
    },
    "facts": [],
}


class MemoryStorage:
    """Memory JSON 文件读写（原子操作）。"""

    def __init__(self, path: str = DEFAULT_MEMORY_PATH):
        self._path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    # ─── 读 ──────────────────────────────────────────────────────────────────

    def load(self) -> dict:
        """加载 memory 数据，文件不存在则返回空结构。"""
        if not os.path.exists(self._path):
            return self._clone_empty()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return self._ensure_structure(data)
        except Exception as e:
            logger.warning(f"Memory 文件读取失败，使用空结构: {e}")
            return self._clone_empty()

    # ─── 写 ──────────────────────────────────────────────────────────────────

    def atomic_update(self, new_data: dict) -> bool:
        """原子写入：先写 temp 文件，再 rename 覆盖。"""
        new_data["lastUpdated"] = datetime.utcnow().isoformat() + "Z"
        dir_ = os.path.dirname(os.path.abspath(self._path))
        try:
            # 写入同目录下的临时文件（确保 rename 是原子操作）
            fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
            return True
        except Exception as e:
            logger.error(f"Memory 原子写入失败: {e}")
            if "tmp_path" in dir() and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return False

    def clear(self) -> bool:
        """清空 memory 数据（保留结构）。"""
        return self.atomic_update(self._clone_empty())

    # ─── Facts CRUD ──────────────────────────────────────────────────────────

    def add_facts(self, new_facts: list[dict], max_facts: int = 100) -> dict:
        """追加新 facts，按 confidence 排序并截断到 max_facts。"""
        data = self.load()
        existing_ids = {f["id"] for f in data.get("facts", [])}

        for fact in new_facts:
            if not fact.get("id"):
                fact["id"] = str(uuid.uuid4())[:8]
            if not fact.get("createdAt"):
                fact["createdAt"] = datetime.utcnow().isoformat() + "Z"
            if fact["id"] not in existing_ids:
                data["facts"].append(fact)

        # 按 confidence 降序，截断
        data["facts"] = sorted(
            data["facts"],
            key=lambda f: f.get("confidence", 0),
            reverse=True
        )[:max_facts]

        self.atomic_update(data)
        return data

    # ─── 格式化注入 ──────────────────────────────────────────────────────────

    def format_for_injection(self, max_tokens: int = 2000) -> str:
        """
        将 memory 数据格式化为 system prompt 注入文本。
        粗略按字符数限制（chars * 1.5 ≈ tokens）。
        """
        data = self.load()
        parts = []

        user = data.get("user", {})
        wc = user.get("workContext", {}).get("summary", "")
        tm = user.get("topOfMind", {}).get("summary", "")
        if wc:
            parts.append(f"Work Context: {wc}")
        if tm:
            parts.append(f"Current Focus: {tm}")

        hist = data.get("history", {})
        rm = hist.get("recentMonths", {}).get("summary", "")
        if rm:
            parts.append(f"Recent Activity: {rm}")

        facts = data.get("facts", [])
        if facts:
            fact_lines = []
            for f in facts:
                conf = f.get("confidence", 0)
                cat = f.get("category", "")
                content = f.get("content", "")
                if conf >= 0.7:  # 只注入高置信度 fact
                    fact_lines.append(f"- [{cat}] {content} ({conf:.0%})")
            if fact_lines:
                parts.append("Known Facts:\n" + "\n".join(fact_lines))

        if not parts:
            return ""

        text = "\n\n".join(parts)
        # 按字符粗截（max_tokens * 1.5 chars）
        char_limit = max_tokens * 2
        if len(text) > char_limit:
            text = text[:char_limit] + "…"
        return text

    # ─── 内部工具 ────────────────────────────────────────────────────────────

    @staticmethod
    def _clone_empty() -> dict:
        import copy
        return copy.deepcopy(_EMPTY_MEMORY)

    @staticmethod
    def _ensure_structure(data: dict) -> dict:
        """确保 memory 数据有完整结构（向前兼容旧版本）。"""
        empty = _EMPTY_MEMORY
        for k, v in empty.items():
            if k not in data:
                import copy
                data[k] = copy.deepcopy(v)
        if "user" in data:
            for k, v in empty["user"].items():
                if k not in data["user"]:
                    import copy
                    data["user"][k] = copy.deepcopy(v)
        if "history" in data:
            for k, v in empty["history"].items():
                if k not in data["history"]:
                    import copy
                    data["history"][k] = copy.deepcopy(v)
        if "facts" not in data:
            data["facts"] = []
        return data
