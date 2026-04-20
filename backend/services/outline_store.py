"""大纲存储服务——管理 outlines / outline_nodes / node_bindings 三张表。"""
import json
import logging
import uuid
from datetime import datetime
from typing import Optional
import aiosqlite

logger = logging.getLogger(__name__)

_SQL = """
CREATE TABLE IF NOT EXISTS outlines (
    id            TEXT PRIMARY KEY,
    skill_name    TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    scene_intro   TEXT DEFAULT '',
    keywords      TEXT DEFAULT '[]',
    query_variants TEXT DEFAULT '[]',
    raw_input     TEXT DEFAULT '',
    root_node_id  TEXT,
    status        TEXT DEFAULT 'draft',
    version       INTEGER DEFAULT 1,
    created_by    TEXT DEFAULT '',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_at   TIMESTAMP,
    approved_by   TEXT
);
CREATE TABLE IF NOT EXISTS outline_nodes (
    id              TEXT PRIMARY KEY,
    outline_id      TEXT NOT NULL,
    neo4j_node_id   TEXT DEFAULT '',
    parent_id       TEXT DEFAULT '',
    name            TEXT NOT NULL,
    level           INTEGER NOT NULL,
    source          TEXT NOT NULL DEFAULT 'kb',
    sort_order      INTEGER DEFAULT 0,
    expand_logic    TEXT DEFAULT '',
    chapter_template TEXT DEFAULT '',
    status          TEXT DEFAULT 'draft',
    FOREIGN KEY (outline_id) REFERENCES outlines(id)
);
CREATE TABLE IF NOT EXISTS node_bindings (
    id              TEXT PRIMARY KEY,
    node_id         TEXT NOT NULL,
    node_name       TEXT NOT NULL,
    data_type       TEXT NOT NULL DEFAULT 'TABLE',
    source_type     TEXT DEFAULT 'mock',
    query_template  TEXT DEFAULT '',
    display_config  TEXT DEFAULT '{}',
    paragraph_template TEXT DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(node_id)
);
CREATE INDEX IF NOT EXISTS idx_outlines_status ON outlines(status);
CREATE INDEX IF NOT EXISTS idx_outlines_skill_name ON outlines(skill_name);
CREATE INDEX IF NOT EXISTS idx_nodes_outline ON outline_nodes(outline_id);
CREATE INDEX IF NOT EXISTS idx_nodes_level ON outline_nodes(level);
CREATE INDEX IF NOT EXISTS idx_nodes_neo4j ON outline_nodes(neo4j_node_id);
CREATE INDEX IF NOT EXISTS idx_bindings_node ON node_bindings(node_id);
"""


