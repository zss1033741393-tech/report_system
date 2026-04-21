"""CLI 入口：python case_2/run.py "你的问题"

环境变量（与主系统共用 .env）：
  LLM_BASE_URL   OpenAI-compatible API 地址
  LLM_API_KEY    API Key
  LLM_MODEL      模型名称（默认 qwen3-235b-a22b）
  LLM_THINK_TAG_MODE  qwen3 | none（默认 none）
"""
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

# 将 backend/ 加入 sys.path，支持直接运行（无需 uvicorn）
_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

# 加载 .env（可选，若无 python-dotenv 则跳过）
try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND / ".env")
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("case_2.run")

import aiohttp

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8001/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "EMPTY")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-235b-a22b")
LLM_THINK_TAG_MODE = os.getenv("LLM_THINK_TAG_MODE", "none")


async def _call_llm(prompt: str) -> str:
    """轻量 LLM 调用，不依赖 LLMService，直接调用 OpenAI-compatible API。"""
    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1500,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    choice = data["choices"][0]
    content = choice["message"].get("content", "") or ""
    reasoning = choice["message"].get("reasoning_content", "") or ""

    # qwen3 think 模式：content 可能为空，fallback 到 reasoning
    if LLM_THINK_TAG_MODE == "qwen3":
        if not content.strip() and reasoning.strip():
            logger.warning("[llm] content 为空，从 reasoning 提取（qwen3 think 模式）")
            content = reasoning
        elif not content.strip():
            # 尝试从 content 中去除 <think>...</think> 标签
            content_raw = choice["message"].get("content", "") or ""
            cleaned = re.sub(r'<think>.*?</think>', '', content_raw, flags=re.DOTALL).strip()
            content = cleaned if cleaned else reasoning

    return content


async def main():
    if len(sys.argv) < 2:
        print("用法: python case_2/run.py \"你的问题\"")
        print("示例: python case_2/run.py \"我想了解fgOTN的部署情况\"")
        sys.exit(1)

    query = sys.argv[1]

    from case_2.workflow import run
    result = await run(query, _call_llm)

    print("\n" + "=" * 60)
    print("【分析框架大纲】")
    print("=" * 60)
    print(result["markdown"])
    print("=" * 60)

    if "--debug" in sys.argv:
        print("\n【意图解析】")
        print(json.dumps(result["intent"], ensure_ascii=False, indent=2))
        print("\n【选中锚点】")
        print(json.dumps(result["anchors"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
