"""Embedding 服务客户端封装。"""
_service = None


def init(embedding_service):
    global _service
    _service = embedding_service


def _check():
    if _service is None:
        raise RuntimeError("embedding_client 未初始化，请先调用 init()")


async def get_embedding(text: str) -> list:
    _check()
    return await _service.get_embedding(text)
