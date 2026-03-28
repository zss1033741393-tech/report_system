"""Memory 提取 Prompt —— 领域定制，面向看网报告系统。"""

EXTRACT_PROMPT = """\
你是看网报告系统的记忆提取助手。请从以下对话中提取有助于未来对话的用户偏好和上下文信息。

## 提取维度

1. **用户工作上下文**（workContext）
   - 用户负责的网络领域（如 fgOTN、政企 OTN、传送网络等）
   - 用户的分析目标或角色

2. **当前关注点**（topOfMind）
   - 用户最近在分析的具体问题或场景

3. **已知事实**（facts）—— 最多提取 10 条
   每条包含：
   - content: 事实描述（中文，简洁）
   - category: 分类（preference/behavior/domain/constraint）
   - confidence: 置信度（0.0-1.0）

   重点关注：
   - 用户习惯性排除的分析维度（"不看低阶交叉"、"不关注XX"）
   - 用户习惯使用的过滤条件（行业、阈值、时间范围）
   - 用户偏好的报告风格或分析深度
   - 用户已掌握的领域知识（无需重复解释）

## 输出格式
用 ```json ``` 代码块包裹，不要输出其他文字：
```json
{
  "user": {
    "workContext": {"summary": "简洁描述工作上下文，无信息则留空字符串"},
    "topOfMind": {"summary": "当前最关注的问题，无信息则留空字符串"}
  },
  "facts": [
    {"content": "...", "category": "preference", "confidence": 0.9}
  ]
}
```

## 对话内容
{conversation}

## 当前已有记忆（供参考，避免重复）
{current_memory}
"""

FORMAT_MEMORY_PROMPT = """\
<memory>
{formatted}
</memory>"""


def format_memory_for_prompt(memory: dict, max_facts: int = 8) -> str:
    """将 memory JSON 格式化为注入 system prompt 的文本块。"""
    if not memory:
        return ""

    parts = []
    user = memory.get("user", {})

    wc = (user.get("workContext") or {}).get("summary", "")
    tom = (user.get("topOfMind") or {}).get("summary", "")
    if wc:
        parts.append(f"工作上下文: {wc}")
    if tom:
        parts.append(f"当前关注: {tom}")

    facts = memory.get("facts") or []
    if facts:
        parts.append("已知偏好与习惯:")
        for f in facts[:max_facts]:
            conf = f.get("confidence", 0)
            if conf < 0.6:
                continue
            cat = f.get("category", "")
            cat_label = {"preference": "偏好", "behavior": "习惯",
                         "domain": "领域", "constraint": "约束"}.get(cat, cat)
            parts.append(f"  - [{cat_label}] {f.get('content', '')}")

    if not parts:
        return ""

    formatted = "\n".join(parts)
    return FORMAT_MEMORY_PROMPT.format(formatted=formatted)
