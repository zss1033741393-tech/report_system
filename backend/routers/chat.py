import logging, uuid
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from models.chat import ChatRequest
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["chat"])

def _agent():
    from main import app_state; return app_state["lead_agent"]
def _ch():
    from main import app_state; return app_state["chat_history"]

@router.post("/chat")
async def chat(req: ChatRequest, agent=Depends(_agent)):
    async def stream():
        async for chunk in agent.handle_message(req.session_id, req.message): yield f"data: {chunk}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","Connection":"keep-alive","X-Accel-Buffering":"no"})

@router.get("/sessions")
async def list_sessions(limit:int=50, offset:int=0, h=Depends(_ch)):
    return {"sessions": await h.list_sessions(limit, offset)}

@router.post("/sessions")
async def create_session(h=Depends(_ch)):
    return await h.create_session(str(uuid.uuid4()))

@router.get("/sessions/{sid}/messages")
async def get_messages(sid:str, limit:int=100, h=Depends(_ch)):
    return {"messages": await h.get_messages(sid, limit)}

@router.get("/sessions/{sid}/outline")
async def get_outline(sid:str, h=Depends(_ch)):
    s = await h.get_outline_state(sid); return s or {"outline_json":None,"anchor_info":None}

@router.delete("/sessions/{sid}")
async def delete_session(sid:str, h=Depends(_ch)):
    await h.delete_session(sid); return {"success":True}

@router.get("/sessions/{sid}/artifacts")
async def get_artifacts(sid: str, h=Depends(_ch)):
    """返回会话的结构化产物：大纲 JSON + 报告 HTML。

    前端用此端点替代遍历 messages[].metadata.report_html 的脆弱逻辑。
    """
    outline_state = await h.get_outline_state(sid)
    outline_json = (outline_state or {}).get("outline_json")
    anchor_info = (outline_state or {}).get("anchor_info")

    report_html = None
    report_title = None
    try:
        msgs = await h.get_messages(sid, limit=100)
        for m in reversed(msgs):
            meta = m.get("metadata") or {}
            if meta.get("report_html"):
                report_html = meta["report_html"]
                report_title = meta.get("report_title", "报告")
                break
    except Exception:
        pass

    return {
        "outline_json": outline_json,
        "anchor_info": anchor_info,
        "report": {"html": report_html, "title": report_title} if report_html else None,
    }
