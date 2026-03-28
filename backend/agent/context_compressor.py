"""ContextCompressor —— 对标 DeerFlow SummarizationMiddleware。

触发条件（OR 逻辑）：
  - token 估算 > TOKEN_THRESHOLD
  - 消息条数 > MSG_THRESHOLD

压缩算法：
  1. 保留 system prompt（messages[0]）+ 最近 KEEP_TAIL 条消息
  2. 找到 AI/Tool pair 安全分割边界（不在 tool_call 序列中间切割）
  3. 限制摘要输入 token，调用 LLM 生成摘要
  4. 摘要注入为 user role 消息（避免 system message 插入限制）

参考 DeerFlow issue #1299：Anthropic 不允许 conversation 中途插入 SystemMessage。
"""
import json
import logging

from llm.config import LLMConfig
from llm.service import LLMService

logger = logging.getLogger(__name__)

TOKEN_THRESHOLD = 15000    # 估算 token 数超过此值触发压缩
MSG_THRESHOLD = 60         # 消息条数超过此值触发压缩
KEEP_TAIL = 10             # 压缩后保留最近 N 条消息不动
SUMMARY_MAX_TOKENS = 4000  # 摘要 LLM 调用的输入 token 上限

# 领域定制摘要 prompt
DOMAIN_SUMMARY_PROMPT = """\
你是看网报告系统的上下文摘要助手。请对下面的对话历史进行压缩摘要，重点保留：

1. 当前大纲的结构和关键节点（哪些节点已保留/已删除/已修改）
2. 用户已施加的约束条件（行业过滤、阈值修改、时间范围等）
3. 已完成的数据查询结果摘要（关键数值，不需要全部细节）
4. 设计态流程（skill-factory）的当前进度（完成了哪些步骤）
5. 尚未完成/等待用户确认的操作

输出一段简洁的中文摘要（300-600 字），聚焦"当前状态"，避免重复已完成操作的细节。
不要输出 JSON 或列表格式，用自然段落叙述。

以下是对话历史：
---
{history}
---
"""


def _estimate_tokens(messages: list[dict]) -> int:
    """粗略估算 token 数（中英文混合按 3.3 字符 ≈ 1 token）。"""
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, list):
            # OpenAI 多模态格式
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        total += len(str(content)) // 3 + 1
        # tool_calls 部分
        for tc in m.get("tool_calls") or []:
            total += len(json.dumps(tc, ensure_ascii=False)) // 3 + 1
    return total


def _find_safe_split_boundary(messages: list[dict], target: int) -> int:
    """
    从 target 位置向前找安全分割点（不在 tool_call 序列中间）。
    tool_call 序列: AIMessage(tool_calls) + N×ToolMessage
    必须整体保留或整体摘要，不能切断。
    """
    # 从 target 往前找，跳过紧接着的 tool messages
    idx = target
    while idx > 0:
        msg = messages[idx]
        role = msg.get("role", "")
        if role == "tool":
            # tool message，往前继续找
            idx -= 1
            continue
        # 找到非 tool 消息
        # 检查前一条是否为含 tool_calls 的 assistant 消息
        if role == "assistant" and msg.get("tool_calls"):
            # 这是 tool_call 序列的起始，需要继续往前
            idx -= 1
            continue
        break
    return max(0, idx)


def _trim_to_tokens(messages: list[dict], max_tokens: int) -> list[dict]:
    """从后往前保留消息直到 token 预算用完。"""
    result = []
    used = 0
    for m in reversed(messages):
        content = m.get("content") or ""
        t = len(str(content)) // 3 + 1
        if used + t > max_tokens:
            break
        result.append(m)
        used += t
    return list(reversed(result))


class ContextCompressor:

    def __init__(self, llm_service: LLMService, config: LLMConfig | None = None):
        self._llm = llm_service
        self._config = config or LLMConfig(
            model="",
            temperature=0.3,
            max_tokens=4096,
        )

    def should_compress(self, messages: list[dict]) -> bool:
        if len(messages) > MSG_THRESHOLD:
            return True
        if _estimate_tokens(messages) > TOKEN_THRESHOLD:
            return True
        return False

    async def compress(self, messages: list[dict]) -> list[dict]:
        """压缩 messages，返回压缩后的消息列表。"""
        if len(messages) <= 2:
            return messages

        system_msg = messages[0] if messages[0].get("role") == "system" else None
        body = messages[1:] if system_msg else messages

        if len(body) <= KEEP_TAIL:
            return messages

        # 分区：待摘要部分 + 保留尾部
        to_summarize_raw = body[:-KEEP_TAIL]
        to_keep = body[-KEEP_TAIL:]

        # 找安全分割边界
        split_idx = _find_safe_split_boundary(to_summarize_raw, len(to_summarize_raw) - 1)
        to_summarize = to_summarize_raw[:split_idx + 1]

        if not to_summarize:
            return messages

        # 限制摘要输入大小，避免摘要调用本身超限
        trimmed = _trim_to_tokens(to_summarize, SUMMARY_MAX_TOKENS)

        # 调用 LLM 生成摘要
        history_text = self._format_for_summary(trimmed)
        prompt = DOMAIN_SUMMARY_PROMPT.format(history=history_text)
        try:
            summary_text = await self._llm.complete(
                [{"role": "user", "content": prompt}], self._config
            )
        except Exception as e:
            logger.warning(f"ContextCompressor LLM 调用失败，跳过压缩: {e}")
            return messages

        summary_msg = {
            "role": "user",
            "content": f"以下是截至目前的对话摘要：\n\n{summary_text}",
        }

        compressed = []
        if system_msg:
            compressed.append(system_msg)
        compressed.append(summary_msg)
        compressed.extend(to_keep)

        logger.info(
            f"ContextCompressor: {len(messages)} → {len(compressed)} 条消息 "
            f"(摘要了 {len(to_summarize)} 条)"
        )
        return compressed

    @staticmethod
    def _format_for_summary(messages: list[dict]) -> str:
        parts = []
        for m in messages:
            role = m.get("role", "unknown")
            content = m.get("content") or ""
            if m.get("tool_calls"):
                tc_names = [tc.get("name", "?") for tc in m["tool_calls"]]
                parts.append(f"[{role}] 调用工具: {', '.join(tc_names)}")
            elif role == "tool":
                tc_content = str(content)[:200]
                parts.append(f"[tool_result] {tc_content}")
            else:
                parts.append(f"[{role}] {str(content)[:500]}")
        return "\n".join(parts)
