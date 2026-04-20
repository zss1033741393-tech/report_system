"""审核路由 —— 管理 user_defined 节点的审核工作流。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/outlines", tags=["review"])


def _get_review_service(request: Request):
    svc = request.app.state.review_service
    if not svc:
        raise HTTPException(status_code=503, detail="review_service 未初始化")
    return svc


class RejectBody(BaseModel):
    reason: str = ""


@router.get("/pending")
async def list_pending_outlines(review_svc=Depends(_get_review_service)):
    """列出所有待审核大纲。"""
    items = await review_svc.list_pending_outlines()
    return {"outlines": items, "total": len(items)}


@router.get("/pending/nodes")
async def list_pending_nodes(review_svc=Depends(_get_review_service)):
    """列出所有待审核节点。"""
    items = await review_svc.list_pending_nodes()
    return {"nodes": items, "total": len(items)}


@router.post("/{outline_id}/approve")
async def approve_outline(outline_id: str, review_svc=Depends(_get_review_service)):
    """审核通过大纲：所有 draft 节点写入 Neo4j，大纲状态改为 active。"""
    result = await review_svc.approve_outline(outline_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/{outline_id}/reject")
async def reject_outline(
    outline_id: str,
    body: RejectBody,
    review_svc=Depends(_get_review_service),
):
    """拒绝大纲，状态改为 rejected。"""
    result = await review_svc.reject_outline(outline_id, reason=body.reason)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/nodes/{node_id}/approve")
async def approve_node(node_id: str, review_svc=Depends(_get_review_service)):
    """单独审核通过一个节点并写入 Neo4j。"""
    result = await review_svc.approve_node(node_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result
