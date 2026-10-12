from datetime import date, datetime
from decimal import Decimal
from typing import Any

from simpleeval import EvalWithCompoundTypes, FeatureNotAvailable, InvalidExpression, NameNotDefined

from backend.plugin.rider_salary.engine.fields import (
    BOOL_FIELDS,
    COUNT_FIELDS,
    DECIMAL_FIELDS,
    NUMBER_FIELDS,
    TIME_FIELDS,
    get_field,
)
from backend.plugin.rider_salary.engine.functions import ENGINE_FUNCTIONS, to_minutes
from backend.plugin.rider_salary.engine.numbers import decimal_operators, to_count, to_decimal
from backend.plugin.rider_salary.utils.money import q2


class EvalError(ValueError):
    """求值失败"""


def _as_iso_date(value: Any) -> str | None:
    """日期统一成 ISO 字符串，便于按字典序比较。"""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return text


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value)


def _normalize_names(names: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {'True': True, 'False': False, 'None': None}
    for key, value in names.items():
        spec = get_field(key)
        if spec is not None and spec.type == 'time':
            normalized[key] = to_minutes(value)
            continue
        if spec is not None and spec.type == 'date':
            normalized[key] = _as_iso_date(value)
            continue
        if key in COUNT_FIELDS:
            normalized[key] = 0 if _blank(value) else to_count(value)
            continue
        if key in DECIMAL_FIELDS or key in NUMBER_FIELDS or (spec is not None and spec.type == 'number'):
            normalized[key] = Decimal(0) if _blank(value) else to_decimal(value)
            continue
        if key in BOOL_FIELDS:
            normalized[key] = bool(value)
            continue
        if key in TIME_FIELDS:
            normalized[key] = to_minutes(value)
            continue
        normalized[key] = value
    return normalized


def evaluate(expr: str, names: dict[str, Any] | None = None) -> Any:
    """
    安全求值表达式

    金额、距离、单价用 Decimal，计数用 int；禁用属性访问；函数仅白名单中文函数。
    运算符限于条件比较与公式四则运算，幂与取模会失败。
    """
    if not expr or not str(expr).strip():
        return True
    evaluator = EvalWithCompoundTypes(
        operators=decimal_operators(),
        functions=dict(ENGINE_FUNCTIONS),
        names=_normalize_names(names or {}),
        allowed_attrs={},
    )
    try:
        return evaluator.eval(str(expr))
    except ZeroDivisionError as exc:
        raise EvalError('除零') from exc
    except (NameNotDefined, FeatureNotAvailable, InvalidExpression, SyntaxError, TypeError, ValueError) as exc:
        raise EvalError(str(exc)) from exc


def evaluate_amount(expr: str, names: dict[str, Any] | None = None) -> Decimal:
    """求值并将结果四舍五入到分。空公式或求值失败时抛出 EvalError。"""
    if not expr or not str(expr).strip():
        raise EvalError('公式不能为空')
    result = evaluate(expr, names)
    if result is None or result is False:
        return Decimal('0.00')
    if result is True:
        return Decimal('1.00')
    return q2(result)


def evaluate_condition(expr: str, names: dict[str, Any] | None = None) -> bool:
    """求值条件。求值失败时抛出 EvalError；空条件仍视为成立。"""
    result = evaluate(expr, names)
    return bool(result)
