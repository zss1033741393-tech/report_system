"""LLM 基础服务层。

complete_stream yield Dict:
  {"content": "..."} / {"reasoning_content": "..."} / {"error": "..."}

think_tag_mode:
  "qwen3": is_inside_think 初始 True（推理内容 + </think> + 回答内容）
  "r1":    is_inside_think 初始 False（<think> + 推理内容 + </think> + 回答内容）
  "none":  不解析标签，所有 content 直接输出
"""

import json
import logging
import re
from typing import AsyncGenerator, Dict, Optional

import aiohttp

from llm.config import LLMConfig
from utils.log_decorators import log_llm_complete_json, log_llm_stream

logger = logging.getLogger(__name__)
_trace = logging.getLogger("trace")


class LLMService:

    def __init__(
        self,
        base_url: str,
        default_model: str = "",
        api_key: str = "",
        proxy: str = "",
        ssl_verify: bool = True,
        timeout_connect: int = 60,
        timeout_read: int = 600,
        timeout_total: int = 660,
        think_tag_mode: str = "qwen3",
    ):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self._api_key = api_key
        self._proxy = proxy or None
        self._ssl_verify = ssl_verify
        self._timeout_connect = timeout_connect
        self._timeout_read = timeout_read
        self._timeout_total = timeout_total
        self.think_tag_mode = think_tag_mode
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            connector = aiohttp.TCPConnector(ssl=self._ssl_verify)
            self._session = aiohttp.ClientSession(headers=headers, connector=connector)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ─── 高层接口 ───

    async def complete(self, messages: list[dict], config: LLMConfig | None = None) -> str:
        """非流式，返回 content 文本，reasoning 记 trace。"""
        result = await self.complete_full(messages, config)
        return result["content"]

    async def complete_full(self, messages: list[dict], config: LLMConfig | None = None) -> dict:
        """非流式，返回 {"content": "...", "reasoning_content": "..."}。"""
        content_parts, reasoning_parts = [], []
        async for chunk in self.complete_stream(messages, config):
            if "content" in chunk:
                content_parts.append(chunk["content"])
            if "reasoning_content" in chunk:
                reasoning_parts.append(chunk["reasoning_content"])
            if "error" in chunk:
                raise RuntimeError(chunk["error"])
        reasoning_text = "".join(reasoning_parts)
        if reasoning_text:
            self._log_reasoning(config, reasoning_parts)
        return {"content": "".join(content_parts), "reasoning_content": reasoning_text}

    @log_llm_complete_json
    async def complete_json(self, messages: list[dict], config: LLMConfig | None = None) -> dict:
        cfg = config or LLMConfig()
        last_error = None
        for attempt in range(cfg.max_retry):
            try:
                raw = await self.complete(messages, cfg)
                return self._parse_json(raw)
            except (json.JSONDecodeError, ValueError) as e:
                last_error = e
                logger.warning(f"LLM JSON 解析失败 ({attempt + 1}/{cfg.max_retry}): {e}")
        raise ValueError(f"LLM JSON 解析失败，已重试 {cfg.max_retry} 次: {last_error}")

    # ─── 底层流式接口 ───

    @log_llm_stream
    async def complete_stream(
        self, messages: list[dict], config: LLMConfig | None = None
    ) -> AsyncGenerator[Dict, None]:
        cfg = config or LLMConfig()
        model = cfg.model or self.default_model

        payload = {
            "model": model,
            "messages": messages,
            "temperature": cfg.temperature,
            "top_p": cfg.top_p,
            "max_tokens": cfg.max_tokens,
            "stream": True,
        }
        if cfg.extra_payload:
            payload.update(cfg.extra_payload)

        timeout = aiohttp.ClientTimeout(
            connect=cfg.timeout_connect or self._timeout_connect,
            sock_read=cfg.timeout_read or self._timeout_read,
            total=cfg.timeout_total or self._timeout_total,
        )

        session = await self._get_session()
        request_kwargs = {"json": payload, "timeout": timeout}
        if self._proxy:
            request_kwargs["proxy"] = self._proxy

        # 初始值由 think_tag_mode 决定
        if self.think_tag_mode == "qwen3":
            is_inside_think = True
        else:
            is_inside_think = False
        parse_think = (self.think_tag_mode != "none")

        try:
            async with session.post(
                f"{self.base_url}/chat/completions", **request_kwargs
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    yield {"error": f"LLM 调用失败: status={resp.status}, body={error_text[:500]}"}
                    return

                buffer = bytearray()
                async for raw_bytes in resp.content:
                    buffer.extend(raw_bytes)

                    while b'\n' in buffer:
                        line_end = buffer.find(b'\n')
                        line_bytes = bytes(buffer[:line_end])
                        del buffer[:line_end + 1]

                        if not line_bytes.startswith(b'data:'):
                            continue

                        data_str = line_bytes[5:].strip()
                        if data_str == b'[DONE]':
                            return

                        try:
                            chunk_data = json.loads(data_str)
                            choices = chunk_data.get("choices", [{}])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {})
                            if not isinstance(delta, dict):
                                continue

                            output = {}

                            # 显式 reasoning_content 字段
                            if reasoning := delta.get("reasoning_content"):
                                output["reasoning_content"] = reasoning

                            # content 字段
                            if content := delta.get("content"):
                                if not parse_think:
                                    output["content"] = content
                                elif "<think>" in content and not is_inside_think:
                                    is_inside_think = True
                                    think_start = content.index("<think>")
                                    output["reasoning_content"] = content[think_start + 7:]
                                elif is_inside_think:
                                    if "</think>" in content:
                                        is_inside_think = False
                                        think_end = content.index("</think>")
                                        output["reasoning_content"] = content[:think_end]
                                        output["content"] = content[think_end + 8:]
                                    else:
                                        output["reasoning_content"] = content
                                else:
                                    output["content"] = content

                            if output:
                                yield output

                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

        except Exception as e:
            logger.error(f"LLM stream error: {e}")
            yield {"error": f"LLM 请求异常: {str(e)}"}

    # ─── 内部工具 ───

    def _log_reasoning(self, config, reasoning_parts):
        reasoning_text = "".join(reasoning_parts)
        _trace.debug(json.dumps({
            "event": "llm.reasoning_content",
            "model": (config.model if config else "") or self.default_model,
            "reasoning_length": len(reasoning_text),
            "reasoning_content": reasoning_text,
        }, ensure_ascii=False, default=str))

    async def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        config: LLMConfig | None = None,
    ) -> dict:
        """Native tool calling。

        返回:
          {
            "content": str,          # 最终文本（finish_reason=="stop"时）
            "tool_calls": [          # finish_reason=="tool_calls"时
              {"id": "...", "name": "...", "args": {...}}
            ],
            "finish_reason": "tool_calls" | "stop"
          }
        """
        cfg = config or LLMConfig()
        model = cfg.model or self.default_model

        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "temperature": cfg.temperature,
            "top_p": cfg.top_p,
            "max_tokens": cfg.max_tokens,
            "stream": True,
        }
        # tool calling 时禁用 thinking（避免干扰 tool_calls delta 解析）
        extra = {k: v for k, v in (cfg.extra_payload or {}).items() if k != "enable_thinking"}
        if extra:
            payload.update(extra)

        timeout = aiohttp.ClientTimeout(
            connect=cfg.timeout_connect or self._timeout_connect,
            sock_read=cfg.timeout_read or self._timeout_read,
            total=cfg.timeout_total or self._timeout_total,
        )

        session = await self._get_session()
        request_kwargs = {"json": payload, "timeout": timeout}
        if self._proxy:
            request_kwargs["proxy"] = self._proxy

        content_parts: list[str] = []
        # tool_calls 聚合：{index: {id, name, args_parts}}
        tc_map: dict[int, dict] = {}
        finish_reason = "stop"

        try:
            async with session.post(
                f"{self.base_url}/chat/completions", **request_kwargs
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"LLM tool-call 失败: status={resp.status}, body={error_text[:500]}")

                buffer = bytearray()
                async for raw_bytes in resp.content:
                    buffer.extend(raw_bytes)
                    while b"\n" in buffer:
                        line_end = buffer.find(b"\n")
                        line_bytes = bytes(buffer[:line_end])
                        del buffer[:line_end + 1]

                        if not line_bytes.startswith(b"data:"):
                            continue
                        data_str = line_bytes[5:].strip()
                        if data_str == b"[DONE]":
                            break

                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        choice = choices[0]
                        fr = choice.get("finish_reason")
                        if fr:
                            finish_reason = fr

                        delta = choice.get("delta", {})
                        if not isinstance(delta, dict):
                            continue

                        # 普通文本内容
                        if c := delta.get("content"):
                            content_parts.append(c)

                        # tool_calls delta 聚合
                        for tc_delta in delta.get("tool_calls") or []:
                            idx = tc_delta.get("index", 0)
                            if idx not in tc_map:
                                tc_map[idx] = {"id": "", "name": "", "args_parts": []}
                            entry = tc_map[idx]
                            if tc_id := tc_delta.get("id"):
                                entry["id"] = tc_id
                            func = tc_delta.get("function") or {}
                            if fn_name := func.get("name"):
                                entry["name"] = fn_name
                            if fn_args := func.get("arguments"):
                                entry["args_parts"].append(fn_args)

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"LLM complete_with_tools error: {e}")
            raise

        # 组装 tool_calls 结果
        tool_calls = []
        for idx in sorted(tc_map.keys()):
            entry = tc_map[idx]
            args_str = "".join(entry["args_parts"])
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {"_raw": args_str}
            tool_calls.append({
                "id": entry["id"] or f"call_{idx}",
                "name": entry["name"],
                "args": args,
            })

        return {
            "content": "".join(content_parts),
            "tool_calls": tool_calls,
            "finish_reason": finish_reason if finish_reason else ("tool_calls" if tool_calls else "stop"),
        }

    @staticmethod
    def _parse_json(raw: str) -> dict:
        s = raw.strip()

        # 1. ```json``` 代码块
        code_block = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', s, re.DOTALL)
        if code_block:
            s = code_block.group(1).strip()

        # 2. 直接解析
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass

        # 3. 嵌套 {} 块
        brace_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', s, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        # 4. 最外层 { 到 }
        first, last = s.find('{'), s.rfind('}')
        if first != -1 and last > first:
            try:
                return json.loads(s[first:last + 1])
            except json.JSONDecodeError:
                pass

        raise ValueError(f"无法从 LLM 输出中提取 JSON: {s[:200]}...")
