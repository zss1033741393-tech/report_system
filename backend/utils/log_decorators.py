"""LLM 调用日志装饰器。"""
import functools
import time
import json
import logging
from typing import AsyncGenerator, Dict

logger = logging.getLogger(__name__)
_trace = logging.getLogger("trace")


def _rec(method, msgs, cfg, resp, elapsed, err=None):
    c = {"model": getattr(cfg, "model", ""), "temperature": getattr(cfg, "temperature", 0)} if cfg else {}
    r = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": f"llm.{method}", "elapsed_ms": round(elapsed, 2),
         "data": {"config": c, "messages": msgs, "response": resp, "error": err}}
    _trace.debug(json.dumps(r, ensure_ascii=False, default=str))


def log_llm_complete_json(func):
    @functools.wraps(func)
    async def wrapper(self, msgs, cfg=None):
        t0, err, resp = time.perf_counter(), None, ""
        try:
            result = await func(self, msgs, cfg)
            resp = json.dumps(result, ensure_ascii=False, default=str)
            return result
        except Exception as e:
            err = str(e)
            raise
        finally:
            el = (time.perf_counter() - t0) * 1000
            _rec("json", msgs, cfg, resp, el, err)
            logger.info(f"LLM json {'OK' if not err else 'ERR'} ({el:.0f}ms)")
    return wrapper


def log_llm_stream(func):
    """装饰 complete_stream（yield Dict 的流式接口）。"""
    @functools.wraps(func)
    async def wrapper(self, msgs, cfg=None, **kwargs) -> AsyncGenerator[Dict, None]:
        t0 = time.perf_counter()
        content_parts, reasoning_parts, err = [], [], None
        try:
            async for chunk in func(self, msgs, cfg, **kwargs):
                # 收集用于日志记录
                if isinstance(chunk, dict):
                    if "content" in chunk:
                        content_parts.append(chunk["content"])
                    if "reasoning_content" in chunk:
                        reasoning_parts.append(chunk["reasoning_content"])
                yield chunk
        except Exception as e:
            err = str(e)
            raise
        finally:
            el = (time.perf_counter() - t0) * 1000
            content_text = "".join(content_parts)
            reasoning_text = "".join(reasoning_parts)
            resp_summary = content_text
            if reasoning_text:
                resp_summary = f"[reasoning:{len(reasoning_text)}ch] {content_text}"
            _rec("stream", msgs, cfg, resp_summary, el, err)
            logger.info(
                f"LLM stream {'OK' if not err else 'ERR'} "
                f"({el:.0f}ms, content={len(content_text)}ch"
                f"{f', reasoning={len(reasoning_text)}ch' if reasoning_text else ''})"
            )
    return wrapper
