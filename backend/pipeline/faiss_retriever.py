import json, logging, faiss, numpy as np
from dataclasses import dataclass
logger = logging.getLogger(__name__)

@dataclass
class EntityNode:
    neo4j_id: str; name: str; level: int; score: float

class FAISSRetriever:
    def __init__(self, dim=1024):
        self.dim = dim; self.index = faiss.IndexFlatIP(dim); self.id_map = []

    def build_index(self, entities, embeddings):
        self.index = faiss.IndexFlatIP(self.dim); self.id_map = entities
        faiss.normalize_L2(embeddings); self.index.add(embeddings)

    def add_batch(self, embeddings: np.ndarray, entities: list[dict]):
        """
        增量写入。entities 格式同 build_index（可包含 neo4j_id/name/level 或 skill_dir）。
        写入后自动持久化（如果之前 load 过）。
        """
        if embeddings.shape[0] == 0:
            return
        faiss.normalize_L2(embeddings)
        self.index.add(embeddings)
        self.id_map.extend(entities)
        logger.info(f"FAISS add_batch: +{embeddings.shape[0]}, total={self.index.ntotal}")

    def save(self, ip, mp):
        faiss.write_index(self.index, ip)
        with open(mp,"w",encoding="utf-8") as f: json.dump(self.id_map, f, ensure_ascii=False, indent=2)

    def load(self, ip, mp):
        self.index = faiss.read_index(ip)
        with open(mp,"r",encoding="utf-8") as f: self.id_map = json.load(f)
        logger.info(f"FAISS: {self.index.ntotal} 向量")

    def search(self, qe, top_k=10, threshold=0.5):
        """知识库节点检索。"""
        if not self.index or self.index.ntotal == 0: return []
        scores, indices = self.index.search(qe, top_k)
        return [EntityNode(neo4j_id=self.id_map[i]["neo4j_id"], name=self.id_map[i]["name"],
                level=self.id_map[i]["level"], score=float(s))
                for s, i in zip(scores[0], indices[0]) if i != -1 and s >= threshold]

    @property
    def total(self): return self.index.ntotal if self.index else 0
