"""SimpleReActEngine —— 自研 ReAct 主循环。

替代原 Planner → Executor → Reflector 的 Plan-then-Execute 架构。
LLM 全程参与，通过 tool_calls 驱动工具执行，感知中间结果后动态调整。

工作流：
  messages = [system] + chat_history[-N:] + [user]
  LOOP(max_steps=15):
    ① 上下文压缩检查
    ② LLM call（携带 tool schemas）
    ③ 有 tool_calls → 执行工具 → 追加结果 → 循环检测 → continue
    ④ 无 tool_calls（最终答案）→ yield SSE → break
  收尾：Memory 入队（异步，不阻塞）

LLM 接口说明：
  LLMService 底层是 OpenAI-compatible API（Qwen3.5-27B）。
  本引擎直接扩展 complete_stream 的 payload 加入 tools 字段，
  不修改 LLMService 代码，通过 extra_payload 机制注入。
  _call_llm_with_tools 完成后手动触发 trace_callback，
  确保每次 LLM 调用都写入 llm_traces 表，与 AgentLLM 行为一致。
"""

import json
import logging
import time
from typing import AsyncGenerator, Any

from agent.context_compressor import ContextCompressor
from agent.loop_detector import LoopDetector
from agent.tool_definitions import ALL_TOOLS
from agent.tool_registry import ToolRegistry
from llm.config import LLMConfig, _load as _load_llm_config
from llm.service import LLMService

logger = logging.getLogger(__name__)

MAX_STEPS = 15      # ReAct 最大循环步数
HISTORY_LIMIT = 20  # 注入的 chat_history 条数上限


# ─── System Prompt 模板 ──────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """\
你是看网系统智能助手，运行在 ReAct 模式下，帮助用户生成网络分析报告或创建新的看网能力。

## 意图判断优先于一切（每次收到消息，先判断意图类型，再行动）

### 类型 A：普通问答
**识别**：用户提问（"XX是什么"/"如何做"/"解释"/"帮我了解"等），或不涉及报告生成的对话
**处理**：**直接回答，不调用任何工具**
**示例**：
- "fgOTN 是什么？" → 直接解释，无需工具
- "路由协议有哪些？" → 直接回答，无需工具
- "大纲有哪几层？" → 直接说明，无需工具

### 类型 B：运行态 —— 生成/刷新报告
**识别**：用户提出看网分析需求（通常 ≤50 字），如"分析XX"/"生成XX报告"/"查看XX情况"
**处理步骤**：
1. 调用 get_session_status 了解当前会话是否已有大纲
2. **无大纲** → 调用 search_skill(query) 检索已有看网能力
   - 命中 → execute_data → render_report
   - 未命中 → 告知用户暂无该场景能力，询问是否需要创建（**不要自动启动设计态流程**）
3. **有大纲** → 直接 execute_data → render_report

### 类型 C：运行态 —— 修改已有报告
**识别**：用户对已有报告提出调整，如"不看XX"/"删除XX"/"只看XX行业"/"阈值改为XX"
**处理步骤**：clip_outline（删除/筛选节点）或 inject_params（修改参数）→ execute_data → render_report

### 类型 D：设计态 —— 创建新看网能力【严格门槛，不确定则先询问】
**识别（必须同时满足以下两个条件）**：
  ✅ 条件1：用户输入了 ≥100 字的完整看网逻辑描述，包含场景、指标、判断逻辑等要素
  ✅ 条件2：用户明确表达了"创建"/"设计"/"沉淀"新能力的意图
**处理步骤**：先调用 read_skill_file 读取 skill-factory 工作流，再按六步依序执行
**注意**：不满足上述两个条件时，绝对不要调用 understand_intent 等设计态工具

