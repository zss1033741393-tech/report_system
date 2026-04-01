"""章节定位模块 —— 将自然语言指令映射到 outline 中的 node_id。

两阶段定位：
1. 从大纲树构建编号索引（"第一章第二节" → node_id）
2. 对模糊表述（直接提章节名称）做关键字匹配
"""
import json
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 中文数字 → 阿拉伯数字映射
_CN_NUMS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_to_int(s: str) -> Optional[int]:
    """将中文数字字符串转换为整数，失败返回 None。"""
    if s.isdigit():
        return int(s)
    return _CN_NUMS.get(s)


def build_section_index(outline: dict) -> dict:
    """从大纲树构建章节编号索引。

    Returns:
        {
            "1": {"node_id": "...", "name": "...", "level": 3, "children": {
                "1.1": {"node_id": "...", "name": "...", "level": 4, "children": {
                    "1.1.1": {"node_id": "...", "name": "...", "level": 5}
                }}
            }},
            ...
        }
    """
    index = {}
    root_level = outline.get("level", 0)
    children = outline.get("children", [])

    # 确定章节起始层级（通常 L3=章, L4=节, L5=指标）
    if root_level <= 2:
        ch_nodes = [c for c in children if c.get("level") == 3]
    elif root_level == 3:
        has_l3 = any(c.get("level") == 3 for c in children)
        ch_nodes = [c for c in children if c.get("level") == 3] if has_l3 else [outline]
    elif root_level == 4:
        ch_nodes = [outline]
    else:
        ch_nodes = []

    for ch_i, ch_node in enumerate(ch_nodes, 1):
        ch_key = str(ch_i)
        ch_entry = {
            "node_id": ch_node.get("id", ""),
            "name": ch_node.get("name", ""),
            "level": ch_node.get("level", 3),
            "children": {},
        }
        index[ch_key] = ch_entry

        sec_nodes = [c for c in ch_node.get("children", []) if c.get("level") == 4]
        for sec_i, sec_node in enumerate(sec_nodes, 1):
            sec_key = f"{ch_i}.{sec_i}"
            sec_entry = {
                "node_id": sec_node.get("id", ""),
                "name": sec_node.get("name", ""),
                "level": sec_node.get("level", 4),
                "children": {},
            }
            ch_entry["children"][sec_key] = sec_entry

            ind_nodes = [c for c in sec_node.get("children", []) if c.get("level") == 5]
            for ind_i, ind_node in enumerate(ind_nodes, 1):
                ind_key = f"{ch_i}.{sec_i}.{ind_i}"
                sec_entry["children"][ind_key] = {
                    "node_id": ind_node.get("id", ""),
                    "name": ind_node.get("name", ""),
                    "level": ind_node.get("level", 5),
                    "children": {},
                }

    return index


def _flatten_index(index: dict) -> dict:
    """将嵌套的 index 展平为 {编号: entry} 映射。"""
    flat = {}

    def _walk(d):
        for k, v in d.items():
            flat[k] = v
            if v.get("children"):
                _walk(v["children"])

    _walk(index)
    return flat


def _parse_numbered_ref(instruction: str) -> Optional[str]:
    """从指令中解析出章节编号，如"第二章第一节" → "2.1"，"第三章" → "3"。"""
    # 匹配"第X章第Y节"
    m = re.search(r'第([一二三四五六七八九十\d]+)章第([一二三四五六七八九十\d]+)节', instruction)
    if m:
        ch = _cn_to_int(m.group(1))
        sec = _cn_to_int(m.group(2))
        if ch and sec:
            return f"{ch}.{sec}"

    # 匹配"第X章"
    m = re.search(r'第([一二三四五六七八九十\d]+)章', instruction)
    if m:
        ch = _cn_to_int(m.group(1))
        if ch:
            return str(ch)

    # 匹配"第X节"（无章编号时模糊处理）
    m = re.search(r'第([一二三四五六七八九十\d]+)节', instruction)
    if m:
        sec = _cn_to_int(m.group(1))
        if sec:
            return f"*.{sec}"

    return None


