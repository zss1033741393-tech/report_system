"""report_sdk —— Skill 脚本的共享基础设施包。

各客户端通过 init() 方法绑定具体服务实例，Skill 脚本无需关心底层服务从何而来。

使用示例（在 Executor 构造函数中）：
    from vendor.report_sdk import neo4j_client, faiss_client, outline_db
    neo4j_client.init(neo4j_retriever_instance)
    faiss_client.init(faiss_retriever_instance)
    outline_db.init(outline_store_instance)
"""
from vendor.report_sdk import (  # noqa: F401
    neo4j_client,
    faiss_client,
    kb_store_client,
    embedding_client,
    outline_db,
)
