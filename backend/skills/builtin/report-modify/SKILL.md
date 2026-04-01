---
name: report-modify
display_name: 报告局部修改
scene_intro: 对已生成的看网报告进行局部修改，支持数据参数调整和文字润色
keywords: ["修改报告", "润色", "调整参数", "报告修改"]
source: builtin
version: 1
enabled: true
---

## 工作流

本技能处理对已生成报告的局部修改请求，分为两类：

### 数据层修改（modify_report_data）

适用场景：修改某个章节的数据参数（如阈值、过滤条件），重新执行该节点数据查询，局部刷新报告 HTML。

工作步骤：
1. 解析用户指令，定位目标章节 node_id（使用 section_resolver）
2. 调用 inject_params 更新参数
3. 对目标 L5 节点重新执行数据查询
4. 生成局部 HTML 片段并推送 report_patch 事件
5. 更新持久化的报告 HTML

### 文本层修改（modify_report_text）

适用场景：对报告中某段 narrative 分析文字进行润色、改写或扩充。

工作步骤：
1. 解析用户指令，定位目标章节 node_id
2. 提取目标章节当前 narrative 文字
3. 使用 LLM 按用户要求改写
4. 生成局部 HTML 片段并推送 report_patch 事件
5. 更新持久化的报告 HTML

### 章节定位规则

- 用户说"第一章"→ 对应第一个 L3 节点
- 用户说"第二章第一节"→ 对应第二个 L3 节点的第一个 L4 子节点
- 用户说具体名称（如"覆盖率分析"）→ 模糊匹配 node.name

系统优先进行精确数字编号匹配，其次进行名称关键词匹配。
