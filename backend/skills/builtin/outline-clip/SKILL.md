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
executor:
  module: outline_clip_executor
  class: OutlineClipExecutor
  deps:
    - llm_service
---

# 大纲动态裁剪

## 适用场景
用户想要从已有大纲中移除某些分析维度，或只保留特定节点。
触发词："不看XX"、"删除XX"、"去掉XX节点"、"只保留XX"、"只看XX相关的"。

## 使用工具
`clip_outline(session_id, instruction)`

instruction 描述用户意图，如：
- "删除低阶交叉资源分析节点"
- "只保留容量相关的指标"
- "去掉时延部分"

## 裁剪操作类型（内部实现）
- delete_node: 删除指定节点及其子树
- keep_only: 仅保留指定节点，删除其余
- filter_param: 修改节点的数据绑定参数

## 重要后续操作
裁剪完成后，若当前会话已有报告（has_report=true）：
**必须** 调用 `execute_data` → `render_report` 刷新报告内容
