"""入参长度、金额和结构上限。

待确认的结构上限（当前取值，见 P3-08）：
- 公式 JSON 节点 128
- 表达式语法节点 64，表达式文本 500 字
- 阶梯档位 20
- 奖惩批量 200，日标记 62，方案项 50
- 算薪或沿用原单的骑手 ID 500，站点负责人 20
"""

import ast
import re

from decimal import Decimal
from typing import Any

from pydantic import BeforeValidator

# 与列宽一致
LEN_CODE_32 = 32
LEN_CODE_64 = 64
LEN_NAME_32 = 32
LEN_NAME_64 = 64
LEN_PHONE = 20
LEN_STATUS = 20
LEN_COLOR = 16
LEN_NOTICE_TITLE = 128
LEN_PASSWORD = 64
# 业务短名严于列宽 String(16)
LEN_SHORT_NAME = 6
# 无列宽的长文本
LEN_ADVANCE_REASON = 200
LEN_REMARK = 500
LEN_PLAN_DESC = 2000
LEN_NOTICE_CONTENT = 4000
LEN_CONFIRM = 16

# Numeric(12, 2) / Numeric(8, 2)
MONEY_MAX = Decimal('9999999999.99')
MEASURE_MAX = Decimal('999999.99')
MONEY_DIGITS = 12
MONEY_PLACES = 2
MEASURE_DIGITS = 8

# 待用户确认
MAX_FORMULA_NODES = 128
MAX_EXPR_NODES = 64
MAX_EXPR_CHARS = 500
MAX_JSON_DEPTH = 8
MAX_LADDER_TIERS = 20
MAX_ADJUSTMENT_BATCH = 200
MAX_DAY_FLAGS = 62
MAX_PLAN_ITEMS = 50
MAX_ID_LIST = 500
MAX_SITE_MANAGERS = 20
MAX_SCOPE_ITEMS = 100
MAX_SORT_ORDER = 9999


def zh_str(label: str, max_length: int, *, min_length: int = 0) -> BeforeValidator:
    """超长或过短时给出中文说明。框架不会把 max_length 的原文翻成中文。"""

    def _check(value: object) -> object:
        if value is None or not isinstance(value, str):
            return value
        if min_length and len(value) < min_length:
            raise ValueError(f'{label}至少 {min_length} 个字')
        if len(value) > max_length:
            raise ValueError(f'{label}不能超过 {max_length} 个字')
        return value

    return BeforeValidator(_check)


def zh_list(label: str, max_length: int) -> BeforeValidator:
    """批量条数超限时给出中文说明。"""

    def _check(value: object) -> object:
        if isinstance(value, list) and len(value) > max_length:
            raise ValueError(f'{label}不能超过 {max_length} 条')
        return value

    return BeforeValidator(_check)


def zh_money(label: str, *, signed: bool = False, upper: Decimal = MONEY_MAX) -> BeforeValidator:
    """金额范围和小数位的中文说明。"""

    def _check(value: object) -> object:
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
            return value
        try:
            amount = Decimal(str(value))
        except Exception:
            return value
        lower = -upper if signed else Decimal(0)
        if amount < lower:
            raise ValueError(f'{label}不能为负数' if lower == 0 else f'{label}不能小于 {lower}')
        if amount > upper:
            raise ValueError(f'{label}不能超过 {upper}')
        exponent = amount.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -MONEY_PLACES:
            raise ValueError(f'{label}最多 {MONEY_PLACES} 位小数')
        return value

    return BeforeValidator(_check)


_COLOR_RE = re.compile(r'^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$')
_EXPR_NODE_TYPES = (ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Constant)


def require_hex_color(value: str | None) -> str | None:
    """色带颜色必须是 #RGB、#RRGGBB 或 #RRGGBBAA。"""
    if value is None:
        return None
    if _COLOR_RE.fullmatch(value) is None:
        raise ValueError('颜色须为十六进制，如 #1677FF')
    return value


def _count_nodes(value: Any, depth: int) -> int:
    if depth > MAX_JSON_DEPTH:
        raise ValueError(f'公式结构嵌套不能超过 {MAX_JSON_DEPTH} 层')
    if isinstance(value, dict):
        if not value:
            return 0
        total = 1
        for item in value.values():
            total += _count_nodes(item, depth + 1)
        return total
    if isinstance(value, list):
        if len(value) > MAX_FORMULA_NODES:
            raise ValueError(f'公式节点不能超过 {MAX_FORMULA_NODES} 个')
        total = 1
        for item in value:
            total += _count_nodes(item, depth + 1)
        return total
    if isinstance(value, str) and len(value) > MAX_EXPR_CHARS:
        raise ValueError(f'公式文本不能超过 {MAX_EXPR_CHARS} 个字')
    return 1


def _count_expr_nodes(expr: str) -> int:
    if len(expr) > MAX_EXPR_CHARS:
        raise ValueError(f'表达式不能超过 {MAX_EXPR_CHARS} 个字')
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError:
        raise ValueError('表达式语法无效') from None
    return sum(1 for node in ast.walk(tree) if isinstance(node, _EXPR_NODE_TYPES))


def _reject_node_count(label: str, payload: Any) -> None:
    if payload is not None and _count_nodes(payload, 0) > MAX_FORMULA_NODES:
        raise ValueError(f'{label}节点不能超过 {MAX_FORMULA_NODES} 个')


def _reject_ladder(formula_json: dict[str, Any]) -> None:
    if formula_json.get('类型') != '阶梯':
        return
    tiers = formula_json.get('档位') or []
    invalid_tiers = not isinstance(tiers, list)
    if invalid_tiers:
        raise ValueError('阶梯档位格式无效')
    if len(tiers) > MAX_LADDER_TIERS:
        raise ValueError(f'阶梯档位不能超过 {MAX_LADDER_TIERS} 档')


def _reject_expression(formula_json: dict[str, Any]) -> None:
    if formula_json.get('类型') != '表达式':
        return
    expr = formula_json.get('表达式')
    if not expr:
        return
    invalid_expr = not isinstance(expr, str)
    if invalid_expr:
        raise ValueError('表达式须为文本')
    if _count_expr_nodes(expr) > MAX_EXPR_NODES:
        raise ValueError(f'表达式节点不能超过 {MAX_EXPR_NODES} 个')


def assert_formula_bounds(condition_json: Any, formula_json: Any) -> None:
    """限制条件/公式节点数和阶梯档数。"""
    _reject_node_count('条件', condition_json)
    _reject_node_count('公式', formula_json)
    if not isinstance(formula_json, dict):
        return
    _reject_ladder(formula_json)
    _reject_expression(formula_json)
