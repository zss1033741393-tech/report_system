---
name: outline-clip
display_name: 大纲动态裁剪
description: 依据用户约束条件对已有大纲进行节点裁剪、参数修改或保留筛选，替代原 outline-modify 和条件过滤
enabled: true
params:
  instructions:
    type: string
    required: true
    description: 用户的裁剪指令文本
paradigm: Tool Wrapper
executor:
  module: outline_clip_executor
  class: OutlineClipExecutor
  deps: []
---

# 大纲动态裁剪

## 适用场景
已有大纲后，用户说"不看XX"/"删除XX"/"去掉XX"/"只看XX"，需要对大纲进行动态修改。

## Metadata
- **paradigm**: Tool Wrapper（裁剪算法封装，LLM 指令解析在 tool 层）
- **when_to_use**: 已有大纲，用户说"不看XX"/"删除XX"/"只看XX"时
- **inputs**: clip_instructions（tool 层 LLM 预解析的结构化操作列表）
- **outputs**: updated_outline（裁剪后的大纲树）、deleted_nodes、modified_params

## When to Use
- ✅ 用户明确说"不看XX"/"去掉XX"/"只看XX"/"删除XX节点"
- ❌ 生成新大纲（使用 search_skill）
- ❌ 修改参数阈值（使用 inject_params）

## How to Use

> LLM 指令解析在 **tool 层**（`tool_definitions._clip_outline`）完成，executor 只做纯算法。

1. tool 层 `_llm_parse_clip(instruction, nodes_text)` → 生成 clip_instructions 列表
2. executor 接收 `params.clip_instructions` → 纯算法执行 delete_node / filter_param / keep_only

## References
- `references/clip_prompt.md` — 裁剪指令解析 LLM prompt

## 工具调用：clip_outline(instruction)
传入用户的裁剪指令文本，系统 LLM 解析后执行以下操作之一或组合：

**delete_node（删除节点）**
删除指定名称的节点及其所有子节点。
示例："删除低阶交叉资源分析" → 删除该节点子树

**filter_param（参数过滤）**
修改大纲节点的数据绑定参数（如行业过滤条件）。
示例："只看金融行业" → filter_param(industry=金融)

**keep_only（保留指定节点）**
只保留指定节点，删除其余同级节点。
示例："只看容量分析部分" → 删除非容量节点

## 关键规则
- 执行完 clip_outline 后，**必须**重新调用 execute_data + render_report 刷新报告
- 可以在一次调用中组合多种裁剪操作
- 裁剪操作会永久修改当前会话的大纲状态
