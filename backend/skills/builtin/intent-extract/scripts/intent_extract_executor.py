"""意图提取与双路径检索执行器。

替代原 skill-factory Step1（IntentUnderstand）+ Step2（StructExtract），
去除 Step2 中的 LLM 调用，改为纯算法路径判断。
"""
import json
import logging
from typing import AsyncGenerator, Union

from agent.context import SkillContext, SkillResult
from llm.agent_llm import AgentLLM
from llm.config import SKILL_FACTORY_JSON_CONFIG

logger = logging.getLogger(__name__)

_INTENT_PROMPT = """你是看网逻辑分析专家。分析看网逻辑文本，提取结构化信息。

## 输出格式
```json
{"scene_intro":"50字以内","keywords":["3-5个关键词"],"query_variants":["3种用户问法"],"skill_name":"英文下划线"}
```

## 示例
输入: "从传送网络容量角度分析fgOTN部署机会"
```json
{"scene_intro":"分析fgOTN传送网络容量，评估部署机会","keywords":["fgOTN","传送网络","容量分析","部署"],"query_variants":["帮我分析fgOTN网络容量","fgOTN部署机会分析","传送网络容量评估"],"skill_name":"fgOTN_Capacity_Analysis"}
```

## 看网逻辑
{raw_input}

用 ```json ``` 代码块包裹输出。"""


def _ts(step, status, detail, data=None):
    p = {"type": "thinking_step", "step": step, "status": status, "detail": detail}
    if data:
        p["data"] = data
    return json.dumps(p, ensure_ascii=False)


def _design(step, status):
    return json.dumps({"type": "design_step", "step": step, "status": status}, ensure_ascii=False)


