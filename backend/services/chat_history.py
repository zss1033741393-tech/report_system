"""SQLite 对话历史。"""
import json, logging, aiosqlite
from typing import Optional
from datetime import datetime
logger = logging.getLogger(__name__)

_SQL = """
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, title TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, msg_type TEXT DEFAULT 'text', metadata TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (session_id) REFERENCES sessions(id));
CREATE TABLE IF NOT EXISTS outline_states (session_id TEXT PRIMARY KEY, outline_json TEXT NOT NULL, anchor_info TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (session_id) REFERENCES sessions(id));
CREATE TABLE IF NOT EXISTS llm_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    llm_type TEXT NOT NULL,
    step_name TEXT NOT NULL,
    request_messages TEXT NOT NULL,
    response_content TEXT,
    reasoning_content TEXT,
    model TEXT,
    temperature REAL,
    elapsed_ms REAL,
    success BOOLEAN DEFAULT 1,
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_msg_sid ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_trace_session ON llm_traces(session_id);
CREATE INDEX IF NOT EXISTS idx_trace_type ON llm_traces(llm_type, step_name);
"""

class ChatHistoryService:
    def __init__(self, db_path="./data/chat_history.db"): self.db_path = db_path; self._db = None

    async def init(self):
        self._db = await aiosqlite.connect(self.db_path); self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SQL); await self._db.commit()

    async def close(self):
        if self._db: await self._db.close()

    async def create_session(self, sid, title=""):
        now = datetime.now().isoformat()
        await self._db.execute("INSERT OR IGNORE INTO sessions(id,title,created_at,updated_at) VALUES(?,?,?,?)", (sid,title,now,now))
        await self._db.commit(); return {"id":sid,"title":title,"created_at":now,"updated_at":now}

    async def ensure_session(self, sid, title=""):
        c = await self._db.execute("SELECT id FROM sessions WHERE id=?", (sid,))
        if not await c.fetchone(): await self.create_session(sid, title)

    async def update_session_title(self, sid, title):
        await self._db.execute("UPDATE sessions SET title=?,updated_at=? WHERE id=?", (title,datetime.now().isoformat(),sid))
        await self._db.commit()

    async def list_sessions(self, limit=50, offset=0):
        c = await self._db.execute("SELECT id,title,created_at,updated_at FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?", (limit,offset))
        return [dict(r) for r in await c.fetchall()]

    async def delete_session(self, sid):
        for t, col in [("llm_traces","session_id"),("messages","session_id"),("outline_states","session_id"),("sessions","id")]:
            await self._db.execute(f"DELETE FROM {t} WHERE {col}=?", (sid,))
        await self._db.commit()

    async def add_message(self, sid, role, content, msg_type="text", metadata=None):
        m = json.dumps(metadata, ensure_ascii=False) if metadata else None
        c = await self._db.execute("INSERT INTO messages(session_id,role,content,msg_type,metadata) VALUES(?,?,?,?,?)", (sid,role,content,msg_type,m))
        await self._db.execute("UPDATE sessions SET updated_at=? WHERE id=?", (datetime.now().isoformat(),sid))
        await self._db.commit(); return c.lastrowid

    async def get_messages(self, sid, limit=100):
        c = await self._db.execute("SELECT id,session_id,role,content,msg_type,metadata,created_at FROM messages WHERE session_id=? ORDER BY id ASC LIMIT ?", (sid,limit))
        results = []
        for r in await c.fetchall():
            d = dict(r)
            if d["metadata"]:
                try: d["metadata"] = json.loads(d["metadata"])
                except: d["metadata"] = None
            results.append(d)
        return results

    async def save_outline_state(self, sid, outline_json, anchor_info=None):
        o = json.dumps(outline_json, ensure_ascii=False); a = json.dumps(anchor_info, ensure_ascii=False) if anchor_info else None
        await self._db.execute("INSERT INTO outline_states(session_id,outline_json,anchor_info,updated_at) VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET outline_json=excluded.outline_json,anchor_info=excluded.anchor_info,updated_at=excluded.updated_at",
            (sid, o, a, datetime.now().isoformat()))
        await self._db.commit()

    async def get_outline_state(self, sid):
        c = await self._db.execute("SELECT outline_json,anchor_info,updated_at FROM outline_states WHERE session_id=?", (sid,))
        r = await c.fetchone()
        if not r: return None
        return {"outline_json":json.loads(r["outline_json"]),"anchor_info":json.loads(r["anchor_info"]) if r["anchor_info"] else None,"updated_at":r["updated_at"]}

    async def has_outline(self, sid):
        c = await self._db.execute("SELECT 1 FROM outline_states WHERE session_id=?", (sid,)); return await c.fetchone() is not None

    # ─── LLM 轨迹 ───

    async def save_llm_trace(self, session_id: str, trace_id: str, llm_type: str,
                              step_name: str, request_messages: list, response_content: str = "",
                              reasoning_content: str = "", model: str = "", temperature: float = 0.0,
                              elapsed_ms: float = 0.0, success: bool = True, error: str = "") -> int:
        """写入一条 LLM 调用轨迹。"""
        req_json = json.dumps(request_messages, ensure_ascii=False, default=str)
        c = await self._db.execute(
            "INSERT INTO llm_traces(session_id,trace_id,llm_type,step_name,request_messages,"
            "response_content,reasoning_content,model,temperature,elapsed_ms,success,error) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, trace_id, llm_type, step_name, req_json,
             response_content, reasoning_content, model, temperature, elapsed_ms, success, error)
        )
        await self._db.commit()
        return c.lastrowid

    async def get_llm_traces(self, session_id: str) -> list[dict]:
        """获取某个会话的所有 LLM 轨迹。"""
        c = await self._db.execute(
            "SELECT id,session_id,trace_id,llm_type,step_name,request_messages,"
            "response_content,reasoning_content,model,temperature,elapsed_ms,success,error,created_at "
            "FROM llm_traces WHERE session_id=? ORDER BY id ASC", (session_id,)
        )
        results = []
        for r in await c.fetchall():
            d = dict(r)
            try:
                d["request_messages"] = json.loads(d["request_messages"])
            except:
                pass
            results.append(d)
        return results
