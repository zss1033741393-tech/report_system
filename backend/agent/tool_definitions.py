"""工具定义 —— ReAct 引擎的 12 个工具。

每个工具包含：
  - name: 工具名（LLM 调用时使用）
  - description: LLM 决策依据（精心设计，影响调用质量）
  - parameters: JSON Schema（OpenAI function calling 格式）
"""

# ─── 基础工具 ───────────────────────────────────────────────────────────────

READ_SKILL_FILE = {
    "type": "function",
    "function": {
        "name": "read_skill_file",
        "description": (
            "读取指定路径的 SKILL.md 文件全文，获取该技能的完整工作流指导。"
            "执行复杂的多步骤任务前，先调用此工具了解正确的操作顺序和规则，避免错误。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "SKILL.md 的路径，例如 skills/builtin/skill-factory/SKILL.md",
                }
            },
            "required": ["path"],
        },
    },
}

GET_SESSION_STATUS = {
    "type": "function",
    "function": {
        "name": "get_session_status",
        "description": (
            "获取当前会话的完整状态：是否已有大纲、是否已有报告、是否有待沉淀的设计态缓存。"
            "处理用户请求前先调用此工具，了解当前上下文，避免重复操作。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                }
            },
            "required": ["session_id"],
        },
    },
}

# ─── 运行态工具 ──────────────────────────────────────────────────────────────

SEARCH_SKILL = {
    "type": "function",
    "function": {
        "name": "search_skill",
        "description": (
            "在知识库中搜索与用户问题匹配的已沉淀看网能力，返回大纲模板和相关场景。"
            "用户提出看网分析需求时，先调用此工具检索是否已有现成的看网逻辑，再决定是否需要生成新大纲。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户的分析需求，用自然语言描述",
                }
            },
            "required": ["query"],
        },
    },
}

GET_CURRENT_OUTLINE = {
    "type": "function",
    "function": {
        "name": "get_current_outline",
        "description": (
            "获取当前会话的完整大纲 JSON 结构。"
            "在执行裁剪、参数注入、报告生成前，必须先调用此工具了解大纲的当前状态和节点结构。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                }
            },
            "required": ["session_id"],
        },
    },
}

CLIP_OUTLINE = {
    "type": "function",
    "function": {
        "name": "clip_outline",
        "description": (
            "按用户裁剪指令删除大纲中的指定节点或筛选保留部分节点。"
            "用户说'不看XX'/'删除XX'/'去掉XX'时调用。"
            "执行后如果已有报告，必须再调用 execute_data + render_report 重新生成报告。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                },
                "instruction": {
                    "type": "string",
                    "description": "用户的裁剪指令原文，例如'删除低阶交叉节点'",
                },
            },
            "required": ["session_id", "instruction"],
        },
    },
}

INJECT_PARAMS = {
    "type": "function",
    "function": {
        "name": "inject_params",
        "description": (
            "注入运行时参数，如行业过滤、阈值修改、时间范围等。"
            "用户说'只看XX行业'/'阈值改为XX'/'时间改为XX'时调用。"
            "执行后如果已有报告，必须再调用 execute_data + render_report 重新生成报告。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                },
                "param_key": {
                    "type": "string",
                    "description": "参数名，例如 industry、threshold、time_range",
                },
                "param_value": {
                    "type": "string",
                    "description": "参数值，例如'金融'、'0.8'、'2024Q1'",
                },
                "target_node": {
                    "type": "string",
                    "description": "目标节点名（不指定则全局生效），可选",
                },
            },
            "required": ["session_id", "param_key", "param_value"],
        },
    },
}

EXECUTE_DATA = {
    "type": "function",
    "function": {
        "name": "execute_data",
        "description": (
            "执行大纲中所有评估指标节点的数据查询（Mock/SQL/API），返回结构化数据结果。"
            "生成报告前的必要步骤。裁剪大纲或修改参数后也需要重新执行此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                },
            },
            "required": ["session_id"],
        },
    },
}

RENDER_REPORT = {
    "type": "function",
    "function": {
        "name": "render_report",
        "description": (
            "基于当前大纲和数据执行结果，渲染生成完整的 HTML 报告。"
            "这是生成报告的最后一步，必须在 execute_data 成功后才能调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                },
            },
            "required": ["session_id"],
        },
    },
}

# ─── 设计态工具（skill-factory 六步）────────────────────────────────────────