## 工具使用约束
- **类型 A 不调用任何工具**，能直接答的问题直接答
- **设计态工具有严格门槛**：understand_intent/extract_structure 等六步工具仅类型 D 可用
- **search_skill 未命中时不自动触发设计态**，询问用户确认后才进行
- **不重复已完成的操作**：工具结果中已有数据时不要重复调用相同工具
- **persist_skill 必须等用户明确确认**：用户说"保存/沉淀/确认"才调用
{skill_system_section}
{memory_section}
## 当前会话 ID
{session_id}
"""

MEMORY_SECTION_TEMPLATE = """## 用户记忆（历史对话提炼，可参考但不强制遵循）
<memory>
{memory_content}
</memory>
"""


class SimpleReActEngine:
    """
    ReAct 主循环引擎。

    直接操作 LLMService 底层 API（不经过 AgentLLM 包装），
    以便注入 tools 参数实现 function calling。
    """

    _react_config = None  # 类级懒加载，首次调用时从 YAML 读取

    def __init__(
        self,
        llm_service: LLMService,
        tool_registry: ToolRegistry,
        chat_history,
        session_service,
        skill_registry=None,
        memory_storage=None,
        memory_queue=None,
    ):
        self._llm = llm_service
        self._tools = tool_registry
        self._ch = chat_history
        self._ss = session_service
        self._reg = skill_registry   # SkillRegistry，用于动态生成 skill 索引
        self._compressor = ContextCompressor(llm_service)
        self._memory_storage = memory_storage
        self._memory_queue = memory_queue

    # ─── System Prompt 构建 ──────────────────────────────────────────────────

    def _build_skill_system_section(self) -> str:
        """
        动态从 SkillRegistry 生成 skill 索引。

        只列出以下两类 skill：
          1. skill-factory（设计态能力工厂，带严格触发条件说明）
          2. custom skills（用户已沉淀的看网能力，供运行态通过 search_skill 检索）

        排除纯工具化的运行态 builtin skills（outline-generate/outline-clip/param-inject/
        data-execute/report-generate），这些 skills 已通过工具函数（clip_outline/
        execute_data 等）暴露给 LLM，LLM 不需要读取其 SKILL.md。
        将它们列入索引会误导 LLM 在普通请求时也去读取 skill-factory 等文件。
        """
        if not self._reg:
            return ""

        skills = self._reg.get_enabled()
        if not skills:
            return ""

        # 运行态工具型 builtin skills：已通过工具函数暴露，不在索引中展示
        RUNTIME_TOOL_SKILLS = {
            "outline-generate", "outline-clip", "param-inject",
            "data-execute", "report-generate",
        }

        items = []
        for s in skills:
            if s.source == "builtin" and s.name in RUNTIME_TOOL_SKILLS:
                continue  # 跳过：已通过工具函数暴露，无需在索引中出现

            source = s.source
            rel_path = f"skills/{source}/{s.name}/SKILL.md"

            # skill-factory 单独标注严格触发条件
            trigger_line = ""
            if s.name == "skill-factory":
                trigger_line = (
                    "\n    <trigger>仅当类型 D 条件满足时使用："
                    "用户输入 ≥100 字看网逻辑 + 明确表达创建/沉淀新能力意图</trigger>"
                )

            items.append(
                f"  <skill>\n"
                f"    <n>{s.name}</n>\n"
                f"    <display_name>{s.display_name or s.name}</display_name>\n"
                f"    <description>{s.description}</description>{trigger_line}\n"
                f"    <path>{rel_path}</path>\n"
                f"  </skill>"
            )

        if not items:
            return ""

        skills_xml = "<available_skills>\n" + "\n".join(items) + "\n</available_skills>"
        return (
            "\n## 技能索引\n"
            "skill-factory 仅在类型 D（设计态）条件满足时通过 read_skill_file 读取；\n"
            "运行态操作（生成报告、裁剪大纲等）通过工具函数直接调用，无需读取 SKILL.md。\n\n"
            + skills_xml
            + "\n"
        )

    def _build_system_prompt(self, session_id: str) -> str:
        skill_system_section = self._build_skill_system_section()

        memory_section = ""
        if self._memory_storage:
            memory_content = self._memory_storage.format_for_injection(max_tokens=2000)
            if memory_content:
                memory_section = MEMORY_SECTION_TEMPLATE.format(
                    memory_content=memory_content
                )

        return SYSTEM_PROMPT_TEMPLATE.format(
            skill_system_section=skill_system_section,
            memory_section=memory_section,
            session_id=session_id,
        )

    # ─── ReAct 主循环 ────────────────────────────────────────────────────────

    async def run(
        self,
        session_id: str,
        user_message: str,
        chat_history_msgs: list[dict],
        trace_callback=None,
    ) -> AsyncGenerator[str, None]:
        """
        执行 ReAct 循环，以 AsyncGenerator yield SSE 事件字符串。
        trace_callback 透传给每次 LLM 调用，确保写入 llm_traces 表。
        """
        # ─── 初始化 messages ─────────────────────────────────────────────────
        system_prompt = self._build_system_prompt(session_id)
        history = chat_history_msgs[-HISTORY_LIMIT:]

        # 去重：HistoryMiddleware 从数据库读取历史时，本轮 user message 已被
        # lead_agent 提前写入，history 末尾可能已含本条消息，避免重复追加
        last_history_content = history[-1].get("content", "") if history else ""
        if last_history_content == user_message:
            history = history[:-1]

        messages = (
            [{"role": "system", "content": system_prompt}]
            + history
            + [{"role": "user", "content": user_message}]
        )

        loop_detector = LoopDetector()
        current_outline: Any = None
        step_results: dict = {}

        # 预加载当前大纲（供工具执行时使用）
        try:
            state = await self._ch.get_outline_state(session_id)
            if state and state.get("outline_json"):
                current_outline = state["outline_json"]
        except Exception:
            pass

        # ─── ReAct 主循环 ─────────────────────────────────────────────────────
        for step_idx in range(MAX_STEPS):
            logger.info(f"[{session_id}] ReAct step {step_idx + 1}/{MAX_STEPS}")

            # ① 上下文压缩检查
            if self._compressor.should_compress(messages):
                logger.info(f"[{session_id}] 触发上下文压缩")
                try:
                    messages = await self._compressor.compress(messages)
                except Exception as e:
                    logger.warning(f"上下文压缩异常: {e}")

            # ② LLM 调用（携带 tools schema，同时写 llm_traces）
            try:
                llm_response = await self._call_llm_with_tools(
                    messages, trace_callback=trace_callback, step_idx=step_idx
                )
            except Exception as e:
                logger.exception(f"[{session_id}] LLM 调用失败: {e}")
                yield self._ev("error", message=f"LLM 调用失败: {e}")
                return

            tool_calls = llm_response.get("tool_calls", [])
            content = llm_response.get("content", "")

            # ③ 有 tool_calls → 执行工具
            if tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": content or "",
                    "tool_calls": tool_calls,
                })

                # 循环检测
                warn_msg, should_stop = loop_detector.check(tool_calls)
                if warn_msg:
                    messages.append({"role": "user", "content": warn_msg})
                    if should_stop:
                        logger.warning(f"[{session_id}] 强制停止循环")
                        messages[-2].pop("tool_calls", None)
                        break

                # 执行每个工具调用
                for tc in tool_calls:
                    tool_name = tc.get("function", {}).get("name", "")
                    tool_args_raw = tc.get("function", {}).get("arguments", "{}")
                    tool_call_id = tc.get("id", f"call_{tool_name}_{step_idx}")

                    try:
                        tool_args = (
                            json.loads(tool_args_raw)
                            if isinstance(tool_args_raw, str)
                            else tool_args_raw
                        )
                    except json.JSONDecodeError:
                        tool_args = {}

                    if "session_id" not in tool_args:
                        tool_args["session_id"] = session_id

                    # yield tool_call 事件（前端 ToolCallBlock 可视化）
                    yield self._ev("tool_call", name=tool_name, args=tool_args)

                    # 执行工具，透传所有 SSE 事件
                    tool_result_content = ""
                    async for sse_item in self._tools.execute(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        session_id=session_id,
                        current_outline=current_outline,
                        step_results=step_results,
                        user_message=user_message,
                        trace_callback=trace_callback,
                    ):
                        try:
                            parsed = json.loads(sse_item)
                            if parsed.get("type") == "tool_result":
                                tool_result_content = parsed.get("content", "")
                                # 工具修改了大纲时刷新本地缓存
                                if tool_name in ("clip_outline", "inject_params", "search_skill"):
                                    try:
                                        new_state = await self._ch.get_outline_state(session_id)
                                        if new_state and new_state.get("outline_json"):
                                            current_outline = new_state["outline_json"]
                                            step_results["current_outline"] = current_outline
                                    except Exception:
                                        pass
                            yield sse_item
                        except Exception:
                            yield sse_item

                    # 工具结果追加到 messages，供 LLM 下一步感知
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": tool_result_content or f"{tool_name} 执行完成",
                    })

                continue  # 继续下一步 LLM 决策

            # ④ 无 tool_calls → 最终答案
            if content:
                yield self._ev("chat_reply", content=content)
            break

        else:
            logger.warning(f"[{session_id}] 达到最大步数 {MAX_STEPS}")
            yield self._ev("chat_reply", content="已完成当前分析，请查看右侧面板。")

        yield self._ev("done")

        # ─── 异步 Memory 入队（不阻塞响应）──────────────────────────────────
        if self._memory_queue:
            memory_msgs = [
                m for m in messages
                if m.get("role") in ("user", "assistant")
                and not m.get("tool_calls")
                and m.get("content")
            ]
            if memory_msgs:
                try:
                    self._memory_queue.enqueue(session_id, memory_msgs[-4:])
                except Exception as e:
                    logger.debug(f"Memory enqueue failed (non-critical): {e}")

    # ─── LLM 调用（带 tools 参数 + trace 记录）──────────────────────────────

    async def _call_llm_with_tools(
        self,
        messages: list[dict],
        trace_callback=None,
        step_idx: int = 0,
    ) -> dict:
        """
        调用 LLMService，注入 tools 参数。

        完成后手动触发 trace_callback，写入 llm_traces 表。
        原来通过 AgentLLM._record_trace 做这件事；react_engine 绕过了 AgentLLM，
        在 finally 块中手动补上，保证行为一致。
        """
        # 懒加载 YAML react_agent 场景配置
        if SimpleReActEngine._react_config is None:
            try:
                base = _load_llm_config("react_agent")
            except Exception:
                logger.warning("react_agent 场景未配置，使用默认值")
                base = LLMConfig(temperature=0.7, max_tokens=32768)
            SimpleReActEngine._react_config = base

        base_cfg = SimpleReActEngine._react_config
        # 在 YAML extra_payload 基础上注入 tools（enable_thinking 由 YAML 控制）
        extra = dict(base_cfg.extra_payload)
        extra["tools"] = ALL_TOOLS
        extra["tool_choice"] = "auto"
        config = LLMConfig(
            model=base_cfg.model,
            temperature=base_cfg.temperature,
            top_p=base_cfg.top_p,
            max_tokens=base_cfg.max_tokens,
            extra_payload=extra,
        )

        content_parts: list[str] = []
        tool_calls_raw: dict = {}
        reasoning_parts: list[str] = []
        t0 = time.perf_counter()
        err_msg = None

        try:
            async for chunk in self._llm.complete_stream(messages, config):
                if "content" in chunk:
                    content_parts.append(chunk["content"])
                if "reasoning_content" in chunk:
                    reasoning_parts.append(chunk["reasoning_content"])
                if "tool_calls" in chunk:
                    # 合并流式 tool_calls（OpenAI streaming 增量格式）
                    for tc_delta in chunk["tool_calls"]:
                        idx = tc_delta.get("index", 0)
                        call_id = str(idx)

                        if call_id not in tool_calls_raw:
                            tool_calls_raw[call_id] = {
                                "id": tc_delta.get("id", f"call_{idx}"),
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }

                        tc = tool_calls_raw[call_id]
                        fn = tc_delta.get("function", {})
                        if fn.get("name"):
                            tc["function"]["name"] += fn["name"]
                        if fn.get("arguments"):
                            tc["function"]["arguments"] += fn["arguments"]
                        if tc_delta.get("id"):
                            tc["id"] = tc_delta["id"]

                if "error" in chunk:
                    raise RuntimeError(chunk["error"])

        except Exception as e:
            err_msg = str(e)
            raise

        finally:
            # ── 手动触发 trace_callback，写入 llm_traces 表 ──────────────────
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if trace_callback:
                content_text = "".join(content_parts)
                reasoning_text = "".join(reasoning_parts)
                tool_names = [
                    tc["function"]["name"]
                    for tc in tool_calls_raw.values()
                    if tc["function"]["name"]
                ]
                # response_content 附带工具调用信息，方便在 trace 里排查
                response_summary = content_text
                if tool_names:
                    response_summary = f"[tool_calls: {', '.join(tool_names)}] {content_text}"
                try:
                    await trace_callback(
                        llm_type="react_agent",
                        step_name=f"react_step_{step_idx + 1}",
                        request_messages=messages,
                        response_content=response_summary,
                        reasoning_content=reasoning_text,
                        model=config.model or self._llm.default_model,
                        temperature=config.temperature,
                        elapsed_ms=elapsed_ms,
                        success=err_msg is None,
                        error=err_msg or "",
                    )
                except Exception as trace_err:
                    logger.debug(f"trace_callback 失败 (non-critical): {trace_err}")

        tool_calls = list(tool_calls_raw.values()) if tool_calls_raw else []

        return {
            "content": "".join(content_parts),
            "reasoning_content": "".join(reasoning_parts),
            "tool_calls": tool_calls,
        }

    # ─── SSE 工具方法 ────────────────────────────────────────────────────────

    @staticmethod
    def _ev(event_type: str, **kwargs) -> str:
        return json.dumps({"type": event_type, **kwargs}, ensure_ascii=False)
