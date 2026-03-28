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

用户对已有大纲提出修改要求：
- "不看低阶交叉" / "删除XX节点" / "去掉XX"
- "只看传输层" / "保留容量相关指标"

**前提：当前会话必须已有大纲。**

## 工作流（按序调用工具）

```
1. get_current_outline(session_id)
   → 获取当前大纲结构，了解有哪些节点可以操作

2. clip_outline(session_id, instruction)
   → 执行裁剪操作，将用户指令转为具体的节点删除/保留操作
   → 裁剪结果自动保存到当前会话

3. [如果当前已有报告] → execute_data(session_id) + render_report(session_id)
   → 裁剪后必须重新执行数据查询和报告生成，否则报告与大纲不一致
```

## 关键规则

- **裁剪前必须先调用 get_current_outline**，了解节点结构
- **已有报告时，裁剪后必须追加 execute_data + render_report**
- 用户说"只看XX"时，理解为 keep_only 操作（删除其他节点，保留指定节点）
- 用户说"删除XX/不看XX/去掉XX"时，理解为 delete_node 操作

## 裁剪指令类型

| 类型 | 说明 | 示例指令 |
|------|------|---------|
| delete_node | 删除指定节点及子树 | "删除低阶交叉" |
| keep_only | 仅保留指定节点，删除其余 | "只看容量指标" |
| filter_param | 修改节点的数据过滤参数 | "企业类型改为金融" |
