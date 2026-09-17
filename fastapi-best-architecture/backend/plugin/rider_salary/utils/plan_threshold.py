"""门槛换价周期项条件须互斥（保存与启用硬拦）。"""

from __future__ import annotations

import json

from decimal import Decimal
from itertools import combinations
from typing import Any

from backend.common.exception import errors
from backend.plugin.rider_salary.engine.compiler import CompileError, compile_condition
from backend.plugin.rider_salary.engine.evaluator import EvalError, evaluate_condition
from backend.plugin.rider_salary.enums import CalcStage

THRESHOLD_XOR_MSG = '门槛换价类周期项条件须互斥，否则会双计，请修改条件后再保存或启用'
THRESHOLD_FIELDS = frozenset({'周期有效单量', '周期单量'})
FIELD_RATE_TYPES = frozenset({'字段乘单价', '字段×单价'})
_SAMPLE_SEEDS = (0, 1, 399, 400, 401, 1199, 1200, 1_000_000)


def _stage_value(raw: Any) -> str:
    if raw is None:
        return ''
    if hasattr(raw, 'value'):
        return str(raw.value)
    return str(raw)


def _item_as_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, 'model_dump'):
        return item.model_dump()
    return {
        'name': getattr(item, 'name', '') or '',
        'stage': getattr(item, 'stage', None),
        'sort_order': getattr(item, 'sort_order', 0),
        'enabled': getattr(item, 'enabled', True),
        'formula_json': getattr(item, 'formula_json', None),
        'condition_json': getattr(item, 'condition_json', None),
    }


def _formula_field(formula: Any) -> str:
    if not isinstance(formula, dict):
        return ''
    return str(formula.get('字段') or '')


def is_threshold_price_item(item: Any) -> bool:
    """周期阶段「字段乘单价」且字段为周期有效单量/周期单量，或名称含门槛。"""
    data = _item_as_dict(item)
    if not bool(data.get('enabled', True)):
        return False
    if _stage_value(data.get('stage')) != CalcStage.period.value:
        return False
    formula = data.get('formula_json')
    kind = formula.get('类型') if isinstance(formula, dict) else None
    field = _formula_field(formula)
    if kind in FIELD_RATE_TYPES and field in THRESHOLD_FIELDS:
        return True
    name = str(data.get('name') or '')
    return '门槛' in name and field in THRESHOLD_FIELDS


def _walk_numbers(node: Any) -> list[float]:
    found: list[float] = []
    if isinstance(node, dict):
        for value in node.values():
            found.extend(_walk_numbers(value))
        return found
    if isinstance(node, (list, tuple)):
        for value in node:
            found.extend(_walk_numbers(value))
        return found
    if isinstance(node, bool):
        return found
    if isinstance(node, Decimal):
        found.append(float(node))
        return found
    if isinstance(node, (int, float)):
        found.append(float(node))
        return found
    if isinstance(node, str):
        try:
            found.append(float(node))
        except ValueError:
            pass
    return found


def _sample_values(*conditions: Any) -> list[float]:
    values: set[float] = {float(item) for item in _SAMPLE_SEEDS}
    for condition in conditions:
        for number in _walk_numbers(condition):
            values.add(number)
            values.add(number - 1)
            values.add(number + 1)
    return sorted(values)


def _condition_true(condition: Any, *, field: str, value: float) -> bool:
    try:
        expr = compile_condition(condition, CalcStage.period.value)
    except CompileError:
        return True
    names = dict.fromkeys(THRESHOLD_FIELDS, 0.0)
    names[field] = value
    try:
        return bool(evaluate_condition(expr, names))
    except EvalError:
        return True


def conditions_can_both_be_true(left: Any, right: Any, *, field: str) -> bool:
    """同字段两条条件是否存在可同时为真的样本点。"""
    for value in _sample_values(left, right):
        if _condition_true(left, field=field, value=value) and _condition_true(right, field=field, value=value):
            return True
    return False


def assert_threshold_price_period_items_xor(items: list[Any] | None) -> None:
    """
    同字段 ≥2 条门槛换价周期项条件必须互斥，否则保存/启用失败。

    取消确认不得再写出：本函数在写库前抛错，调用方不得吞掉。
    """
    enabled = [item for item in (items or []) if bool(_item_as_dict(item).get('enabled', True))]
    flagged = [item for item in enabled if is_threshold_price_item(item)]
    by_field: dict[str, list[Any]] = {}
    for item in flagged:
        field = _formula_field(_item_as_dict(item).get('formula_json')) or '周期有效单量'
        by_field.setdefault(field, []).append(item)
    for field, group in by_field.items():
        if len(group) < 2:
            continue
        for left, right in combinations(group, 2):
            left_cond = _item_as_dict(left).get('condition_json')
            right_cond = _item_as_dict(right).get('condition_json')
            if conditions_can_both_be_true(left_cond, right_cond, field=field):
                raise errors.RequestError(msg=THRESHOLD_XOR_MSG)


def dump_for_debug(items: list[Any]) -> str:
    """单测辅助：规范化 JSON。"""
    return json.dumps([_item_as_dict(item) for item in items], ensure_ascii=False)
