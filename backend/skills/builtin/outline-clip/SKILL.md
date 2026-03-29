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
已有大纲后，用户说"不看XX"/"删除XX"/"去掉XX"/"只看XX"，需要对大纲进行动态修改。

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
