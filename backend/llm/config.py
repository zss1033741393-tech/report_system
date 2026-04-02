"""LLM 配置。

LLMConfig dataclass 保持不变（所有使用方 import 它），
场景配置从 configs/llm_models.yaml 加载。
"""
from dataclasses import dataclass, field

from llm.config_loader import get_llm_config_loader


@dataclass
class LLMConfig:
    model: str = ""
    temperature: float = 0.6
    top_p: float = 0.95
    max_tokens: int = 16000
    response_format: str = "text"
    timeout_connect: int = 60
    timeout_read: int = 600
    timeout_total: int = 660
    stream: bool = True
    max_retry: int = 3
    extra_payload: dict = field(default_factory=dict)


def _load(scenario: str) -> LLMConfig:
    return get_llm_config_loader().build_llm_config(scenario)


# 场景配置（从 YAML 加载）
REACT_AGENT_CONFIG = _load("react_agent")
PLANNER_CONFIG = _load("planner")
REFLECTOR_CONFIG = _load("reflector")
ANCHOR_SELECT_CONFIG = _load("anchor_select")
SKILL_FACTORY_JSON_CONFIG = _load("skill_factory_json")
SKILL_FACTORY_OUTLINE_CONFIG = _load("skill_factory_outline")
REPORT_WRITER_CONFIG = _load("report_writer")
SKILL_ROUTER_CONFIG = _load("skill_router")
