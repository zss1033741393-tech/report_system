"""IndicatorResolver：按优先级查找 L5 节点的 paragraph 模板。

查找顺序：
1. Skill 专属 indicators.json（skill_dir/references/indicators.json）
2. 系统预置 default_indicators.json
3. 兜底：返回空 paragraph
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_EMPTY_PARAGRAPH = {
    "content": "",
    "metrics": [],
    "tables": [],
    "data_source": "Mock",
    "params": {},
}


class IndicatorResolver:

    def __init__(self, default_indicators_path: str):
        self._default: dict = self._load(default_indicators_path)
        logger.info(f"IndicatorResolver: 加载系统预置 {len(self._default)} 个指标模板")

    def resolve(self, node_id: str, node_name: str, skill_dir: str = "") -> dict:
        """返回 paragraph dict（深拷贝，避免运行时参数污染模板）。"""
        import copy

        # 1. Skill 专属
        if skill_dir:
            skill_indicators = self._load_skill(skill_dir)
            if node_id in skill_indicators:
                return copy.deepcopy(skill_indicators[node_id]["paragraph"])

        # 2. 系统预置（按 node_id 精确匹配）
        if node_id in self._default:
            return copy.deepcopy(self._default[node_id]["paragraph"])

        # 3. 系统预置（按 indicator_name 模糊匹配）
        for v in self._default.values():
            if v.get("indicator_name") == node_name:
                return copy.deepcopy(v["paragraph"])

        # 4. 兜底空模板
        return copy.deepcopy(_EMPTY_PARAGRAPH)

    def _load(self, path: str) -> dict:
        if not path or not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"IndicatorResolver: 加载失败 {path}: {e}")
            return {}

    def _load_skill(self, skill_dir: str) -> dict:
        path = os.path.join(skill_dir, "references", "indicators.json")
        return self._load(path)
