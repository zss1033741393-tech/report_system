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

## 裁剪指令类型
- delete_node: 删除指定节点及子树
- filter_param: 修改数据绑定参数
- keep_only: 仅保留指定节点

## Scripts
- scripts/outline_clip_executor.py
