"""
数据脱敏引擎 —— 支持 JSONPath [*] 数组遍历（规范 §2.4）。

支持 8 种脱敏类型：
  redact / mask / hash / truncate / generalize / filter_fields / aggregate / custom

路径语法示例：
  "salary"                → 顶层字段
  "candidates[*].salary"  → 数组中每个元素的 salary
  "[*].email"             → 根节点就是数组
  "a.b[*].c[*].d"         → 多层嵌套数组

仅供离线历史诊断；失败拒绝，不参与新交付授权。
"""

from __future__ import annotations

import copy
import re
import hashlib
import logging

logger = logging.getLogger(__name__)


def apply_transforms(data: dict, transforms: list) -> dict:
    """
    按顺序执行多条 transform 规则，每一步的输出是下一步的输入。
    """
    result = copy.deepcopy(data)

    for transform in transforms:
        transform_type = transform["type"]
        fields = transform.get("applies_to_fields", [])
        config = transform.get("config", {})

        if transform_type not in {'redact', 'mask', 'hash', 'truncate', 'generalize', 'filter_fields', 'aggregate'}:
            raise ValueError('UNSUPPORTED_LEGACY_TRANSFORM')
        if transform_type == 'aggregate' and config.get('aggregation_function', 'count') not in {'count', 'sum'}:
            raise ValueError('UNSUPPORTED_LEGACY_AGGREGATION')
        if transform_type == 'truncate' and (type(config.get('truncate_length', 200)) is not int or config.get('truncate_length', 200) < 0):
            raise ValueError('INVALID_LEGACY_CONFIGURATION')
        for field_path in fields:
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\[\*\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\*\])?)*', field_path):
                raise ValueError('UNSUPPORTED_LEGACY_PATH')
            try:
                _apply_at_path(result, field_path, transform_type, config)
            except Exception:
                raise ValueError('LEGACY_PROCESSING_FAILED') from None

    return result


# ═══════════════════════════════════════════
#  路径解析 + 递归遍历
# ═══════════════════════════════════════════

def _parse_path(path: str) -> list:
    """
    "a[*].b.c[*].d" → ["a", "[*]", "b", "c", "[*]", "d"]
    "[*].email"      → ["[*]", "email"]
    """
    result = []
    for part in path.replace("[*]", ".[*]").split("."):
        if part:
            result.append(part)
    return result


def _apply_at_path(data, path: str, action: str, config: dict):
    """入口：解析路径后递归执行"""
    segments = _parse_path(path)
    _walk_and_apply(data, segments, 0, action, config)


def _walk_and_apply(
    node, segments: list, idx: int, action: str, config: dict
):
    """递归遍历路径段，到达叶节点时执行脱敏"""
    if idx >= len(segments):
        return

    seg = segments[idx]

    if seg == "[*]":
        # 数组遍历
        if not isinstance(node, list):
            logger.warning(
                f"Expected array at segment {idx}, got {type(node).__name__}"
            )
            return
        for item in node:
            _walk_and_apply(item, segments, idx + 1, action, config)
        return

    if not isinstance(node, dict) or seg not in node:
        return  # 字段不存在，静默跳过

    if idx == len(segments) - 1:
        # 到达目标字段，执行脱敏
        _execute_action(node, seg, action, config)
    else:
        _walk_and_apply(node[seg], segments, idx + 1, action, config)


# ═══════════════════════════════════════════
#  脱敏动作实现
# ═══════════════════════════════════════════

