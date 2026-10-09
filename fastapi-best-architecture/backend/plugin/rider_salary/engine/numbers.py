"""金额、距离、单价用 Decimal；计数用 int。运算符在这里把两边收成 Decimal 再算。"""

import ast
import math
import operator

from decimal import Decimal, InvalidOperation
from typing import Any

from simpleeval import DEFAULT_OPERATORS


def to_decimal(value: Any) -> Decimal:
    """把金额、距离、单价收成 Decimal。float 先走十进制字符串，避免二进制误差。"""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    if isinstance(value, bool):
        raise TypeError('数值无效')
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('数值无效')
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return Decimal(0)
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError('数值无效') from exc
    if not number.is_finite():
        raise ValueError('数值无效')
    return number


def parse_decimal(value: Any) -> Decimal:
    """解析档位和单价。空值、布尔不能当成 0。"""
    if isinstance(value, bool) or value is None:
        raise ValueError('数值无效')
    if isinstance(value, str) and not value.strip():
        raise ValueError('数值无效')
    return to_decimal(value)


def to_count(value: Any) -> int:
    """计数收成整数。"""
    if value is None:
        return 0
    if isinstance(value, str) and not value.strip():
        return 0
    if isinstance(value, bool):
        return int(value)
    return int(to_decimal(value).to_integral_value())


def is_real(value: Any) -> bool:
    """int、float、Decimal 参与数值比较；布尔和字符串除外。"""
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _add(left: Any, right: Any) -> Decimal:
    return to_decimal(left) + to_decimal(right)


def _sub(left: Any, right: Any) -> Decimal:
    return to_decimal(left) - to_decimal(right)


def _mul(left: Any, right: Any) -> Decimal:
    return to_decimal(left) * to_decimal(right)


def _div(left: Any, right: Any) -> Decimal:
    return to_decimal(left) / to_decimal(right)


def _pos(value: Any) -> Decimal:
    return +to_decimal(value)


def _neg(value: Any) -> Decimal:
    return -to_decimal(value)


def _cmp(op: Any) -> Any:
    def inner(left: Any, right: Any) -> bool:
        if is_real(left) and is_real(right):
            return bool(op(to_decimal(left), to_decimal(right)))
        return bool(op(left, right))

    return inner


def decimal_operators() -> dict[type[ast.AST], Any]:
    """四则运算一律 Decimal；Decimal 与 int、float 字面量混算。比较只在两边都是数时转换。"""
    ops: dict[type[ast.AST], Any] = {
        node: DEFAULT_OPERATORS[node]
        for node in (
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.Div,
            ast.UAdd,
            ast.USub,
            ast.Not,
            ast.Eq,
            ast.NotEq,
            ast.Gt,
            ast.Lt,
            ast.GtE,
            ast.LtE,
            ast.In,
            ast.NotIn,
        )
    }
    ops[ast.Add] = _add
    ops[ast.Sub] = _sub
    ops[ast.Mult] = _mul
    ops[ast.Div] = _div
    ops[ast.UAdd] = _pos
    ops[ast.USub] = _neg
    ops[ast.Eq] = _cmp(operator.eq)
    ops[ast.NotEq] = _cmp(operator.ne)
    ops[ast.Gt] = _cmp(operator.gt)
    ops[ast.Lt] = _cmp(operator.lt)
    ops[ast.GtE] = _cmp(operator.ge)
    ops[ast.LtE] = _cmp(operator.le)
    return ops
