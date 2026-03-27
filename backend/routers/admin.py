import logging, os
from fastapi import APIRouter, HTTPException
from models.request import KBImportRequest
from models.response import ImportResult
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

@router.post("/kb/import", response_model=ImportResult)
async def import_kb(req: KBImportRequest):
    if not os.path.exists(req.excel_path): raise HTTPException(400, f"文件不存在: {req.excel_path}")
    try:
        from scripts.import_kb import import_knowledge_base
        count = await import_knowledge_base(req.excel_path)
        return ImportResult(success=True, entity_count=count, message=f"导入{count}个实体")
    except Exception as e: raise HTTPException(500, f"导入失败: {e}")

@router.post("/kb/reindex")
async def reindex():
    try:
        from main import app_state; from config import settings
        fr = app_state["faiss_retriever"]; fr.load(settings.FAISS_INDEX_PATH, settings.FAISS_ID_MAP_PATH)
        return {"success":True,"message":f"FAISS重载: {fr.total}条"}
    except Exception as e: raise HTTPException(500, f"重载失败: {e}")