def _match_by_name(instruction: str, flat_index: dict) -> list:
    """通过名称关键词匹配，返回最匹配的 node_id 列表。"""
    matched = []
    for key, entry in flat_index.items():
        name = entry.get("name", "")
        # 取 name 的中文 2-gram 进行匹配
        zh_segs = re.findall(r'[\u4e00-\u9fff]+', name)
        for seg in zh_segs:
            for i in range(len(seg) - 1):
                bigram = seg[i:i + 2]
                if bigram in instruction:
                    matched.append((key, entry["node_id"], name))
                    break
            else:
                continue
            break
    return matched


def resolve_section(instruction: str, outline: dict) -> dict:
    """将自然语言指令映射到 outline 中的节点信息。

    Args:
        instruction: 用户的修改指令
        outline: 当前大纲 JSON

    Returns:
        {
            "node_ids": ["目标章节 node_id", ...],
            "l5_ids": ["目标 L5 指标 node_id", ...],
            "parsed_action": "定位说明",
        }
    """
    index = build_section_index(outline)
    flat = _flatten_index(index)

    if not flat:
        return {"node_ids": [], "l5_ids": [], "parsed_action": "大纲为空，无法定位章节"}

    node_ids = []
    l5_ids = []
    parsed_action = ""

    # 第一步：尝试编号定位
    ref = _parse_numbered_ref(instruction)
    if ref:
        if ".*." in ref:
            # 仅有节编号，在所有章中找对应节
            _, sec_num = ref.split(".")
            for key, entry in flat.items():
                if key.endswith(f".{sec_num}") and entry.get("level") == 4:
                    node_ids.append(entry["node_id"])
                    for child in entry.get("children", {}).values():
                        if child.get("level") == 5 and child.get("node_id"):
                            l5_ids.append(child["node_id"])
        elif ref in flat:
            entry = flat[ref]
            node_ids.append(entry["node_id"])
            # 收集该节点下所有 L5 指标
            for child_key, child in flat.items():
                if child_key.startswith(ref + ".") and child.get("level") == 5:
                    l5_ids.append(child["node_id"])
            parsed_action = f"定位到编号 {ref}：{entry.get('name', '')}"

    # 第二步：编号定位失败时用名称匹配
    if not node_ids:
        matches = _match_by_name(instruction, flat)
        if matches:
            # 取匹配度最高的（编号最具体的，即 key 最长的）
            matches.sort(key=lambda x: len(x[0]), reverse=True)
            key, nid, name = matches[0]
            node_ids.append(nid)
            for child_key, child in flat.items():
                if child_key.startswith(key + ".") and child.get("level") == 5:
                    l5_ids.append(child["node_id"])
            parsed_action = f"关键词匹配到：{name}"

    if not node_ids:
        parsed_action = "未能定位到具体章节，将对整体报告操作"

    return {"node_ids": node_ids, "l5_ids": l5_ids, "parsed_action": parsed_action}


def collect_all_node_ids(outline: dict) -> set:
    """递归收集大纲中所有 node_id。"""
    ids = set()
    nid = outline.get("id", "")
    if nid:
        ids.add(nid)
    for child in outline.get("children", []):
        ids.update(collect_all_node_ids(child))
    return ids


def collect_l5_nodes_under(outline: dict, target_node_ids: list) -> list:
    """收集目标节点（含子树）下所有 L5 节点。"""
    result = []

    def _walk(node, in_target):
        is_target = node.get("id", "") in target_node_ids
        if is_target or in_target:
            if node.get("level") == 5:
                result.append(node)
            for child in node.get("children", []):
                _walk(child, True)
        else:
            for child in node.get("children", []):
                _walk(child, False)

    _walk(outline, False)
    return result
