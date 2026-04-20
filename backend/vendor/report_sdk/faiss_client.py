"""FAISS 检索客户端封装。"""
_retriever = None


def init(faiss_retriever):
    global _retriever
    _retriever = faiss_retriever


def _check():
    if _retriever is None:
        raise RuntimeError("faiss_client 未初始化，请先调用 init()")


def search(embedding: list, top_k: int = 10, threshold: float = 0.5) -> list:
    _check()
    return _retriever.search(embedding, top_k, threshold)


def add_batch(node_ids: list, embeddings: list):
    _check()
    return _retriever.add_batch(node_ids, embeddings)


def save(index_path: str, id_map_path: str):
    _check()
    return _retriever.save(index_path, id_map_path)
