"""ReAct engine tool definitions -- JSON Schema for all tools (OpenAI function-calling format).

LLM uses these descriptions to decide which tool to call.
13 tools: 2 basic + 6 runtime + 5 design-mode (skill-factory steps).
"""

_READ_SKILL_FILE = {
    "type": "function",
    "function": {
        "name": "read_skill_file",
        "description": (
            "读取指定路径的 SKILL.md 文件全文。"
            "在执行复杂任务前先调用此工具理解对应技能的工作流和规则。"
            "只在真正需要时读取，不要预先读取所有技能文件。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "SKILL.md 的相对路径，如 skills/builtin/skill-factory/SKILL.md",
                }
            },
            "required": ["path"],
        },
    },
}

_GET_SESSION_STATUS = {
    "type": "function",
    "function": {
        "name": "get_session_status",
        "description": (
            "获取当前会话状态：是否已有大纲、是否已有报告、是否有待沉淀的设计态缓存。"
            "在决定下一步操作前调用，避免重复生成已存在的内容。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"}
            },
            "required": ["session_id"],
        },
    },
}

_SEARCH_SKILL = {
    "type": "function",
    "function": {
        "name": "search_skill",
        "description": (
            "在已沉淀的看网能力库中检索与用户问题匹配的能力，返回大纲模板。"
            "用户首次提问时先调用，命中则直接加载，未命中再走 GraphRAG 生成流程。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "query": {"type": "string", "description": "用户的分析需求文本"},
            },
            "required": ["session_id", "query"],
        },
    },
}

_GET_CURRENT_OUTLINE = {
    "type": "function",
    "function": {
        "name": "get_current_outline",
        "description": (
            "获取当前会话的完整大纲 JSON 结构。"
            "在执行大纲裁剪、参数注入、报告生成等操作前调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
    },
}

_CLIP_OUTLINE = {
    "type": "function",
    "function": {
        "name": "clip_outline",
        "description": (
            "按裁剪指令对大纲进行节点删除、过滤或保留操作。"
            "用户说不看某内容、删除某节点、只保留某部分时调用。"
            "注意：执行后如果会话已有报告，必须重新调用 execute_data + render_report 刷新报告。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "instruction": {
                    "type": "string",
                    "description": "裁剪指令，如：删除低阶交叉节点；只保留容量相关指标",
                },
            },
            "required": ["session_id", "instruction"],
        },
    },
}

_INJECT_PARAMS = {
    "type": "function",
    "function": {
        "name": "inject_params",
        "description": (
            "向大纲数据绑定中注入运行时参数，如行业过滤、阈值修改、时间范围等。"
            "用户说只看某行业、阈值改为某值时调用。"
            "注意：执行后如果会话已有报告，必须重新调用 execute_data + render_report 刷新报告。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "param_updates": {
                    "type": "object",
                    "description": "参数更新字典，例如 {\"industry\": [\"金融\"], \"threshold\": 0.8}",
                },
            },
            "required": ["session_id", "param_updates"],
        },
    },
}

_EXECUTE_DATA = {
    "type": "function",
    "function": {
        "name": "execute_data",
        "description": (
            "执行大纲中所有 L5 评估指标节点的数据查询（Mock/SQL/API）。"
            "生成报告前必须先调用此工具。大纲被裁剪或参数被修改后也需重新调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
    },
}

_RENDER_REPORT = {
    "type": "function",
    "function": {
        "name": "render_report",
        "description": (
            "基于大纲结构和数据执行结果，用 Jinja2 模板渲染完整 HTML 报告。"
            "这是生成报告的最后一步，必须在 execute_data 成功后调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
    },
}

_UNDERSTAND_INTENT = {
    "type": "function",
    "function": {
        "name": "understand_intent",
        "description": (
            "理解专家输入的看网逻辑，提取场景简介、触发关键词、用户问法变体和技能名称建议。"
            "这是 skill-factory 设计态六步流程的第 1 步。"
            "用户输入超过 80 字的看网逻辑文本时，先读取 skill-factory SKILL.md 了解完整流程，再调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "expert_input": {
                    "type": "string",
                    "description": "专家输入的自然语言看网逻辑文本",
                },
            },
            "required": ["session_id", "expert_input"],
        },
    },
}

_EXTRACT_STRUCTURE = {
    "type": "function",
    "function": {
        "name": "extract_structure",
        "description": (
            "将看网逻辑文本格式化为结构化 Markdown，映射五层知识架构。"
            "这是 skill-factory 设计态六步流程的第 2 步，在 understand_intent 成功后调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "raw_input": {"type": "string", "description": "专家输入的原始文本"},
            },
            "required": ["session_id", "raw_input"],
        },
    },
}

_DESIGN_OUTLINE = {
    "type": "function",
    "function": {
        "name": "design_outline",
        "description": (
            "基于结构化文本生成可执行大纲 JSON（五层架构），并为 L5 节点绑定数据源。"
            "这是 skill-factory 设计态六步流程的第 3+4 步，在 extract_structure 成功后调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "structured_text": {
                    "type": "string",
                    "description": "extract_structure 输出的结构化文本",
                },
            },
            "required": ["session_id", "structured_text"],
        },
    },
}

_PREVIEW_REPORT = {
    "type": "function",
    "function": {
        "name": "preview_report",
        "description": (
            "生成设计态预览版报告 HTML，供用户确认看网逻辑是否正确。"
            "这是 skill-factory 设计态六步流程的第 5 步，在 design_outline 成功后调用。"
            "完成后提示用户确认是否沉淀，等待用户明确确认后再调用 persist_skill。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
    },
}

_PERSIST_SKILL = {
    "type": "function",
    "function": {
        "name": "persist_skill",
        "description": (
            "将设计态成果沉淀为可复用看网能力，写入 skills/custom/ 目录。"
            "这是 skill-factory 设计态六步流程的第 6 步（最后一步）。"
            "重要：仅在用户明确说保存、沉淀、确认保存时才调用，不能主动触发。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "context_key": {
                    "type": "string",
                    "description": "设计态缓存 key（preview_report 返回的 context_key）",
                },
            },
            "required": ["session_id", "context_key"],
        },
    },
}

ALL_TOOLS: list[dict] = [
    _READ_SKILL_FILE,
    _GET_SESSION_STATUS,
    _SEARCH_SKILL,
    _GET_CURRENT_OUTLINE,
    _CLIP_OUTLINE,
    _INJECT_PARAMS,
    _EXECUTE_DATA,
    _RENDER_REPORT,
    _UNDERSTAND_INTENT,
    _EXTRACT_STRUCTURE,
    _DESIGN_OUTLINE,
    _PREVIEW_REPORT,
    _PERSIST_SKILL,
]

TOOL_NAMES = {t["function"]["name"] for t in ALL_TOOLS}
