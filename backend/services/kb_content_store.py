"""知识库内容存储 —— 描述性字段的 SQLite 哈希表。

Neo4j 只存图结构（id/name/level + 边关系），
所有描述性内容（简介、拓展逻辑、章节模板、指标描述、关键词、典型问题等）
按 node_id 存在这张表里，定位到节点后按需取出。
"""

import json
import logging
import aiosqlite
from typing import Optional

logger = logging.getLogger(__name__)

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS kb_contents (
    node_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    domain TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    description TEXT DEFAULT '',
    keywords TEXT DEFAULT '',
    typical_questions TEXT DEFAULT '',
    expand_logic TEXT DEFAULT '',
    chapter_template TEXT DEFAULT '',
    suggestion TEXT DEFAULT '',
    extra TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_kb_level ON kb_contents(level);
CREATE INDEX IF NOT EXISTS idx_kb_label ON kb_contents(label);
CREATE INDEX IF NOT EXISTS idx_kb_name ON kb_contents(name);
"""


class KBContentStore:
    """知识库描述性内容的 SQLite 存储。"""

    def __init__(self, db_path: str = "./data/kb_contents.db"):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self):
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_INIT_SQL)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    async def clear(self):
        """清空所有内容（导入前调用）。"""
        await self._db.execute("DELETE FROM kb_contents")
        await self._db.commit()

    async def upsert(self, node_id: str, name: str, level: int, label: str = "",
                     domain: str = "", summary: str = "", description: str = "",
                     keywords: str = "", typical_questions: str = "",
                     expand_logic: str = "", chapter_template: str = "",
                     suggestion: str = "", extra: str = ""):
        """插入或更新一条知识库内容。"""
        await self._db.execute("""
            INSERT INTO kb_contents (node_id, name, level, label, domain, summary, description,
                                     keywords, typical_questions, expand_logic, chapter_template, suggestion, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                name=excluded.name, level=excluded.level, label=excluded.label,
                domain=excluded.domain, summary=excluded.summary, description=excluded.description,
                keywords=excluded.keywords, typical_questions=excluded.typical_questions,
                expand_logic=excluded.expand_logic, chapter_template=excluded.chapter_template,
                suggestion=excluded.suggestion, extra=excluded.extra
        """, (node_id, name, level, label, domain, summary, description,
              keywords, typical_questions, expand_logic, chapter_template, suggestion, extra))
        await self._db.commit()

    async def batch_upsert(self, records: list[dict]):
        """批量插入。每条 record 是 upsert 的关键字参数。"""
        for rec in records:
            await self._db.execute("""
                INSERT INTO kb_contents (node_id, name, level, label, domain, summary, description,
                                         keywords, typical_questions, expand_logic, chapter_template, suggestion, extra)
                VALUES (:node_id, :name, :level, :label, :domain, :summary, :description,
                        :keywords, :typical_questions, :expand_logic, :chapter_template, :suggestion, :extra)
                ON CONFLICT(node_id) DO UPDATE SET
                    name=excluded.name, level=excluded.level, label=excluded.label,
                    domain=excluded.domain, summary=excluded.summary, description=excluded.description,
                    keywords=excluded.keywords, typical_questions=excluded.typical_questions,
                    expand_logic=excluded.expand_logic, chapter_template=excluded.chapter_template,
                    suggestion=excluded.suggestion, extra=excluded.extra
            """, {
                "node_id": rec.get("node_id", ""),
                "name": rec.get("name", ""),
                "level": rec.get("level", 0),
                "label": rec.get("label", ""),
                "domain": rec.get("domain", ""),
                "summary": rec.get("summary", ""),
                "description": rec.get("description", ""),
                "keywords": rec.get("keywords", ""),
                "typical_questions": rec.get("typical_questions", ""),
                "expand_logic": rec.get("expand_logic", ""),
                "chapter_template": rec.get("chapter_template", ""),
                "suggestion": rec.get("suggestion", ""),
                "extra": rec.get("extra", ""),
            })
        await self._db.commit()
        logger.info(f"KB 内容存储: 批量写入 {len(records)} 条")

    async def get(self, node_id: str) -> Optional[dict]:
        """按 node_id 获取内容。"""
        cur = await self._db.execute("SELECT * FROM kb_contents WHERE node_id=?", (node_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_by_name(self, name: str) -> list[dict]:
        """按名称查询（可能有多个同名不同层级的节点）。"""
        cur = await self._db.execute("SELECT * FROM kb_contents WHERE name=?", (name,))
        return [dict(r) for r in await cur.fetchall()]

    async def get_batch(self, node_ids: list[str]) -> dict[str, dict]:
        """批量获取。返回 {node_id: content_dict}。"""
        if not node_ids:
            return {}
        placeholders = ",".join("?" * len(node_ids))
        cur = await self._db.execute(
            f"SELECT * FROM kb_contents WHERE node_id IN ({placeholders})", node_ids
        )
        return {r["node_id"]: dict(r) for r in await cur.fetchall()}

    async def count(self) -> int:
        cur = await self._db.execute("SELECT count(*) AS c FROM kb_contents")
        return (await cur.fetchone())["c"]
