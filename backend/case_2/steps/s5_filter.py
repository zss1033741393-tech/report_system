"""S5: 大纲裁剪 —— LLM 根据用户问题对子树进行精简，复用 outline_ops。

与 OutlineClipExecutor / GraphRAGExecutor 的 Step 6.5 逻辑一致：
  LLM 返回 instructions: [{type: delete_node|keep_only, target_name}]
  本地执行操作，无需再次调用 LLM。
"""
import copy
import json
import logging
import re
import sys
from pathlib import Path

# 使 outline_ops 可在独立脚本和 FastAPI 两种运行环境下均可 import
_BACKEND = Path(__file__).parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from tools.executors.outline_ops import collect_nodes_text, delete_node, keep_only

logger = logging.getLogger(__name__)

CLIP_PROMPT = """\
你是一个电信网络分析助手。根据用户问题，对以下大纲结构进行裁剪，去除不相关的部分。

## 用户问题
{query}

## 当前大纲节点（跳过 L5 细节）
{nodes_text}

## 裁剪规则
- 如果用户问题聚焦于某个具体方向，删除无关节点
- 如果用户问整体框架，尽量保留所有节点
- 操作类型：
  - delete_node：删除指定名称的节点及其子树
  - keep_only：只保留指定名称的节点（及其祖先/后代路径）

## 输出格式（严格 JSON）
```json
{{
  "clip_needed": true或false,
  "reason": "裁剪原因（10字以内）",
  "instructions": [
    {{"type": "delete_node", "target_name": "节点名称"}},
    {{"type": "keep_only", "target_name": "节点名称"}}
  ]
}}
```
- 若不需要裁剪，clip_needed=false，instructions 为空数组
- 每条 instruction 操作一个节点，按顺序执行

只输出 JSON，不加解释。
"""


async def run(query: str, subtree: dict, llm_fn) -> dict:
    """
    对子树进行 LLM 裁剪。
    返回裁剪后的子树（原树 deepcopy，不修改原始数据）。
    """
    working = copy.deepcopy(subtree)

    nodes_text = collect_nodes_text(working, skip_l5=True, max_depth=4)
    prompt = CLIP_PROMPT.format(query=query, nodes_text=nodes_text)
    logger.info(f"[S5-大纲裁剪] prompt ({len(prompt)}ch):\n{prompt}")

    raw = await llm_fn(prompt)
    logger.info(f"[S5-大纲裁剪] LLM 响应 ({len(raw)}ch): {raw[:600]}")

    # 提取 JSON
    code_block = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', raw, re.DOTALL)
    if code_block:
        raw = code_block.group(1).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[S5-大纲裁剪] JSON 解析失败，跳过裁剪")
        return working

    if not result.get("clip_needed", False):
        logger.info(f"[S5-大纲裁剪] 无需裁剪: {result.get('reason', '')}")
        return working

    instructions = result.get("instructions", [])
    logger.info(f"[S5-大纲裁剪] 解析到 {len(instructions)} 条操作: {instructions}")

    for inst in instructions:
        op = inst.get("type")
        target = inst.get("target_name", "")
        if not target:
            continue
        if op == "delete_node":
            working = delete_node(working, target)
            logger.info(f"[S5-大纲裁剪] 删除节点: {target!r}")
        elif op == "keep_only":
            working = keep_only(working, {target})
            logger.info(f"[S5-大纲裁剪] 保留节点: {target!r}")
        else:
            logger.warning(f"[S5-大纲裁剪] 未知操作类型: {op!r}")

    return working
