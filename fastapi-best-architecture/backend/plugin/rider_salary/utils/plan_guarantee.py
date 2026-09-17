"""保底 /「本期已计金额」须为周期阶段末位（保存与启用硬拦）。"""

from __future__ import annotations

import json

from typing import Any

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import CalcStage

ACCRUED_FIELD = '本期已计金额'
GUARANTEE_NAME_HINT = '保底'
GUARANTEE_LAST_MSG = '引用「本期已计金额」或保底类方案项须放在周期阶段最后执行，请将该项沉底后再保存或启用'


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
    }


def _contains_accrued_field(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return ACCRUED_FIELD in value
    if isinstance(value, dict):
        return any(_contains_accrued_field(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_accrued_field(item) for item in value)
    try:
        return ACCRUED_FIELD in json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return False


def is_accrued_or_guarantee_item(item: Any) -> bool:
    """公式含「本期已计金额」，或名称启发式保底类。"""
    data = _item_as_dict(item)
    name = str(data.get('name') or '')
    if GUARANTEE_NAME_HINT in name:
        return True
    return _contains_accrued_field(data.get('formula_json'))


def assert_accrued_guarantee_is_last_period_item(items: list[Any] | None) -> None:
    """
    启用中的保底 / 本期已计金额项必须是该版本 period 阶段 sort_order 最大者。

    取消确认不得再写出：本函数在写库前抛错，调用方不得吞掉。
    """
    enabled = [item for item in (items or []) if bool(_item_as_dict(item).get('enabled', True))]
    flagged = [item for item in enabled if is_accrued_or_guarantee_item(item)]
    if not flagged:
        return
    for item in flagged:
        stage = _stage_value(_item_as_dict(item).get('stage'))
        if stage != CalcStage.period.value:
            raise errors.RequestError(msg=GUARANTEE_LAST_MSG)
    period_items = [
        item for item in enabled if _stage_value(_item_as_dict(item).get('stage')) == CalcStage.period.value
    ]
    max_sort = max(int(_item_as_dict(item).get('sort_order') or 0) for item in period_items)
    for item in flagged:
        sort_order = int(_item_as_dict(item).get('sort_order') or 0)
        if sort_order < max_sort:
            raise errors.RequestError(msg=GUARANTEE_LAST_MSG)
