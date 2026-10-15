import ast

from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Any

from simpleeval import (
    EvalWithCompoundTypes,
    FeatureNotAvailable,
    FunctionNotDefined,
    InvalidExpression,
    NameNotDefined,
)

from backend.plugin.rider_salary.engine.fields import BOOL_FIELDS, NUMBER_FIELDS, TIME_FIELDS, get_field
from backend.plugin.rider_salary.engine.functions import ENGINE_FUNCTIONS, to_minutes
from backend.plugin.rider_salary.engine.ladder import to_decimal_or_zero
from backend.plugin.rider_salary.utils.money import q2

# 求值期间固定精度与舍入，避免受进程内其它 Decimal 上下文影响。
_DECIMAL_CTX = Context(prec=28, rounding=ROUND_HALF_UP)

_EVAL_ERRORS = (
    NameNotDefined,
    FunctionNotDefined,
    ZeroDivisionError,
    SyntaxError,
    FeatureNotAvailable,
    InvalidExpression,
    TypeError,
    ValueError,
    ArithmeticError,
)


class EvalError(ValueError):
    """求值失败"""


class _DecimalEval(EvalWithCompoundTypes):
    """数字字面量按 Decimal 求值。

    字段已经是 Decimal 时，若字面量仍是 float（如 0.7），简单乘法会抛 TypeError。
    """

    @staticmethod
    def _eval_constant(node: ast.Constant) -> Any:
        value = node.value
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, float):
            return Decimal(str(value))
        return EvalWithCompoundTypes._eval_constant(node)

    @staticmethod
    def _eval_num(node: ast.AST) -> Decimal:
        value = getattr(node, 'n', 0)
        if isinstance(value, float):
            return Decimal(str(value))
        return Decimal(value)


def _normalize_names(names: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {'True': True, 'False': False, 'None': None}
    for key, value in names.items():
        spec = get_field(key)
        if spec is not None and spec.type == 'time':
            normalized[key] = to_minutes(value)
            continue
        if key in NUMBER_FIELDS or (spec is not None and spec.type == 'number'):
            try:
                normalized[key] = to_decimal_or_zero(value)
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise EvalError(f'字段「{key}」数值无效') from exc
            continue
        if key in BOOL_FIELDS:
            normalized[key] = bool(value)
            continue
        if key in TIME_FIELDS:
            normalized[key] = to_minutes(value)
            continue
        normalized[key] = value
    return normalized


def _as_eval_error(exc: Exception) -> EvalError:
    if isinstance(exc, NameNotDefined):
        return EvalError(f'字段未定义：{exc.name}')
    if isinstance(exc, FunctionNotDefined):
        return EvalError(f'函数未定义：{exc.func_name}')
    if isinstance(exc, ZeroDivisionError):
        return EvalError('除零')
    if isinstance(exc, SyntaxError):
        return EvalError('表达式语法无效')
    if isinstance(exc, FeatureNotAvailable):
        return EvalError('表达式包含不允许的操作')
    if isinstance(exc, InvalidExpression):
        return EvalError('表达式无效')
    if isinstance(exc, InvalidOperation):
        return EvalError('数值无效')
    return EvalError('表达式求值失败')


def _finalize(result: Any) -> Any:
    """求值结果里的数值统一成 Decimal，避免把 float 交回调用方。"""
    if isinstance(result, bool) or result is None or isinstance(result, str):
        return result
    if isinstance(result, Decimal):
        return result
    if isinstance(result, float):
        return Decimal(str(result))
    if isinstance(result, int):
        return Decimal(result)
    return result


def _coerce_amount(result: Any) -> Decimal:
    if result is None or result is False:
        return Decimal('0.00')
    if result is True:
        return Decimal('1.00')
    try:
        return q2(result)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise EvalError('数值无效') from exc


def _is_blank(expr: str | None) -> bool:
    return expr is None or not str(expr).strip()


def evaluate(expr: str | None, names: dict[str, Any] | None = None) -> Any:
    """
    安全求值表达式

    数值与数字字面量统一 Decimal；禁用属性访问；函数仅白名单中文函数。
    空表达式视为 True。失败抛出带中文原因的 EvalError。
    """
    if _is_blank(expr):
        return True
    try:
        evaluator = _DecimalEval(
            functions=dict(ENGINE_FUNCTIONS),
            names=_normalize_names(names or {}),
            allowed_attrs={},
        )
        with localcontext(_DECIMAL_CTX):
            result = evaluator.eval(str(expr))
    except EvalError:
        raise
    except _EVAL_ERRORS as exc:
        raise _as_eval_error(exc) from exc
    return _finalize(result)


def evaluate_amount(expr: str | None, names: dict[str, Any] | None = None) -> Decimal:
    """求值并将结果四舍五入到分；失败视为 0"""
    try:
        result = evaluate(expr, names)
    except EvalError:
        return Decimal('0.00')
    return _coerce_amount(result)


def evaluate_condition(expr: str | None, names: dict[str, Any] | None = None) -> bool:
    """求值条件，失败视为假"""
    try:
        result = evaluate(expr, names)
    except EvalError:
        return False
    return bool(result)


def evaluate_amount_strict(expr: str | None, names: dict[str, Any] | None = None) -> Decimal:
    """求值金额。空表达式为 0；失败抛出 EvalError（中文原因）。"""
    if _is_blank(expr):
        return Decimal('0.00')
    return _coerce_amount(evaluate(expr, names))


def evaluate_condition_strict(expr: str | None, names: dict[str, Any] | None = None) -> bool:
    """求值条件。空表达式为真；失败抛出 EvalError（中文原因）。"""
    if _is_blank(expr):
        return True
    return bool(evaluate(expr, names))
