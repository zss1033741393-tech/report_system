"""数据服务工厂 —— 按配置返回合适的数据服务实现。

当前支持：
  mock / indicator_mock → IndicatorAwareMockService（默认）

预留扩展：
  nl2sql → NL2SQLDataService（未来实现）
  api    → APIDataService（未来实现）
"""
import logging

from services.data.base import DataServiceBase

logger = logging.getLogger(__name__)


def create_data_service(config: dict = None) -> DataServiceBase:
    """工厂函数：根据配置返回数据服务实例。

    Args:
        config: 可选配置字典，支持 data_source 键（默认 'mock'）

    Returns:
        DataServiceBase 的具体实现
    """
    if config is None:
        config = {}
    source = config.get("data_source", "mock").lower()

    if source in ("mock", "indicator_mock", ""):
        from services.data.indicator_aware_mock import IndicatorAwareMockService
        return IndicatorAwareMockService()

    logger.warning(f"未知数据源类型 '{source}'，回退到 IndicatorAwareMockService")
    from services.data.indicator_aware_mock import IndicatorAwareMockService
    return IndicatorAwareMockService()
