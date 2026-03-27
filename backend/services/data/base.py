"""数据服务抽象基类。所有数据源（Mock/SQL/API）实现此接口。"""
from abc import ABC, abstractmethod


class DataServiceBase(ABC):
    @abstractmethod
    async def execute(self, binding_config: dict, params: dict) -> dict:
        """
        执行数据查询。

        Args:
            binding_config: 绑定配置（来自 bindings.json）
            params: 运行时参数（行业、阈值等）

        Returns:
            结构化数据，格式统一：
            {"data_type": "PIE_CHART|BAR_CHART|TABLE|SINGLE_VALUE|HEATMAP",
             "title": "...", "data": [...], "params_used": {...}}
        """
        pass