class IntentExtractExecutor:
    """意图提取 + 双路径检索执行器（Step1 LLM + Step2 纯算法）。"""

    def __init__(self, llm_service, embedding_service, faiss_retriever,
                 neo4j_retriever, session_service, kb_store,
                 top_k: int = 20, score_threshold: float = 0.3,
                 l14_confidence_threshold: float = 0.7):
        self._llm = llm_service
        self._emb = embedding_service
        self._faiss = faiss_retriever
        self._neo4j = neo4j_retriever
        self._session = session_service
        self._kb = kb_store
        self._top_k = top_k
        self._threshold = score_threshold
        self._l14_threshold = l14_confidence_threshold

    async def execute(self, ctx: SkillContext) -> AsyncGenerator[Union[str, SkillResult], None]:
        expert_input = ctx.params.get("expert_input", ctx.user_message)
        if not expert_input:
            yield SkillResult(False, "缺少 expert_input 参数")
            return

        # ── Step 1：意图提取（LLM）──
        yield _design("intent_understand", "running")
        yield _ts("intent_extract", "running", "正在分析看网逻辑意图...")
        intent = await self._extract_intent(expert_input, ctx.trace_callback)
        yield _ts("intent_extract", "done", f"意图提取完成: {intent.get('scene_intro', '')[:30]}")
        yield _design("intent_understand", "done")

        # ── Step 2：语义检索（纯算法）──
        yield _design("struct_extract", "running")
        query = (intent["scene_intro"] + " " + " ".join(intent.get("keywords", []))).strip() or expert_input[:200]
        yield _ts("semantic_search", "running", "正在向量化检索知识库...")
        qe = await self._emb.get_embedding(query)
        cands = self._faiss.search(qe, self._top_k, self._threshold)
        yield _ts("semantic_search", "done", f"找到 {len(cands)} 个候选节点")

        if not cands:
            yield _design("struct_extract", "done")
            yield SkillResult(True, "检索无结果，走路径B（自底向上）",
                              data={"path": "no_match", "intent": intent,
                                    "bottom_up": {"indicators": [], "kb_contents": {}, "existing_l3l4": []}})
            return

        # 获取祖先路径
        yield _ts("path_analysis", "running", "分析节点路径...")
        ancestor_paths = await self._neo4j.get_ancestor_paths([c.neo4j_id for c in cands])
        yield _ts("path_analysis", "done", f"{len(ancestor_paths)} 条路径")

        # ── Step 3：路径判断（纯算法，无 LLM）──
        # 构建 neo4j_id → score 映射
        score_map = {c.neo4j_id: c.score for c in cands}

        # 检查是否有 L1~L4 高置信度命中
        l14_hits = [
            n for n in ancestor_paths
            if n.get("level", 5) <= 4 and score_map.get(n["id"], 0) >= self._l14_threshold
        ]
        l5_hits = [n for n in ancestor_paths if n.get("level") == 5]

        yield _design("struct_extract", "done")

        if l14_hits:
            # 路径 A：自顶向下
            best = max(l14_hits, key=lambda x: score_map.get(x["id"], 0))
            yield _ts("path_decision", "done",
                      f"路径A（自顶向下）: 锚点「{best['name']}」(L{best['level']}) score={score_map.get(best['id'], 0):.2f}")
            yield _design("outline_design", "running")
            subtree = await self._neo4j.get_subtree(best["id"])
            yield _design("outline_design", "done")
            yield SkillResult(True, f"路径A: 命中「{best['name']}」",
                              data={
                                  "path": "top_down",
                                  "intent": intent,
                                  "top_down": {
                                      "anchor": {"id": best["id"], "name": best["name"], "level": best["level"]},
                                      "subtree": subtree,
                                  },
                              })
        elif l5_hits:
            # 路径 B：自底向上——收集 L5 + KB 内容 + 已有 L3/L4
            yield _ts("path_decision", "done",
                      f"路径B（自底向上）: 仅命中 {len(l5_hits)} 个 L5 指标节点")
            # 按 score 降序，最多取 15 个（token 预算控制）
            l5_sorted = sorted(l5_hits, key=lambda x: score_map.get(x["id"], 0), reverse=True)[:15]
            kb_contents = {}
            for node in l5_sorted:
                try:
                    content = await self._kb.get(node["id"])
                    if content:
                        kb_contents[node["id"]] = content
                except Exception as e:
                    logger.debug(f"KB 内容加载失败 {node['id']}: {e}")

            # 收集已有 L3/L4 节点，供 LLM 组织大纲时优先复用
            existing_l3l4 = [
                {"id": n["id"], "name": n["name"], "level": n["level"]}
                for n in ancestor_paths if n.get("level") in (3, 4)
            ]
            # 去重
            seen = set()
            existing_l3l4 = [
                x for x in existing_l3l4
                if not (x["id"] in seen or seen.add(x["id"]))
            ]

            yield SkillResult(True, f"路径B: {len(l5_sorted)} 个 L5 指标",
                              data={
                                  "path": "bottom_up",
                                  "intent": intent,
                                  "bottom_up": {
                                      "indicators": [
                                          {"id": n["id"], "name": n["name"], "level": n["level"],
                                           "score": score_map.get(n["id"], 0)}
                                          for n in l5_sorted
                                      ],
                                      "kb_contents": kb_contents,
                                      "existing_l3l4": existing_l3l4,
                                  },
                              })
        else:
            # 所有命中节点 score 均低于阈值
            yield SkillResult(True, "未找到高置信度匹配，走路径B",
                              data={"path": "no_match", "intent": intent,
                                    "bottom_up": {"indicators": [], "kb_contents": {}, "existing_l3l4": []}})

    async def _extract_intent(self, raw_input: str, trace_callback=None) -> dict:
        """LLM 提取意图结构。"""
        prompt = _INTENT_PROMPT.format(raw_input=raw_input)
        agent = AgentLLM(self._llm, "", SKILL_FACTORY_JSON_CONFIG,
                         trace_callback=trace_callback,
                         llm_type="intent_extract", step_name="intent_extract")
        try:
            result = await agent.chat_json(prompt)
            return {
                "scene_intro": result.get("scene_intro", ""),
                "keywords": result.get("keywords", []),
                "query_variants": result.get("query_variants", [])[:5],
                "skill_name": result.get("skill_name", "unnamed_skill"),
            }
        except Exception as e:
            logger.warning(f"意图提取 LLM 失败: {e}")
            return {"scene_intro": "", "keywords": [], "query_variants": [], "skill_name": "unnamed_skill"}