UNDERSTAND_INTENT = {
    "type": "function",
    "function": {
        "name": "understand_intent",
        "description": (
            "【设计态专用 —— 严格门槛】"
            "仅当同时满足以下两个条件时才能调用："
            "①用户输入了 ≥100 字的完整看网逻辑描述（含场景/指标/判断逻辑等要素）；"
            "②用户明确表达了创建/设计/沉淀新看网能力的意图。"
            "对于普通分析请求（如'分析网络容量'）、简短提问、修改报告等请求，"
            "严禁调用此工具。这是 skill-factory 六步流程的第一步，"
            "调用前应先通过 read_skill_file 读取 skill-factory 工作流。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                },
                "expert_input": {
                    "type": "string",
                    "description": "专家输入的看网逻辑原文",
                },
            },
            "required": ["session_id", "expert_input"],
        },
    },
}

EXTRACT_STRUCTURE = {
    "type": "function",
    "function": {
        "name": "extract_structure",
        "description": (
            "【设计态专用 —— 严格门槛】"
            "将看网逻辑格式化为结构化 Markdown，映射五层知识架构（场景→维度→指标）。"
            "这是 skill-factory 的第二步，必须在 understand_intent 成功返回后才能调用。"
            "仅限设计态场景（用户输入 ≥100 字看网逻辑 + 明确创建意图），"
            "运行态请求严禁调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                },
                "raw_input": {
                    "type": "string",
                    "description": "专家输入的原始文本（同 understand_intent 的 expert_input）",
                },
            },
            "required": ["session_id", "raw_input"],
        },
    },
}

DESIGN_OUTLINE = {
    "type": "function",
    "function": {
        "name": "design_outline",
        "description": (
            "【设计态专用 —— 严格门槛】"
            "基于结构化文本生成可执行的五层大纲 JSON（场景→维度→指标→子指标→评估点）。"
            "这是 skill-factory 的第三步，必须在 extract_structure 成功后才能调用。"
            "仅限设计态场景，运行态请求严禁调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                },
            },
            "required": ["session_id"],
        },
    },
}

BIND_DATA = {
    "type": "function",
    "function": {
        "name": "bind_data",
        "description": (
            "【设计态专用 —— 严格门槛】"
            "为大纲底层评估指标节点绑定数据源（SQL/API/Mock）。"
            "这是 skill-factory 的第四步，必须在 design_outline 成功后才能调用。"
            "仅限设计态场景，运行态请求严禁调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                },
            },
            "required": ["session_id"],
        },
    },
}

PREVIEW_REPORT = {
    "type": "function",
    "function": {
        "name": "preview_report",
        "description": (
            "【设计态专用 —— 严格门槛】"
            "生成预览版报告 HTML，供用户确认看网逻辑是否符合预期。"
            "这是 skill-factory 的第五步，必须在 bind_data 成功后才能调用，"
            "完成后等待用户明确确认是否沉淀，不得自动调用 persist_skill。"
            "仅限设计态场景，运行态报告生成请使用 render_report 工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                },
            },
            "required": ["session_id"],
        },
    },
}

PERSIST_SKILL = {
    "type": "function",
    "function": {
        "name": "persist_skill",
        "description": (
            "【设计态专用 —— 严格门槛】"
            "将设计态成果沉淀为可复用的看网能力，写入知识库。"
            "这是 skill-factory 的第六步（最后一步）。"
            "调用条件：①已完成前五步（understand_intent→preview_report）；"
            "②用户在看到预览报告后明确说'保存'/'沉淀'/'确认'。"
            "不得自动执行，不得在未完成前五步时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                },
                "context_key": {
                    "type": "string",
                    "description": "设计态缓存的 context key（从 preview_report 结果中获取）",
                },
            },
            "required": ["session_id", "context_key"],
        },
    },
}

# ─── 工具集合 ─────────────────────────────────────────────────────────────────

ALL_TOOLS = [
    READ_SKILL_FILE,
    GET_SESSION_STATUS,
    SEARCH_SKILL,
    GET_CURRENT_OUTLINE,
    CLIP_OUTLINE,
    INJECT_PARAMS,
    EXECUTE_DATA,
    RENDER_REPORT,
    UNDERSTAND_INTENT,
    EXTRACT_STRUCTURE,
    DESIGN_OUTLINE,
    BIND_DATA,
    PREVIEW_REPORT,
    PERSIST_SKILL,
]

# 工具名 → schema 快速查找
TOOL_SCHEMA_MAP = {t["function"]["name"]: t for t in ALL_TOOLS}
