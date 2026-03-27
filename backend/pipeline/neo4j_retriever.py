import logging
from typing import Optional
from neo4j import AsyncGraphDatabase
logger = logging.getLogger(__name__)
_R = "HAS_SUBSCENE|HAS_DIMENSION|HAS_ITEM|HAS_INDICATOR"

class Neo4jRetriever:
    def __init__(self, uri, user, password):
        self.driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self): await self.driver.close()

    async def verify_connectivity(self):
        async with self.driver.session() as s:
            r = await s.run("RETURN 1 AS ok"); return (await r.single())["ok"] == 1

    async def get_ancestor_paths(self, node_ids):
        q = f"""UNWIND $ids AS nid MATCH (t) WHERE t.id=nid
        MATCH path=(root)-[:{_R}*0..]->(t) WHERE NOT EXISTS{{MATCH(a)-[:{_R}]->(root)}}
        RETURN t.id AS id, t.name AS name, t.level AS level, [n IN nodes(path)|n.name] AS pn"""
        async with self.driver.session() as s:
            result = await s.run(q, ids=node_ids)
            return [{"id":r["id"],"name":r["name"],"level":r["level"],"path":" > ".join(r["pn"])} async for r in result]

    async def get_subtree(self, node_id):
        q = f"MATCH path=(root)-[:{_R}*0..]->(d) WHERE root.id=$nid RETURN path ORDER BY length(path)"
        async with self.driver.session() as s:
            result = await s.run(q, nid=node_id); tree = await self._tree(result, node_id)
            # 诊断日志：打印子树层级结构
            self._log_tree_structure(tree)
            return tree

    def _log_tree_structure(self, node, depth=0):
        """递归打印子树结构用于诊断。"""
        if not node:
            return
        prefix = "  " * depth
        logger.info(f"SUBTREE: {prefix}L{node.get('level',0)} {node.get('name','')} (id={node.get('id','')} children={len(node.get('children',[]))})")
        for c in node.get("children", []):
            self._log_tree_structure(c, depth + 1)

    async def get_ancestor_chain(self, node_id):
        ll = {2:"子场景层",3:"评估维度层",4:"评估项层"}
        q = f"""MATCH path=(root)-[:{_R}*]->(t) WHERE t.id=$nid
        WITH [n IN nodes(path)|n] AS ns UNWIND ns AS n WITH n WHERE n.level IN [2,3,4]
        RETURN DISTINCT n.id AS id, n.name AS name, n.level AS level ORDER BY n.level"""
        async with self.driver.session() as s:
            result = await s.run(q, nid=node_id)
            return [{"id":r["id"],"name":r["name"],"level":r["level"],"label":ll.get(r["level"],"")} async for r in result]

    async def get_node_by_id(self, nid):
        async with self.driver.session() as s:
            r = await s.run("MATCH(n) WHERE n.id=$nid RETURN n.id AS id,n.name AS name,n.level AS level,n.intro_text AS it", nid=nid)
            rec = await r.single()
            return {"id":rec["id"],"name":rec["name"],"level":rec["level"],"intro_text":rec.get("it","")} if rec else None

    async def get_entity_count(self):
        async with self.driver.session() as s:
            r = await s.run("MATCH(n) RETURN count(n) AS c"); return (await r.single())["c"]

    async def _tree(self, result, root_id):
        nodes, edges = {}, set()
        async for rec in result:
            p = rec["path"]
            for nd in p.nodes:
                nid = nd["id"]
                if nid not in nodes: nodes[nid] = {"id":nid,"name":nd["name"],"level":nd["level"],"intro_text":nd.get("intro_text",""),"children":[]}
            for rl in p.relationships:
                pid, cid = rl.start_node["id"], rl.end_node["id"]
                if (pid,cid) not in edges and pid in nodes and cid in nodes:
                    nodes[pid]["children"].append(nodes[cid]); edges.add((pid,cid))
        return nodes.get(root_id, {})

    # ─── 写入方法（skill-persist 使用）───

    async def set_skill_path(self, node_id: str, skill_path: str):
        """在节点上挂载 skill_path 属性。"""
        async with self.driver.session() as s:
            await s.run(
                "MATCH (n) WHERE n.id=$nid SET n.skill_path=$sp, n.has_skill=true",
                nid=node_id, sp=skill_path,
            )
        logger.info(f"Neo4j set_skill_path: {node_id} → {skill_path}")

    async def create_nodes_and_relations(self, nodes: list[dict]):
        """
        批量创建节点和关系（Zero-Shot 沉淀时使用）。

        nodes 格式:
        [{"id":"n1","name":"xxx","level":3,"label":"Dimension","parent_id":"n0","rel_type":"HAS_DIMENSION"}]
        """
        _rel_map = {"HAS_SUBSCENE","HAS_DIMENSION","HAS_ITEM","HAS_INDICATOR"}
        async with self.driver.session() as s:
            for node in nodes:
                label = node.get("label", "Dimension")
                await s.run(
                    f"MERGE (n:{label} {{id:$id}}) SET n.name=$name, n.level=$level",
                    id=node["id"], name=node["name"], level=node["level"],
                )
                pid = node.get("parent_id")
                rel = node.get("rel_type")
                if pid and rel and rel in _rel_map:
                    await s.run(
                        f"MATCH (a {{id:$pid}}),(b {{id:$cid}}) MERGE (a)-[:{rel}]->(b)",
                        pid=pid, cid=node["id"],
                    )
        logger.info(f"Neo4j create_nodes_and_relations: {len(nodes)} nodes")