class OutlineStore:
    """outlines / outline_nodes / node_bindings 三表 CRUD。"""

    def __init__(self, db_path: str = "./data/outlines.db"):
        self.db_path = db_path
        self._db = None

    async def init(self):
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SQL)
        await self._db.commit()
        logger.info(f"OutlineStore 初始化完成: {self.db_path}")

    async def close(self):
        if self._db:
            await self._db.close()

    # ─── outlines 表 ───

    async def create_outline(
        self,
        skill_name: str,
        display_name: str,
        raw_input: str = "",
        scene_intro: str = "",
        keywords: list = None,
        query_variants: list = None,
        created_by: str = "",
    ) -> str:
        oid = str(uuid.uuid4())
        now = datetime.now().isoformat()
        await self._db.execute(
            "INSERT INTO outlines(id,skill_name,display_name,scene_intro,keywords,"
            "query_variants,raw_input,status,version,created_by,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (oid, skill_name, display_name, scene_intro,
             json.dumps(keywords or [], ensure_ascii=False),
             json.dumps(query_variants or [], ensure_ascii=False),
             raw_input, "draft", 1, created_by, now),
        )
        await self._db.commit()
        return oid

    async def get_outline(self, outline_id: str) -> Optional[dict]:
        c = await self._db.execute("SELECT * FROM outlines WHERE id=?", (outline_id,))
        r = await c.fetchone()
        return self._parse_outline(dict(r)) if r else None

    async def list_outlines(self, status: str = None, limit: int = 50) -> list:
        if status:
            c = await self._db.execute(
                "SELECT * FROM outlines WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            c = await self._db.execute(
                "SELECT * FROM outlines ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return [self._parse_outline(dict(r)) for r in await c.fetchall()]

    async def update_outline_status(self, outline_id: str, status: str,
                                     approved_by: str = "") -> bool:
        now = datetime.now().isoformat()
        if status == "approved":
            await self._db.execute(
                "UPDATE outlines SET status=?,approved_at=?,approved_by=? WHERE id=?",
                (status, now, approved_by, outline_id),
            )
        else:
            await self._db.execute(
                "UPDATE outlines SET status=? WHERE id=?", (status, outline_id)
            )
        await self._db.commit()
        return True

    async def set_root_node(self, outline_id: str, root_node_id: str):
        await self._db.execute(
            "UPDATE outlines SET root_node_id=? WHERE id=?", (root_node_id, outline_id)
        )
        await self._db.commit()

    async def list_active_outlines_for_router(self, limit: int = 100) -> list:
        """供 skill-router 查询已激活的大纲元数据（替代文件系统扫描）。"""
        c = await self._db.execute(
            "SELECT id,skill_name,display_name,scene_intro,keywords,query_variants,raw_input "
            "FROM outlines WHERE status IN ('active','approved') "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._parse_outline(dict(r)) for r in await c.fetchall()]

    def _parse_outline(self, d: dict) -> dict:
        for f in ("keywords", "query_variants"):
            if d.get(f):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    d[f] = []
        return d

    # ─── outline_nodes 表 ───

    async def create_node(
        self,
        outline_id: str,
        name: str,
        level: int,
        source: str = "kb",
        neo4j_node_id: str = "",
        parent_id: str = "",
        sort_order: int = 0,
        expand_logic: str = "",
        chapter_template: str = "",
        node_id: str = None,
    ) -> str:
        nid = node_id or str(uuid.uuid4())
        # user_defined 节点需要审核，kb 节点直接 approved
        node_status = "draft" if source == "user_defined" else "approved"
        await self._db.execute(
            "INSERT INTO outline_nodes(id,outline_id,neo4j_node_id,parent_id,name,level,"
            "source,sort_order,expand_logic,chapter_template,status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (nid, outline_id, neo4j_node_id, parent_id, name, level,
             source, sort_order, expand_logic, chapter_template, node_status),
        )
        await self._db.commit()
        return nid

    async def get_nodes_by_outline(self, outline_id: str) -> list:
        c = await self._db.execute(
            "SELECT * FROM outline_nodes WHERE outline_id=? ORDER BY sort_order ASC",
            (outline_id,),
        )
        return [dict(r) for r in await c.fetchall()]

    async def get_pending_nodes(self) -> list:
        """获取所有待审核的 user_defined 节点。"""
        c = await self._db.execute(
            "SELECT n.*, o.skill_name, o.display_name FROM outline_nodes n "
            "JOIN outlines o ON n.outline_id = o.id "
            "WHERE n.source='user_defined' AND n.status='draft' "
            "ORDER BY n.outline_id, n.sort_order"
        )
        return [dict(r) for r in await c.fetchall()]

    async def approve_node(self, node_id: str):
        await self._db.execute(
            "UPDATE outline_nodes SET status='approved' WHERE id=?", (node_id,)
        )
        await self._db.commit()

    async def bulk_create_nodes_from_outline_tree(
        self, outline_id: str, outline_json: dict
    ) -> str:
        """将大纲树递归写入 outline_nodes 表，返回根节点 id。"""
        root_id = await self._insert_node_recursive(outline_id, outline_json, "", 0)
        await self.set_root_node(outline_id, root_id)
        return root_id

    async def _insert_node_recursive(
        self, outline_id: str, node: dict, parent_id: str, sort_order: int
    ) -> str:
        source = node.get("source", "kb")
        neo4j_id = node.get("id", "") if source == "kb" else ""
        nid = await self.create_node(
            outline_id=outline_id,
            name=node.get("name", ""),
            level=node.get("level", 0),
            source=source,
            neo4j_node_id=neo4j_id,
            parent_id=parent_id,
            sort_order=sort_order,
            expand_logic=node.get("expand_logic", ""),
            chapter_template=node.get("chapter_template", ""),
        )
        for i, child in enumerate(node.get("children", [])):
            await self._insert_node_recursive(outline_id, child, nid, i)
        return nid

    # ─── node_bindings 表 ───

    async def upsert_binding(
        self,
        node_id: str,
        node_name: str,
        data_type: str = "TABLE",
        source_type: str = "mock",
        query_template: str = "",
        display_config: dict = None,
        paragraph_template: dict = None,
    ) -> str:
        bid = str(uuid.uuid4())
        dc = json.dumps(display_config or {}, ensure_ascii=False)
        pt = json.dumps(paragraph_template or {}, ensure_ascii=False)
        await self._db.execute(
            "INSERT INTO node_bindings(id,node_id,node_name,data_type,source_type,"
            "query_template,display_config,paragraph_template) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(node_id) DO UPDATE SET "
            "node_name=excluded.node_name,data_type=excluded.data_type,"
            "source_type=excluded.source_type,query_template=excluded.query_template,"
            "display_config=excluded.display_config,paragraph_template=excluded.paragraph_template",
            (bid, node_id, node_name, data_type, source_type, query_template, dc, pt),
        )
        await self._db.commit()
        return bid

    async def get_binding(self, node_id: str) -> Optional[dict]:
        c = await self._db.execute(
            "SELECT * FROM node_bindings WHERE node_id=?", (node_id,)
        )
        r = await c.fetchone()
        if not r:
            return None
        d = dict(r)
        for f in ("display_config", "paragraph_template"):
            if d.get(f):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    d[f] = {}
        return d

    async def get_bindings_by_nodes(self, node_ids: list) -> dict:
        if not node_ids:
            return {}
        placeholders = ",".join("?" * len(node_ids))
        c = await self._db.execute(
            f"SELECT * FROM node_bindings WHERE node_id IN ({placeholders})", node_ids
        )
        result = {}
        for r in await c.fetchall():
            d = dict(r)
            for f in ("display_config", "paragraph_template"):
                if d.get(f):
                    try:
                        d[f] = json.loads(d[f])
                    except Exception:
                        d[f] = {}
            result[d["node_id"]] = d
        return result

    async def bulk_upsert_bindings_from_outline(self, outline_json: dict):
        """递归从大纲中提取所有 L5 节点并 upsert 到 node_bindings。"""
        l5_nodes: list = []
        _collect_l5(outline_json, l5_nodes)
        for node in l5_nodes:
            paragraph = node.get("paragraph", {})
            await self.upsert_binding(
                node_id=node.get("id", ""),
                node_name=node.get("name", ""),
                data_type=paragraph.get("data_source", "TABLE"),
                source_type="mock",
                paragraph_template=paragraph,
            )


def _collect_l5(node: dict, result: list):
    if node.get("level") == 5:
        result.append(node)
        return
    for child in node.get("children", []):
        _collect_l5(child, result)
