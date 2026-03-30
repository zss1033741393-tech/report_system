import logging, os
from fastapi import APIRouter, HTTPException, Depends
from models.request import KBImportRequest
from models.response import ImportResult
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

def _ch():
    from main import app_state; return app_state["chat_history"]

@router.post("/kb/import", response_model=ImportResult)
async def import_kb(req: KBImportRequest):
    if not os.path.exists(req.excel_path): raise HTTPException(400, f"文件不存在: {req.excel_path}")
    try:
        from scripts.import_kb import import_knowledge_base
        count = await import_knowledge_base(req.excel_path)
        return ImportResult(success=True, entity_count=count, message=f"导入{count}个实体")
    except Exception as e: raise HTTPException(500, f"导入失败: {e}")

@router.get("/sessions/{sid}/traces")
async def get_traces(sid: str, h=Depends(_ch)):
    """获取会话的完整调用轨迹：LLM 调用 + 工具执行。"""
    llm_traces = await h.get_llm_traces(sid)
    tool_traces = await h.get_tool_traces(sid)
    return {"session_id": sid, "llm_traces": llm_traces, "tool_traces": tool_traces}


@router.post("/kb/reindex")
async def reindex():
    try:
        from main import app_state; from config import settings
        fr = app_state["faiss_retriever"]; fr.load(settings.FAISS_INDEX_PATH, settings.FAISS_ID_MAP_PATH)
        return {"success":True,"message":f"FAISS重载: {fr.total}条"}
    except Exception as e: raise HTTPException(500, f"重载失败: {e}")
