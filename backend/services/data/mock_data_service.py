"""Mock 数据服务 —— 返回模拟数据，结构与真实数据源一致。

预留真实数据源替换口：实现 DataServiceBase 接口即可替换。
"""
import json
import logging
import os
import random
from typing import Optional

from services.data.base import DataServiceBase

logger = logging.getLogger(__name__)


class MockType:
    PIE_CHART = "PIE_CHART"
    BAR_CHART = "BAR_CHART"
    TABLE = "TABLE"
    SINGLE_VALUE = "SINGLE_VALUE"
    HEATMAP = "HEATMAP"
    LINE_CHART = "LINE_CHART"


# 指标名 → Mock 数据类型 映射
MOCK_DATA_REGISTRY = {
    "企业行业分布": MockType.PIE_CHART,
    "企业行政区分布": MockType.BAR_CHART,
    "企业城市分布": MockType.HEATMAP,
    "企业详情": MockType.TABLE,
    "OTN站点企业覆盖率": MockType.SINGLE_VALUE,
    "OTN站点覆盖企业数量": MockType.SINGLE_VALUE,
    "OTN站点覆盖企业行政区域分布": MockType.BAR_CHART,
    "OTN站点未覆盖企业行政区域分布": MockType.BAR_CHART,
    "站点低阶交叉容量利用率区间分布": MockType.BAR_CHART,
    "站点设备低阶交叉容量使用详情": MockType.TABLE,
    "子架槽位利用率区间分布": MockType.BAR_CHART,
    "子架业务槽位使用详情": MockType.TABLE,
    "站点支持部署fgOTN单板的子架详情": MockType.TABLE,
    "站点支持部署fgOTN单板的状态分布": MockType.PIE_CHART,
    "站点覆盖企业详情": MockType.TABLE,
    "站点OTN下沉统计": MockType.BAR_CHART,
}


class MockDataService(DataServiceBase):

    def __init__(self, mock_data_dir: str = "./data/mock"):
        self._dir = mock_data_dir

    async def execute(self, binding_config: dict, params: dict) -> dict:
        node_name = binding_config.get("node_name", "")
        data_type = binding_config.get("mock_config", {}).get("data_type", "")

        # 优先从文件加载预定义 mock
        file_data = self._load_from_file(node_name)
        if file_data:
            return file_data

        # 否则按类型生成
        if not data_type:
            data_type = MOCK_DATA_REGISTRY.get(node_name, MockType.TABLE)

        generator = {
            MockType.PIE_CHART: self._gen_pie,
            MockType.BAR_CHART: self._gen_bar,
            MockType.TABLE: self._gen_table,
            MockType.SINGLE_VALUE: self._gen_single,
            MockType.HEATMAP: self._gen_heatmap,
            MockType.LINE_CHART: self._gen_line,
        }.get(data_type, self._gen_table)

        return generator(node_name, params)

    def _load_from_file(self, node_name: str) -> Optional[dict]:
        safe_name = node_name.replace("/", "_").replace(" ", "_")
        fp = os.path.join(self._dir, f"{safe_name}.json")
        if os.path.isfile(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    @staticmethod
    def _gen_pie(name: str, params: dict) -> dict:
        industries = params.get("industry", "金融,政府,医疗,云电竞,科教").split(",")
        return {
            "data_type": MockType.PIE_CHART,
            "title": name,
            "data": [{"name": ind.strip(), "value": random.randint(10, 100)} for ind in industries],
            "params_used": params,
        }

    @staticmethod
    def _gen_bar(name: str, params: dict) -> dict:
        categories = ["0-60%", "60-80%", "80%以上"] if "利用率" in name else [f"区域{i}" for i in range(1, 6)]
        return {
            "data_type": MockType.BAR_CHART,
            "title": name,
            "data": [{"category": c, "value": random.randint(5, 80)} for c in categories],
            "params_used": params,
        }

    @staticmethod
    def _gen_table(name: str, params: dict) -> dict:
        rows = []
        for i in range(1, 6):
            rows.append({"站点": f"站点{i:03d}", "设备": f"设备型号{chr(64+i)}", "利用率": f"{random.randint(20,95)}%"})
        return {
            "data_type": MockType.TABLE,
            "title": name,
            "columns": list(rows[0].keys()) if rows else [],
            "data": rows,
            "params_used": params,
        }

    @staticmethod
    def _gen_single(name: str, params: dict) -> dict:
        return {
            "data_type": MockType.SINGLE_VALUE,
            "title": name,
            "data": {"value": round(random.uniform(30, 95), 1), "unit": "%"},
            "params_used": params,
        }

    @staticmethod
    def _gen_heatmap(name: str, params: dict) -> dict:
        cities = ["南宁", "柳州", "桂林", "玉林", "百色"]
        return {
            "data_type": MockType.HEATMAP,
            "title": name,
            "data": [{"city": c, "lat": 22.8+i*0.5, "lng": 108.3+i*0.3, "value": random.randint(10, 200)}
                     for i, c in enumerate(cities)],
            "params_used": params,
        }

    @staticmethod
    def _gen_line(name: str, params: dict) -> dict:
        return {
            "data_type": MockType.LINE_CHART,
            "title": name,
            "data": [{"month": f"2026-{m:02d}", "value": random.randint(50, 100)} for m in range(1, 7)],
            "params_used": params,
        }
