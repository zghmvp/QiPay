from decimal import Decimal
from typing import Any

from simpleeval import EvalWithCompoundTypes, FeatureNotAvailable, InvalidExpression, NameNotDefined

from backend.plugin.rider_salary.engine.fields import BOOL_FIELDS, NUMBER_FIELDS, TIME_FIELDS, get_field
from backend.plugin.rider_salary.engine.functions import ENGINE_FUNCTIONS, to_minutes
from backend.plugin.rider_salary.utils.money import q2


class EvalError(ValueError):
    """求值失败"""


def _normalize_names(names: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {'True': True, 'False': False, 'None': None}
    for key, value in names.items():
        spec = get_field(key)
        if spec is not None and spec.type == 'time':
            normalized[key] = to_minutes(value)
            continue
        if key in NUMBER_FIELDS or (spec is not None and spec.type == 'number'):
            if value is None or (isinstance(value, str) and not value):
                normalized[key] = 0.0
            else:
                normalized[key] = float(value)
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

    数值统一 float；禁用属性访问；函数仅白名单中文函数。
    """
    if not expr or not str(expr).strip():
        return True
    evaluator = EvalWithCompoundTypes(
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
    """求值并将结果四舍五入到分；求值异常向上抛出 EvalError"""
    result = evaluate(expr, names)
    if result is None or result is False:
        return Decimal('0.00')
    if result is True:
        return Decimal('1.00')
    return q2(Decimal(str(result)))


def evaluate_condition(expr: str, names: dict[str, Any] | None = None) -> bool:
    """求值条件；求值异常向上抛出 EvalError"""
    result = evaluate(expr, names)
    return bool(result)