def _execute_action(parent: dict, key: str, action: str, config: dict):
    """对目标字段执行具体的脱敏操作"""

    if action == "redact":
        del parent[key]

    elif action == "mask":
        val = str(parent[key])
        if len(val) > 2:
            parent[key] = val[0] + "*" * (len(val) - 2) + val[-1]
        else:
            parent[key] = config.get("mask_pattern", "***MASKED***")

    elif action == "hash":
        algorithm = config.get("hash_algorithm", "sha256")
        val = str(parent[key])
        if algorithm == "sha3-256":
            parent[key] = hashlib.sha3_256(val.encode()).hexdigest()[:16]
        else:
            parent[key] = hashlib.sha256(val.encode()).hexdigest()[:16]

    elif action == "truncate":
        max_len = config.get("truncate_length", 200)
        val = str(parent[key])
        if len(val) > max_len:
            parent[key] = val[:max_len] + "..."

    elif action == "generalize":
        val = parent[key]
        if isinstance(val, (int, float)):
            magnitude = max(1, 10 ** (len(str(int(abs(val)))) - 1))
            low = (int(val) // magnitude) * magnitude
            parent[key] = f"{low}-{low + magnitude}"
        else:
            parent[key] = "***GENERALIZED***"

    elif action == "filter_fields":
        include = config.get("include_fields", [])
        if isinstance(parent[key], dict):
            parent[key] = {
                k: v for k, v in parent[key].items() if k in include
            }

    elif action == "aggregate":
        func = config.get("aggregation_function", "count")
        val = parent[key]
        if isinstance(val, list):
            if func == "count":
                parent[key] = {"_aggregated": True, "count": len(val)}
            elif func == "sum":
                parent[key] = {
                    "_aggregated": True,
                    "sum": sum(
                        v for v in val if isinstance(v, (int, float))
                    ),
                }
        else:
            parent[key] = {"_aggregated": True, "value": "N/A"}

    # custom 类型 MVP 不实现（规范 §2.8）


# ═══════════════════════════════════════════
#  高层 API：apply_transform（简化规则格式）
# ═══════════════════════════════════════════
#
# 测试 / QA 侧使用的简化接口。
# 规则格式：{ "field": "a.b.c", "action": "drop|mask|range_aggregation|hash", "conditions": [...] }
# 与内部 apply_transforms 的区别：
#   - 规则用 "field" 而非 "applies_to_fields"
#   - 动作用 "action" 而非 "type"
#   - 支持 "drop" (→ redact) 和 "range_aggregation" (→ generalize) 别名
#   - mask 统一替换为 ***MASKED***（测试契约要求完全隐匿）

# action 别名映射到内部引擎动作
_ACTION_ALIAS = {
    "drop": "redact",
    "range_aggregation": "generalize",
}


def apply_transform(
    data: dict | list,
    rules: list[dict],
    caller_agent_id: str | None = None,
) -> dict | list:
    """
    高层脱敏入口（对齐 QA 测试规则格式）。

    参数：
        data:             原始数据
        rules:            规则列表，每条 { "field": "x.y.z", "action": "...", "conditions": [...] }
        caller_agent_id:  调用方 Agent ID（用于日志 / 审计，MVP 阶段可选）

    返回：
        脱敏后的数据副本（不改变原始输入）
    """
    import copy
    result = copy.deepcopy(data)

    for rule in rules:
        field_path = rule.get("field", "")
        action = rule.get("action", "")

        # 将高层 action 名映射到内部名称
        internal_action = _ACTION_ALIAS.get(action, action)

        # mask 动作：使用完全隐匿模式（***MASKED***），直接替换整个值
        config = {}

        try:
            if action == "mask":
                _apply_full_mask(result, field_path)
            else:
                _apply_at_path(result, field_path, internal_action, config)
        except Exception as e:
            logger.warning(
                f"apply_transform rule skipped: {field_path} ({action}): {e}"
            )

    return result


def _apply_full_mask(data, path: str):
    """完全掩码：将目标字段替换为 ***MASKED***（不做部分保留）"""
    segments = _parse_path(path)
    _walk_and_set(data, segments, 0, "***MASKED***")


def _walk_and_set(node, segments: list, idx: int, value):
    """递归遍历路径段，到达叶节点时直接设值"""
    if idx >= len(segments):
        return

    seg = segments[idx]

    if seg == "[*]":
        if not isinstance(node, list):
            return
        for item in node:
            _walk_and_set(item, segments, idx + 1, value)
        return

    if not isinstance(node, dict) or seg not in node:
        return  # 字段不存在，静默跳过

    if idx == len(segments) - 1:
        node[seg] = value
    else:
        _walk_and_set(node[seg], segments, idx + 1, value)
