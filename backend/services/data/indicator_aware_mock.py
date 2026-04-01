"""指标感知 Mock 服务 —— 根据 paragraph 模板反向生成匹配的 Mock 数据。

与 MockDataService 的区别：返回值额外携带 metric_values 字段，
为每个指标的 paragraph.metrics 中的占位符提供填充值，
使 report_writer 可以渲染出完整的 narrative 文字而非裸占位符。
"""
import json
import logging
import os
import random

from services.data.base import DataServiceBase
from services.data.mock_data_service import MockDataService

logger = logging.getLogger(__name__)

_IND_PATH = os.path.join(os.path.dirname(__file__), "default_indicators.json")

# 行政区列表（广西/通用）
_DISTRICTS = ["江南区", "青秀区", "兴宁区", "邕宁区", "西乡塘区", "良庆区", "武鸣区", "横县"]
_INDUSTRIES = ["金融", "政府", "医疗", "云电竞", "科教", "交通", "制造"]


def _load_indicators_by_name() -> dict:
    """加载 default_indicators.json，以 indicator_name 为 key 返回 paragraph 字典。"""
    try:
        with open(_IND_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        result = {}
        for ind_data in raw.values():
            name = ind_data.get("indicator_name", "")
            if name:
                result[name] = ind_data.get("paragraph", {})
        return result
    except Exception as e:
        logger.warning(f"加载 default_indicators.json 失败: {e}")
        return {}


_IND_MAP = _load_indicators_by_name()


def _seeded_rng(node_name: str) -> random.Random:
    """基于节点名生成固定种子的随机数生成器，保证同一指标每次结果一致。"""
    return random.Random(hash(node_name) & 0xFFFFFFFF)


def _gen_metric_values(node_name: str, metrics: list, params: dict) -> dict:
    """为 metrics 列表中的每个占位符生成合理的 Mock 值。"""
    rng = _seeded_rng(node_name)
    mv = {}

    for metric in metrics:
        # 阈值类：优先从 params 取用户注入值
        if metric == "threshold":
            val = params.get("threshold", 80)
            if isinstance(val, dict):
                val = val.get("value", 80)
            mv[metric] = val
            continue

        if metric == "min_free_slots":
            val = params.get("min_free_slots", 2)
            if isinstance(val, dict):
                val = val.get("value", 2)
            mv[metric] = val
            continue

        # 企业总量
        if metric == "total_enterprises":
            mv[metric] = rng.randint(150, 450)

        # 行业 Top 描述
        elif metric == "top_industries":
            inds = rng.sample(_INDUSTRIES, 3)
            counts = sorted([rng.randint(20, 80) for _ in inds], reverse=True)
            mv[metric] = "、".join(f"{i}({c}家)" for i, c in zip(inds, counts))

        # 高价值行业占比
        elif metric == "high_value_ratio":
            mv[metric] = round(rng.uniform(45, 75), 1)

        # 行政区分布描述
        elif metric == "district_distribution":
            districts = rng.sample(_DISTRICTS, 3)
            counts = [rng.randint(20, 80) for _ in districts]
            mv[metric] = "、".join(f"{d}({c}家)" for d, c in zip(districts, counts))

        # Top 行政区名称
        elif metric in ("top_district", "top_covered_district", "top_uncovered_district"):
            mv[metric] = rng.choice(_DISTRICTS)

        # Top 行政区企业数
        elif metric == "top_district_count":
            mv[metric] = rng.randint(30, 120)

        # 覆盖率
        elif metric == "coverage_rate":
            mv[metric] = round(rng.uniform(55, 90), 1)

        # 已覆盖企业数
        elif metric == "covered_enterprises":
            total = rng.randint(150, 400)
            mv[metric] = int(total * rng.uniform(0.5, 0.85))

        # 未覆盖企业数
        elif metric == "uncovered_enterprises":
            covered = mv.get("covered_enterprises", rng.randint(80, 200))
            mv[metric] = max(10, rng.randint(20, covered // 2))

        # 覆盖分布描述
        elif metric == "covered_district_distribution":
            districts = rng.sample(_DISTRICTS, 3)
            counts = [rng.randint(10, 60) for _ in districts]
            mv[metric] = "、".join(f"{d}({c}家)" for d, c in zip(districts, counts))

        # 未覆盖分布描述
        elif metric == "uncovered_district_distribution":
            districts = rng.sample(_DISTRICTS, 3)
            counts = [rng.randint(5, 40) for _ in districts]
            mv[metric] = "、".join(f"{d}({c}家)" for d, c in zip(districts, counts))

        # 低阶交叉利用率区间
        elif metric == "low_util_count":
            mv[metric] = rng.randint(15, 50)
        elif metric == "mid_util_count":
            mv[metric] = rng.randint(20, 60)
        elif metric == "high_util_count":
            mv[metric] = rng.randint(10, 40)

        # 平均利用率
        elif metric == "avg_slot_util":
            mv[metric] = round(rng.uniform(40, 75), 1)

        # 超载数量
        elif metric == "overload_count":
            mv[metric] = rng.randint(5, 40)

        # 可部署子架数
        elif metric == "eligible_chassis_count":
            mv[metric] = rng.randint(20, 150)

        # fgOTN 状态分布
        elif metric == "direct_support_count":
            mv[metric] = rng.randint(30, 100)
        elif metric == "upgrade_count":
            mv[metric] = rng.randint(20, 80)
        elif metric == "new_chassis_count":
            mv[metric] = rng.randint(10, 50)
        elif metric == "unsupported_count":
            mv[metric] = rng.randint(5, 30)

        # 通用兜底
        else:
            mv[metric] = rng.randint(1, 200)

    return mv


class IndicatorAwareMockService(DataServiceBase):
    """指标感知 Mock 服务。

    在 MockDataService 的基础上，为返回值附加 metric_values 字段，
    以匹配 paragraph.metrics 中声明的占位符，使 narrative 文字可以被完整渲染。
    """

    def __init__(self, mock_data_dir: str = "./data/mock"):
        self._fallback = MockDataService(mock_data_dir)

    async def execute(self, binding_config: dict, params: dict) -> dict:
        node_name = binding_config.get("node_name", "")

        # 优先从文件加载（文件中若已含 metric_values 则直接返回）
        file_data = self._fallback._load_from_file(node_name)
        if file_data:
            return file_data

        # 通过 fallback 生成基础 Mock 数据
        base_data = await self._fallback.execute(binding_config, params)

        # 查找 paragraph 模板，生成 metric_values
        paragraph = _IND_MAP.get(node_name, {})
        metrics = paragraph.get("metrics", [])
        if metrics:
            base_data["metric_values"] = _gen_metric_values(node_name, metrics, params)

        return base_data
