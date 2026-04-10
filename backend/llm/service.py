"""LLM 基础服务层。

complete_stream yield Dict:
  {"content": "..."} / {"reasoning_content": "..."} / {"error": "..."}
  {"tool_calls": [{"id":..., "name":..., "arguments": {...}}]}  # 工具调用（在 [DONE] 前一次性 yield）

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

    async def complete_full(
        self,
        messages: list[dict],
        config: LLMConfig | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        """非流式，返回 {"content": "...", "reasoning_content": "...", "tool_calls": [...]}。"""
        content_parts, reasoning_parts, tool_calls = [], [], []
        async for chunk in self.complete_stream(messages, config, tools=tools):
            if "content" in chunk:
                content_parts.append(chunk["content"])
            if "reasoning_content" in chunk:
                reasoning_parts.append(chunk["reasoning_content"])
            if "tool_calls" in chunk:
                tool_calls = chunk["tool_calls"]
            if "error" in chunk:
                raise RuntimeError(chunk["error"])
        reasoning_text = "".join(reasoning_parts)
        if reasoning_text:
            self._log_reasoning(config, reasoning_parts)
        return {
            "content": "".join(content_parts),
            "reasoning_content": reasoning_text,
            "tool_calls": tool_calls,
        }

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
        self,
        messages: list[dict],
        config: LLMConfig | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[Dict, None]:
        cfg = config or LLMConfig()
        use_stream = cfg.stream

        model = cfg.model or self.default_model

        payload = {
            "model": model,
            "messages": messages,
            "temperature": cfg.temperature,
            "top_p": cfg.top_p,
            "max_tokens": cfg.max_tokens,
            "stream": use_stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
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

        if use_stream:
            async for chunk in self._do_stream(session, request_kwargs, cfg):
                yield chunk
        else:
            async for chunk in self._do_non_stream(session, request_kwargs):
                yield chunk

    # ─── 流式 HTTP 请求 ───

    async def _do_stream(
        self, session: aiohttp.ClientSession,
        request_kwargs: dict, cfg: LLMConfig,
    ) -> AsyncGenerator[Dict, None]:
        """流式请求，逐 chunk yield。"""
        # 工具调用累积缓冲（index → {id, name, arguments_parts}）
        _tc_buf: dict[int, dict] = {}

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
                _stream_done = False
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
                            _stream_done = True
                            break

                        try:
                            chunk_data = json.loads(data_str)
                            choices = chunk_data.get("choices", [{}])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {})
                            if not isinstance(delta, dict):
                                continue

                            output = {}

                            # ── 工具调用累积 ──
                            if tc_list := delta.get("tool_calls"):
                                for tc in tc_list:
                                    idx = tc.get("index", 0)
                                    if idx not in _tc_buf:
                                        _tc_buf[idx] = {"id": "", "name": "", "arguments": []}
                                    entry = _tc_buf[idx]
                                    if tc_id := tc.get("id"):
                                        entry["id"] = tc_id
                                    fn = tc.get("function", {})
                                    if fn_name := fn.get("name"):
                                        entry["name"] = fn_name
                                    if fn_args := fn.get("arguments"):
                                        entry["arguments"].append(fn_args)
                                # 有 tool_calls 就跳过 content 处理
                                continue

                            # ── 显式 reasoning_content 字段 ──
                            if reasoning := delta.get("reasoning_content"):
                                output["reasoning_content"] = reasoning

                            # ── content 字段 ──
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

                        except (json.JSONDecodeError, KeyError, IndexError) as e:
                            logger.warning(f"LLM chunk 解析失败（跳过）: {e}")
                            continue

                    if _stream_done:
                        break

                # 流式结束：flush 累积的 tool_calls
                if _tc_buf:
                    tool_calls = []
                    for idx in sorted(_tc_buf.keys()):
                        entry = _tc_buf[idx]
                        args_str = "".join(entry["arguments"])
                        try:
                            args = json.loads(args_str) if args_str else {}
                        except json.JSONDecodeError:
                            args = {"_raw": args_str}
                        tool_calls.append({
                            "id": entry["id"],
                            "name": entry["name"],
                            "arguments": args,
                        })
                    yield {"tool_calls": tool_calls}

        except Exception as e:
            logger.error(f"LLM stream error: {e}")
            yield {"error": f"LLM 请求异常: {str(e)}"}

    # ─── 非流式 HTTP 请求 ───

    async def _do_non_stream(
        self, session: aiohttp.ClientSession,
        request_kwargs: dict,
    ) -> AsyncGenerator[Dict, None]:
        """非流式请求，一次性拿到完整响应后转换为与流式相同的 yield 格式。"""
        try:
            async with session.post(
                f"{self.base_url}/chat/completions", **request_kwargs
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    yield {"error": f"LLM 调用失败: status={resp.status}, body={error_text[:500]}"}
                    return

                body = await resp.json()
                choices = body.get("choices", [])
                if not choices:
                    yield {"error": "LLM 返回空 choices"}
                    return

                message = choices[0].get("message", {})

                # ── reasoning_content ──
                if reasoning := message.get("reasoning_content"):
                    yield {"reasoning_content": reasoning}

                # ── content（think 标签解析） ──
                content = message.get("content") or ""
                if content:
                    parse_think = (self.think_tag_mode != "none")
                    if not parse_think:
                        yield {"content": content}
                    else:
                        # 完整文本中提取 <think>...</think> 和正文
                        import re as _re
                        think_match = _re.search(r'<think>(.*?)</think>', content, _re.DOTALL)
                        if think_match:
                            reasoning_text = think_match.group(1)
                            answer_text = content[:think_match.start()] + content[think_match.end():]
                            if reasoning_text.strip():
                                yield {"reasoning_content": reasoning_text}
                            if answer_text.strip():
                                yield {"content": answer_text}
                        else:
                            # qwen3 模式下无 </think> 标签 → 全部当 reasoning
                            if self.think_tag_mode == "qwen3" and "</think>" not in content:
                                yield {"reasoning_content": content}
                            else:
                                yield {"content": content}

                # ── tool_calls ──
                if tc_list := message.get("tool_calls"):
                    tool_calls = []
                    for tc in tc_list:
                        fn = tc.get("function", {})
                        args_raw = fn.get("arguments", "")
                        try:
                            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                        except json.JSONDecodeError:
                            args = {"_raw": args_raw}
                        tool_calls.append({
                            "id": tc.get("id", ""),
                            "name": fn.get("name", ""),
                            "arguments": args,
                        })
                    yield {"tool_calls": tool_calls}

        except Exception as e:
            logger.error(f"LLM non-stream error: {e}")
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
