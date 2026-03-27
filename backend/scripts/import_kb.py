"""知识库导入脚本：Excel → Neo4j 图结构 + FAISS 向量索引。

使用方法:
    cd backend && python scripts/import_kb.py --file ../data/knowledge_base.xlsx

Excel 格式要求:
    必填列: scene_name, subscene_name, dimension_name, item_name, indicator_name
    可选列: dimension_intro, scene_desc, subscene_desc, item_desc, indicator_desc
"""

import argparse
import asyncio
import logging
import sys
import os

# 添加 backend 目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from neo4j import AsyncGraphDatabase
from config import settings
from pipeline.faiss_retriever import FAISSRetriever
from services.embedding_service import EmbeddingService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def import_knowledge_base(excel_path: str) -> int:
    """
    从 Excel 导入知识库到 Neo4j 并构建 FAISS 向量索引。

    Args:
        excel_path: Excel 文件路径

    Returns:
        导入的实体总数
    """
    logger.info(f"开始导入知识库: {excel_path}")

    # 读取 Excel
    df = pd.read_excel(excel_path)
    required_cols = ["scene_name", "subscene_name", "dimension_name", "item_name", "indicator_name"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Excel 缺少必填列: {missing}")

    logger.info(f"Excel 读取完成: {len(df)} 行数据")

    # 连接 Neo4j
    driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )

    # 初始化服务
    embedding_svc = EmbeddingService(
        settings.EMBEDDING_BASE_URL, dim=settings.EMBEDDING_DIM
    )
    retriever = FAISSRetriever(dim=settings.EMBEDDING_DIM)

    entities = []  # 收集所有实体用于构建 FAISS 索引

    async with driver.session() as session:
        # 清空现有数据
        logger.info("清空 Neo4j 现有数据...")
        await session.run("MATCH (n) DETACH DELETE n")

        # 按行处理，五层实体合并去重写入
        seen: dict[tuple, str] = {}
        rel_map = {
            2: "HAS_SUBSCENE",
            3: "HAS_DIMENSION",
            4: "HAS_ITEM",
            5: "HAS_INDICATOR",
        }

        for row_idx, row in df.iterrows():
            path_def = [
                ("Scene", str(row["scene_name"]).strip(), 1, str(row.get("scene_desc", "") or "")),
                ("Subscene", str(row["subscene_name"]).strip(), 2, str(row.get("subscene_desc", "") or "")),
                ("Dimension", str(row["dimension_name"]).strip(), 3, str(row.get("dimension_intro", "") or "")),
                ("EvalItem", str(row["item_name"]).strip(), 4, str(row.get("item_desc", "") or "")),
                ("Indicator", str(row["indicator_name"]).strip(), 5, str(row.get("indicator_desc", "") or "")),
            ]

            parent_id = None
            for label, name, level, desc in path_def:
                if not name or name == "nan":
                    break

                key = (label, name)
                if key not in seen:
                    node_id = f"{label}_{len(seen)}"
                    await session.run(
                        f"CREATE (n:{label} {{id: $id, name: $name, level: $level, "
                        f"intro_text: $desc}})",
                        id=node_id,
                        name=name,
                        level=level,
                        desc=desc,
                    )
                    seen[key] = node_id
                    entities.append(
                        {"neo4j_id": node_id, "name": name, "level": level}
                    )

                node_id = seen[key]

                # 建立父子关系
                if parent_id and level in rel_map:
                    await session.run(
                        f"MATCH (a {{id:$pid}}), (b {{id:$cid}}) "
                        f"MERGE (a)-[:{rel_map[level]}]->(b)",
                        pid=parent_id,
                        cid=node_id,
                    )

                parent_id = node_id

            if (row_idx + 1) % 100 == 0:
                logger.info(f"Neo4j 写入进度: {row_idx + 1}/{len(df)} 行")

    logger.info(f"✅ 写入 Neo4j 完成，共 {len(entities)} 个实体")

    # 创建索引以加速查询
    async with driver.session() as session:
        for label in ["Scene", "Subscene", "Dimension", "EvalItem", "Indicator"]:
            await session.run(
                f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.id)"
            )
        logger.info("✅ Neo4j 索引创建完成")

    await driver.close()

    # 构建 FAISS 索引
    logger.info("⏳ 生成 Embedding...")
    texts = [e["name"] for e in entities]
    embeddings = await embedding_svc.get_embeddings_batch(texts, batch_size=32)

    retriever.build_index(entities, embeddings)

    # 确保目录存在
    os.makedirs(os.path.dirname(settings.FAISS_INDEX_PATH) or ".", exist_ok=True)
    retriever.save(settings.FAISS_INDEX_PATH, settings.FAISS_ID_MAP_PATH)
    logger.info(f"✅ FAISS 索引构建完成，共 {len(entities)} 条向量")

    return len(entities)


def main():
    parser = argparse.ArgumentParser(description="知识库导入脚本")
    parser.add_argument(
        "--file",
        type=str,
        default="../data/knowledge_base.xlsx",
        help="Excel 文件路径",
    )
    args = parser.parse_args()

    if not os.path.exists(args.file):
        logger.error(f"文件不存在: {args.file}")
        sys.exit(1)

    asyncio.run(import_knowledge_base(args.file))


if __name__ == "__main__":
    main()
