# 大纲裁剪指令解析 Prompt

将用户的自然语言裁剪指令转换为结构化操作列表，由 executor 纯算法执行。

## System Prompt

（空字符串）

## User Message Template

```
你是大纲裁剪专家。根据用户指令，生成裁剪操作列表。

## 当前大纲节点
{nodes_text}

## 用户指令
{user_instruction}

## 输出格式
用 ```json ``` 代码块包裹输出，格式：
{"instructions": [
    {"type": "delete_node", "target_name": "节点名", "level": 4},
    {"type": "filter_param", "target_name": "节点名", "param_key": "industry", "param_value": "金融企业"},
    {"type": "keep_only", "target_names": ["节点名1", "节点名2"]}
]}
```

## 操作类型说明

| type | 说明 |
|------|------|
| delete_node | 删除指定节点及其子树 |
| filter_param | 为指定节点注入过滤参数（不删节点） |
| keep_only | 仅保留列表中的节点（删除其他同层节点） |

## 降级策略

若 LLM 调用失败，返回空 instructions 列表，不做任何裁剪。
