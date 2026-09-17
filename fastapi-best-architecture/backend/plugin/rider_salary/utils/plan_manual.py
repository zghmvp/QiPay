"""周期项公式不得把「本期手工奖 / 本期手工惩」当作加项（保存与启用硬拦）。"""

from __future__ import annotations

import ast

from typing import Any

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import CalcStage

MANUAL_PERIOD_FIELDS = frozenset({'本期手工奖', '本期手工惩'})
MANUAL_ADDEND_MSG = '周期项公式不得把「本期手工奖 / 本期手工惩」当作加项：手工明细已入账，再加会双计'
FIELD_RATE_TYPES = frozenset({'字段乘单价', '字段×单价'})
LADDER_TYPE = '阶梯'
FIXED_TYPE = '固定金额'
EXPR_TYPE = '表达式'


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
        'enabled': getattr(item, 'enabled', True),
        'formula_json': getattr(item, 'formula_json', None),
        'formula_expr': getattr(item, 'formula_expr', None),
    }


def _normalize_expr(expr: str) -> str:
    return expr.replace('×', '*').replace('÷', '/').replace('−', '-').replace('—', '-').replace('–', '-')


def _const_sign(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        if node.value > 0:
            return 1
        if node.value < 0:
            return -1
        return 0
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _const_sign(node.operand)
        return None if inner is None else -inner
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        return _const_sign(node.operand)
    return None


def _expr_has_positive_addend(expr: str) -> bool:
    text = _normalize_expr(expr).strip()
    if not text or not any(field in text for field in MANUAL_PERIOD_FIELDS):
        return False
    try:
        tree = ast.parse(text, mode='eval')
    except SyntaxError:
        return True
    return _node_has_positive_addend(tree.body, 1)


def _muldiv_child_signs(node: ast.BinOp, sign: int) -> tuple[int, int]:
    left_c = _const_sign(node.left)
    right_c = _const_sign(node.right)
    if isinstance(node.op, ast.Mult):
        left_sign = sign if right_c is None else sign * right_c
        right_sign = sign if left_c is None else sign * left_c
        return left_sign, right_sign
    left_sign = sign if right_c is None else (0 if right_c == 0 else sign * right_c)
    return left_sign, sign


def _binop_has_positive_addend(node: ast.BinOp, sign: int) -> bool:
    if isinstance(node.op, ast.Add):
        return _node_has_positive_addend(node.left, sign) or _node_has_positive_addend(node.right, sign)
    if isinstance(node.op, ast.Sub):
        return _node_has_positive_addend(node.left, sign) or _node_has_positive_addend(node.right, -sign)
    if isinstance(node.op, (ast.Mult, ast.Div)):
        left_sign, right_sign = _muldiv_child_signs(node, sign)
        return _node_has_positive_addend(node.left, left_sign) or _node_has_positive_addend(node.right, right_sign)
    return _node_has_positive_addend(node.left, sign) or _node_has_positive_addend(node.right, sign)


def _node_has_positive_addend(node: ast.AST, sign: int) -> bool:
    if sign == 0:
        return False
    if isinstance(node, ast.Name):
        return sign > 0 and node.id in MANUAL_PERIOD_FIELDS
    if isinstance(node, ast.UnaryOp):
        next_sign = -sign if isinstance(node.op, ast.USub) else sign
        return _node_has_positive_addend(node.operand, next_sign)
    if isinstance(node, ast.BinOp):
        return _binop_has_positive_addend(node, sign)
    if isinstance(node, ast.Call):
        return any(_node_has_positive_addend(arg, sign) for arg in node.args)
    return any(_node_has_positive_addend(child, sign) for child in ast.iter_child_nodes(node))


def _fixed_wraps_manual(formula: dict[str, Any], field: str) -> bool:
    amount = formula.get('金额')
    if isinstance(amount, str) and amount.strip() in MANUAL_PERIOD_FIELDS:
        return True
    if isinstance(amount, dict) and formula_adds_manual_period_field(amount):
        return True
    return field in MANUAL_PERIOD_FIELDS


def formula_adds_manual_period_field(formula: Any) -> bool:
    """公式是否把本期手工奖/惩当作正贡献加项。条件引用与相减不是加项。"""
    if formula is None:
        return False
    if isinstance(formula, str):
        stripped = formula.strip()
        return stripped in MANUAL_PERIOD_FIELDS or _expr_has_positive_addend(stripped)
    if not isinstance(formula, dict):
        return False
    kind = formula.get('类型')
    field = str(formula.get('字段') or '')
    if kind in FIELD_RATE_TYPES or kind == LADDER_TYPE:
        return field in MANUAL_PERIOD_FIELDS
    if kind == FIXED_TYPE:
        return _fixed_wraps_manual(formula, field)
    if kind == EXPR_TYPE:
        return _expr_has_positive_addend(str(formula.get('表达式') or ''))
    if field in MANUAL_PERIOD_FIELDS:
        return True
    expr = formula.get('表达式')
    if isinstance(expr, str) and _expr_has_positive_addend(expr):
        return True
    return any(formula_adds_manual_period_field(value) for value in formula.values() if isinstance(value, dict))


def is_period_manual_addend_item(item: Any) -> bool:
    """启用中的周期项是否把手工奖惩字段当公式加项。"""
    data = _item_as_dict(item)
    if not bool(data.get('enabled', True)):
        return False
    if _stage_value(data.get('stage')) != CalcStage.period.value:
        return False
    if formula_adds_manual_period_field(data.get('formula_json')):
        return True
    expr = data.get('formula_expr')
    return isinstance(expr, str) and _expr_has_positive_addend(expr)


def assert_period_formula_not_manual_addend(items: list[Any] | None) -> None:
    """
    周期项公式把本期手工奖/惩当加项则保存/启用失败。

    取消确认不得再写出：本函数在写库前抛错，调用方不得吞掉。
    """
    for item in items or []:
        if is_period_manual_addend_item(item):
            raise errors.RequestError(msg=MANUAL_ADDEND_MSG)
