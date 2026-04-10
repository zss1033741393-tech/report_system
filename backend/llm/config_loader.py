"""LLM 配置加载器。

从 YAML 文件加载模型配置，支持：
- 多模型服务节点配置
- 环境变量替换（${ENV_VAR} 格式）
- 场景化配置映射
"""
import os
import re
import logging
import yaml
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "configs"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "llm_models.yaml"


def _resolve_env_vars(value):
    """解析字符串中的环境变量引用 ${VAR_NAME}。"""
    if not isinstance(value, str):
        return value
    pattern = r'\$\{([^}]+)\}'
    for var_name in re.findall(pattern, value):
        value = value.replace(f"${{{var_name}}}", os.environ.get(var_name, ""))
    return value


def _resolve_dict_env_vars(data: dict) -> dict:
    """递归解析字典中所有环境变量引用。"""
    result = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = _resolve_dict_env_vars(value)
        elif isinstance(value, list):
            result[key] = [
                _resolve_dict_env_vars(item) if isinstance(item, dict) else _resolve_env_vars(item)
                for item in value
            ]
        else:
            result[key] = _resolve_env_vars(value)
    return result


@dataclass
class ModelProvider:
    """模型服务节点配置。"""
    base_url: str = ""
    api_key: str = ""
    timeout_connect: int = 60
    timeout_read: int = 600
    timeout_total: int = 660
    ssl_verify: bool = True
    think_tag_mode: str = "qwen3"
    proxy: str = ""


@dataclass
class ModelDefinition:
    """单个模型定义。"""
    provider: str = "default"
    model: str = ""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.6
    top_p: float = 0.95
    max_tokens: int = 16000
    stream: bool = True
    max_retry: int = 3
    extra_payload: dict = field(default_factory=dict)


class LLMConfigLoader:
    """LLM 配置加载器。"""

    def __init__(self, config_path: str = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._providers: dict[str, ModelProvider] = {}
        self._models: dict[str, ModelDefinition] = {}
        self._scenarios: dict[str, dict] = {}
        self._load()

    def _load(self):
        if not self.config_path.exists():
            logger.warning(f"LLM 配置文件不存在: {self.config_path}，使用默认配置")
            self._providers["default"] = ModelProvider()
            return

        with open(self.config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        config = _resolve_dict_env_vars(raw)

        # 加载 provider
        dc = config.get("default", {})
        self._providers["default"] = ModelProvider(
            base_url=dc.get("base_url", ""),
            api_key=dc.get("api_key", ""),
            timeout_connect=dc.get("timeout_connect", 60),
            timeout_read=dc.get("timeout_read", 600),
            timeout_total=dc.get("timeout_total", 660),
            ssl_verify=dc.get("ssl_verify", True),
            think_tag_mode=dc.get("think_tag_mode", "qwen3"),
            proxy=dc.get("proxy", ""),
        )

        # 加载 models
        for name, cfg in config.get("models", {}).items():
            self._models[name] = ModelDefinition(
                provider=cfg.get("provider", "default"),
                model=cfg.get("model", name),
                base_url=cfg.get("base_url"),
                api_key=cfg.get("api_key"),
                temperature=cfg.get("temperature", 0.6),
                top_p=cfg.get("top_p", 0.95),
                max_tokens=cfg.get("max_tokens", 16000),
                stream=cfg.get("stream", True),
                max_retry=cfg.get("max_retry", 3),
                extra_payload=cfg.get("extra_payload", {}),
            )

        # 加载 scenarios
        self._scenarios = config.get("scenarios", {})
        logger.info(f"LLM 配置加载完成: {len(self._models)} models, {len(self._scenarios)} scenarios")

    def get_provider(self, name: str = "default") -> ModelProvider:
        return self._providers.get(name, self._providers["default"])

    def get_model(self, name: str) -> Optional[ModelDefinition]:
        return self._models.get(name)

    def build_llm_config(self, scenario: str) -> "LLMConfig":
        """构建 LLMConfig 对象。"""
        from llm.config import LLMConfig

        sc = self._scenarios.get(scenario, {})
        model_name = sc.get("model", "qwen3.5-27b")
        model_def = self.get_model(model_name)
        provider = self.get_provider(model_def.provider if model_def else "default")

        return LLMConfig(
            model=model_def.model if model_def else model_name,
            temperature=sc.get("temperature", model_def.temperature if model_def else 0.6),
            top_p=sc.get("top_p", model_def.top_p if model_def else 0.95),
            max_tokens=sc.get("max_tokens", model_def.max_tokens if model_def else 16000),
            response_format=sc.get("response_format", "text"),
            timeout_connect=provider.timeout_connect,
            timeout_read=provider.timeout_read,
            timeout_total=provider.timeout_total,
            stream=sc.get("stream", model_def.stream if model_def else True),
            max_retry=model_def.max_retry if model_def else 3,
            extra_payload=sc.get("extra_payload", model_def.extra_payload if model_def else {}),
        )

    def get_base_url(self, model_name: str = None) -> str:
        if model_name:
            md = self.get_model(model_name)
            if md and md.base_url:
                return md.base_url
            if md:
                return self.get_provider(md.provider).base_url
        return self._providers["default"].base_url

    def get_api_key(self, model_name: str = None) -> str:
        if model_name:
            md = self.get_model(model_name)
            if md and md.api_key:
                return md.api_key
            if md:
                return self.get_provider(md.provider).api_key
        return self._providers["default"].api_key

    def get_think_tag_mode(self, model_name: str = None) -> str:
        if model_name:
            md = self.get_model(model_name)
            if md:
                return self.get_provider(md.provider).think_tag_mode
        return self._providers["default"].think_tag_mode

    def get_model_name(self) -> str:
        if self._scenarios:
            return next(iter(self._scenarios.values())).get("model", "qwen3.5-27b")
        return "qwen3.5-27b"

    def get_proxy(self) -> str:
        return self._providers["default"].proxy

    def get_ssl_verify(self) -> bool:
        return self._providers["default"].ssl_verify

    def get_timeout_connect(self) -> int:
        return self._providers["default"].timeout_connect

    def get_timeout_read(self) -> int:
        return self._providers["default"].timeout_read

    def get_timeout_total(self) -> int:
        return self._providers["default"].timeout_total


# 全局单例
_loader: Optional[LLMConfigLoader] = None


def get_llm_config_loader() -> LLMConfigLoader:
    global _loader
    if _loader is None:
        _loader = LLMConfigLoader()
    return _loader
