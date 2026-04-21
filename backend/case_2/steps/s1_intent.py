"""S1: 意图解析 —— LLM 将用户自然语言问题转为结构化意图。

输出：
  {
    "topics": ["关键主题词1", "关键主题词2"],
    "focus": "用户最关注的核心方向（一句话）",
    "scope": "全局" | "专项"   # 全局=整体框架, 专项=某具体问题
  }
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

INTENT_PROMPT = """\
你是一个电信网络分析助手。用户输入了一个关于政企OTN网络的问题，请解析意图。

## 用户问题
{query}

## 要求
分析用户想了解什么，输出如下 JSON：
```json
{{
  "topics": ["关键主题词，来自原文或领域术语，3-6个"],
  "focus": "用户最核心的关注点，一句话20字以内",
  "scope": "全局或专项"
}}
```
- topics：提取用户关注的关键词，可包含：OTN、fgOTN、量子加密、覆盖、容量、槽位、交叉、企业分布等
- scope：若用户问整体框架/全貌则为"全局"，若聚焦某一具体子问题则为"专项"

只输出 JSON，不加解释。
"""


async def run(query: str, llm_fn) -> dict:
    """
    llm_fn: async callable(prompt: str) -> str
    """
    prompt = INTENT_PROMPT.format(query=query)
    logger.info(f"[S1-意图解析] prompt ({len(prompt)}ch):\n{prompt}")

    raw = await llm_fn(prompt)
    logger.info(f"[S1-意图解析] LLM 响应 ({len(raw)}ch): {raw[:600]}")

    # 提取 JSON
    code_block = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', raw, re.DOTALL)
    if code_block:
        raw = code_block.group(1).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"[S1-意图解析] JSON 解析失败，降级为默认意图")
        result = {"topics": [query], "focus": query, "scope": "全局"}

    logger.info(f"[S1-意图解析] 解析结果: topics={result.get('topics')}, scope={result.get('scope')}, focus={result.get('focus')!r}")
    return result
