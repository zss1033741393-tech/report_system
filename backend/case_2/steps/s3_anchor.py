"""S3: 锚点选择 —— LLM 从候选节点中选出最合适的入口节点（锚点）。

锚点：用户问题在知识树上的"命中入口"，决定了子树展开的起点。
优先选 L2/L3 层节点作为锚点（框架层），避免过深（L5 太细）或过浅（L1 太宽）。
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

ANCHOR_PROMPT = """\
你是一个电信网络分析助手。根据用户的问题意图和候选知识节点，选出最合适的分析入口（锚点）。

## 用户问题
{query}

## 用户意图
- 关键主题：{topics}
- 核心关注：{focus}
- 范围：{scope}

## 候选知识节点
{candidates}

## 要求
从候选节点中选出 1-3 个最匹配的锚点节点。
- 若 scope=全局，优先选 L1 或 L2 层节点（覆盖面广）
- 若 scope=专项，优先选 L3 或 L4 层节点（针对性强）
- 选择依据：节点名称/描述与用户意图的相关性

输出 JSON：
```json
{{
  "anchors": [
    {{"id": "节点ID", "name": "节点名称", "reason": "选择原因（10字以内）"}}
  ]
}}
```
只输出 JSON，不加解释。
"""


async def run(query: str, intent: dict, candidates: list, llm_fn) -> list[dict]:
    """
    candidates: [(node_id, score, node), ...]
    返回锚点列表 [{"id": ..., "name": ..., "reason": ...}, ...]
    """
    if not candidates:
        logger.warning("[S3-锚点选择] 候选节点为空，无法选锚点")
        return []

    # 格式化候选节点展示给 LLM
    cand_lines = []
    for nid, score, node in candidates:
        cand_lines.append(
            f"- [{nid}] L{node['level']} {node['name']}：{node.get('description', '')[:60]}"
        )
    candidates_text = "\n".join(cand_lines)

    prompt = ANCHOR_PROMPT.format(
        query=query,
        topics=", ".join(intent.get("topics", [])),
        focus=intent.get("focus", ""),
        scope=intent.get("scope", "全局"),
        candidates=candidates_text,
    )
    logger.info(f"[S3-锚点选择] prompt ({len(prompt)}ch):\n{prompt}")

    raw = await llm_fn(prompt)
    logger.info(f"[S3-锚点选择] LLM 响应 ({len(raw)}ch): {raw[:600]}")

    # 提取 JSON
    code_block = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', raw, re.DOTALL)
    if code_block:
        raw = code_block.group(1).strip()

    try:
        result = json.loads(raw)
        anchors = result.get("anchors", [])
    except json.JSONDecodeError:
        logger.warning("[S3-锚点选择] JSON 解析失败，降级：取评分最高候选节点")
        top = candidates[0]
        anchors = [{"id": top[0], "name": top[2]["name"], "reason": "评分最高"}]

    logger.info(f"[S3-锚点选择] 选出 {len(anchors)} 个锚点:")
    for a in anchors:
        logger.info(f"  → {a['id']} {a['name']} ({a.get('reason', '')})")

    return anchors
