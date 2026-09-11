import ast
import json

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backend.plugin.rider_salary.engine.fields import (
    ALL_FIELD_NAMES,
    TYPE_BOOL,
    TYPE_ENUM,
    TYPE_NUMBER,
    TYPE_TIME,
    FieldSpec,
    field_available,
    get_field,
)
from backend.plugin.rider_salary.engine.functions import WHITELIST_FUNCTION_NAMES, to_minutes
from backend.plugin.rider_salary.engine.ladder import MODE_FULL, MODE_PROGRESSIVE, PRICING_FIXED, PRICING_UNIT
from backend.plugin.rider_salary.engine.operators import (
    COMPARE_PYTHON,
    OP_EQ,
    OP_IN,
    OP_IN_RANGE,
    OP_IN_TIME,
    OP_NOT_IN,
    OP_NOT_IN_RANGE,
    OP_NOT_IN_TIME,
    operator_allowed,
)

FORMULA_FIXED = '固定金额'
FORMULA_FIELD_RATE = '字段乘单价'
FORMULA_LADDER = '阶梯'
FORMULA_EXPR = '表达式'

MAX_CONDITION_DEPTH = 2

FORMULA_TEMPLATES: list[dict[str, Any]] = [
    {
        'type': FORMULA_FIXED,
        'name': '固定金额',
        'description': '每次命中加固定金额，符号由科目方向决定',
        'skeleton': {'类型': FORMULA_FIXED, '金额': 2},
    },
    {
        'type': FORMULA_FIELD_RATE,
        'name': '字段乘单价',
        'description': '金额 = max(0, (字段 − 起算值)) × 单价',
        'skeleton': {'类型': FORMULA_FIELD_RATE, '字段': '配送距离', '单价': 0.8, '起算值': 5},
    },
    {
        'type': FORMULA_LADDER,
        'name': '阶梯',
        'description': '全量落档或分段累进；每档含下限不含上限，最后一档上限可空表示无穷',
        'skeleton': {
            '类型': FORMULA_LADDER,
            '字段': '周期单量',
            '模式': MODE_FULL,
            '计价': PRICING_UNIT,
            '档位': [
                {'下限': 0, '上限': 300, '值': 5},
                {'下限': 300, '上限': 600, '值': 5.5},
                {'下限': 600, '上限': None, '值': 6},
            ],
        },
    },
    {
        'type': FORMULA_EXPR,
        'name': '表达式',
        'description': '由拼装器生成的中文表达式，仅允许白名单字段与函数',
        'skeleton': {'类型': FORMULA_EXPR, '表达式': '最大值(0, 3000 - 本期已计金额)'},
    },
    {
        'type': '底薪分摊',
        'name': '底薪分摊',
        'description': '快捷模板：底薪金额 × 方案生效天数 / 周期天数（前端替换底薪金额常量）',
        'skeleton': {'类型': FORMULA_EXPR, '表达式': '底薪金额 × 方案生效天数 / 周期天数'},
        'compiled_example': '2000 * 方案生效天数 / 周期天数',
    },
]


@dataclass
class CompileResult:
    """条件/公式校验结果"""

    ok: bool
    condition_expr: str = 'True'
    formula_expr: str = '0'
    errors: list[str] = field(default_factory=list)


class CompileError(ValueError):
    """公式编译错误"""


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return 'True' if value else 'False'
    if value is None:
        return 'None'
    if isinstance(value, Decimal):
        as_int = value.to_integral_value()
        if value == as_int:
            return str(int(as_int))
        return format(value, 'f')
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return f'[{", ".join(_literal(item) for item in value)}]'
    return json.dumps(value, ensure_ascii=False)


def _is_group(node: Any) -> bool:
    return isinstance(node, dict) and '逻辑' in node


def _is_empty_condition(node: Any) -> bool:
    if node is None:
        return True
    if node == {}:
        return True
    return bool(isinstance(node, dict) and not node.get('字段') and not node.get('条件') and not node.get('逻辑'))


def _check_field(name: str, stage: str | None, errors: list[str]) -> FieldSpec | None:
    spec = get_field(name)
    if spec is None:
        errors.append(f'字段「{name}」未注册')
        return None
    if stage is not None and not field_available(name, stage):
        errors.append(f'字段「{name}」在该阶段不可用')
        return None
    return spec


def _compile_leaf(node: dict[str, Any], stage: str | None, errors: list[str]) -> str:  # ruff: ignore[complex-structure]
    field_name = node.get('字段')
    operator = node.get('运算符')
    value = node.get('值')
    if not field_name:
        errors.append('条件缺少字段')
        return 'False'
    if not operator:
        errors.append('条件缺少运算符')
        return 'False'
    spec = _check_field(str(field_name), stage, errors)
    if spec is None:
        return 'False'
    if not operator_allowed(spec, str(operator)):
        errors.append(f'运算符「{operator}」不能用于字段「{field_name}」')
        return 'False'

    if operator in {OP_IN_TIME, OP_NOT_IN_TIME}:
        if not isinstance(value, list) or len(value) != 2:
            errors.append(f'字段「{field_name}」的时段需要起止两个时刻')
            return 'False'
        start, end = value[0], value[1]
        call = f'在时段内({field_name}, {_literal(str(start))}, {_literal(str(end))})'
        return f'not {call}' if operator == OP_NOT_IN_TIME else call

    if operator in {OP_IN_RANGE, OP_NOT_IN_RANGE}:
        if not isinstance(value, list) or len(value) != 2:
            errors.append(f'字段「{field_name}」的区间需要上下限')
            return 'False'
        low, high = value[0], value[1]
        if spec.type == TYPE_TIME:
            low_m = to_minutes(low)
            high_m = to_minutes(high)
            if low_m is None or high_m is None:
                errors.append(f'字段「{field_name}」区间时刻格式无效')
                return 'False'
            call = f'在区间内({field_name}, {low_m:g}, {high_m:g})'
        else:
            call = f'在区间内({field_name}, {_literal(low)}, {_literal(high)})'
        return f'not {call}' if operator == OP_NOT_IN_RANGE else call

    if operator in {OP_IN, OP_NOT_IN}:
        values = value if isinstance(value, list) else [value]
        if not values:
            errors.append(f'运算符「{operator}」至少需要一个枚举值')
            return 'False'
        joined = _literal(values)
        keyword = 'in' if operator == OP_IN else 'not in'
        return f'{field_name} {keyword} {joined}'

    python_op = COMPARE_PYTHON.get(str(operator))
    if python_op is None:
        errors.append(f'不支持的运算符「{operator}」')
        return 'False'

    if spec.type == TYPE_TIME:
        minutes = to_minutes(value)
        if minutes is None:
            errors.append(f'字段「{field_name}」的时刻值无效')
            return 'False'
        return f'{field_name} {python_op} {minutes:g}'

    if spec.type == TYPE_BOOL and operator != OP_EQ:
        errors.append('布尔字段仅支持运算符「=」')
        return 'False'

    if spec.type == TYPE_ENUM and not isinstance(value, (str, int)):
        errors.append(f'字段「{field_name}」的比较值无效')
        return 'False'

    return f'{field_name} {python_op} {_literal(value)}'


def _compile_node(node: Any, stage: str | None, errors: list[str], *, depth: int) -> str:
    if _is_empty_condition(node):
        return 'True'
    if not isinstance(node, dict):
        errors.append('条件 JSON 格式无效')
        return 'False'
    if _is_group(node):
        if depth > MAX_CONDITION_DEPTH:
            errors.append('条件最多嵌套 2 层')
            return 'False'
        logic = str(node.get('逻辑') or '且')
        children = node.get('条件') or []
        if not isinstance(children, list) or not children:
            return 'True'
        compiled = [
            _compile_node(child, stage, errors, depth=depth + 1 if _is_group(child) else depth) for child in children
        ]
        if logic == '非':
            return f'not ({compiled[0]})'
        joiner = ' and ' if logic == '且' else ' or ' if logic == '或' else None
        if joiner is None:
            errors.append(f'不支持的逻辑「{logic}」')
            return 'False'
        if len(compiled) == 1:
            return compiled[0]
        return joiner.join(f'({part})' for part in compiled)
    return _compile_leaf(node, stage, errors)


def compile_condition(condition_json: dict | list | None, stage: str | None = None) -> str:
    """
    将条件 JSON 编译为中文变量 Python 表达式

    :param condition_json: 结构化条件
    :param stage: 计算阶段，用于字段可用性校验；为 None 时不校验阶段
    :return: 表达式字符串，空条件为 True
    """
    errors: list[str] = []
    expr = _compile_node(condition_json, stage, errors, depth=1)
    if errors:
        raise CompileError(errors[0])
    return expr


def _num_literal(value: Any) -> str:
    return _literal(value)


def _compile_ladder(formula: dict[str, Any], stage: str | None, errors: list[str]) -> str:  # ruff: ignore[complex-structure]
    field_name = formula.get('字段')
    mode = formula.get('模式')
    pricing = formula.get('计价')
    tiers = formula.get('档位') or []
    if not field_name:
        errors.append('阶梯公式缺少字段')
        return '0'
    spec = _check_field(str(field_name), stage, errors)
    if spec is not None and spec.type != TYPE_NUMBER:
        errors.append(f'阶梯字段「{field_name}」必须是数值类型')
    if mode not in {MODE_FULL, MODE_PROGRESSIVE}:
        errors.append('阶梯模式必须是「全量落档」或「分段累进」')
    if pricing not in {PRICING_UNIT, PRICING_FIXED}:
        errors.append('阶梯计价必须是「按单价」或「固定金额」')
    if mode == MODE_PROGRESSIVE and pricing == PRICING_FIXED:
        errors.append('分段累进模式仅支持按单价计价')
    if not isinstance(tiers, list) or not tiers:
        errors.append('阶梯至少需要 1 档')
        return '0'
    parsed: list[tuple[float, float | None, float]] = []
    for index, raw in enumerate(tiers):
        if not isinstance(raw, dict):
            errors.append(f'第 {index + 1} 档格式无效')
            continue
        try:
            low = float(raw['下限'])
            raw_high = raw.get('上限')
            high = None if raw_high is None else float(raw_high)
            rate = float(raw['值'])
        except (KeyError, TypeError, ValueError):
            errors.append(f'第 {index + 1} 档上下限或值无效')
            continue
        parsed.append((low, high, rate))
    if not parsed:
        return '0'
    if parsed[0][0] != 0:
        errors.append('阶梯第一档下限必须为 0')
    for index, (low, high, _rate) in enumerate(parsed):
        if high is None and index != len(parsed) - 1:
            errors.append('仅最后一档上限可为空')
        if high is not None and high < low:
            errors.append(f'第 {index + 1} 档上限不能小于下限')
        if index > 0:
            prev_high = parsed[index - 1][1]
            if prev_high is None or prev_high != low:
                errors.append('阶梯档位必须连续、不能重叠')
            if low < parsed[index - 1][0]:
                errors.append('阶梯档位必须按下限升序')
    rows = []
    for low, high, rate in parsed:
        high_lit = 'None' if high is None else _num_literal(high)
        rows.append(f'[{_num_literal(low)}, {high_lit}, {_num_literal(rate)}]')
    return f'阶梯({field_name}, {_literal(mode)}, {_literal(pricing)}, [{", ".join(rows)}])'


def _walk_expr_errors(expr: str, stage: str | None, errors: list[str]) -> None:  # ruff: ignore[complex-structure]
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError:
        errors.append('表达式括号不匹配或语法无效')
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            errors.append('表达式不允许属性访问')
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            right = node.right
            const = getattr(right, 'value', None) if isinstance(right, ast.Constant) else None
            if const == 0:
                errors.append('除以常数 0')
        elif isinstance(node, ast.Call):
            func = node.func
            if not isinstance(func, ast.Name) or func.id not in WHITELIST_FUNCTION_NAMES:
                name = getattr(func, 'id', '?')
                errors.append(f'表达式包含未注册函数「{name}」')
        elif isinstance(node, ast.Name):
            if node.id in WHITELIST_FUNCTION_NAMES:
                continue
            if node.id in {'True', 'False', 'None'}:
                continue
            if node.id not in ALL_FIELD_NAMES:
                errors.append(f'表达式包含未注册字段「{node.id}」')
            elif stage is not None and not field_available(node.id, stage):
                errors.append(f'字段「{node.id}」在该阶段不可用')


def compile_formula(formula_json: dict | None, stage: str | None = None) -> str:
    """
    将公式 JSON 编译为求值表达式

    :param formula_json: 模板式公式
    :param stage: 计算阶段
    :return: 表达式字符串
    """
    errors: list[str] = []
    expr = _compile_formula(formula_json, stage, errors)
    if errors:
        raise CompileError(errors[0])
    return expr


def _compile_formula(formula_json: dict | None, stage: str | None, errors: list[str]) -> str:  # ruff: ignore[complex-structure]
    if not formula_json:
        errors.append('请填写计算公式')
        return '0'
    kind = formula_json.get('类型')
    if kind == FORMULA_FIXED:
        amount = formula_json.get('金额')
        if amount is None or (isinstance(amount, str) and not amount):
            errors.append('请填写固定金额')
            return '0'
        return _num_literal(amount)
    if kind == FORMULA_FIELD_RATE:
        field_name = formula_json.get('字段')
        rate = formula_json.get('单价')
        start = formula_json.get('起算值', 0)
        if not field_name:
            errors.append('字段乘单价缺少字段')
            return '0'
        spec = _check_field(str(field_name), stage, errors)
        if spec is not None and spec.type != TYPE_NUMBER:
            errors.append(f'字段「{field_name}」不是数值类型，不能用于字段乘单价')
        if rate is None or (isinstance(rate, str) and not rate):
            errors.append('请填写单价')
            return '0'
        return f'最大值(0, ({field_name} - {_num_literal(start)})) * {_num_literal(rate)}'
    if kind == FORMULA_LADDER:
        return _compile_ladder(formula_json, stage, errors)
    if kind == FORMULA_EXPR:
        expr = str(formula_json.get('表达式') or '').strip()
        if not expr:
            errors.append('请填写表达式')
            return '0'
        expr = expr.replace('×', '*').replace('÷', '/')
        _walk_expr_errors(expr, stage, errors)
        return expr
    errors.append(f'不支持的公式类型「{kind}」')
    return '0'


def validate_item(
    stage: str,
    condition_json: dict | None,
    formula_json: dict | None,
) -> CompileResult:
    """校验条件与公式，返回编译结果与中文错误"""
    errors: list[str] = []
    condition_expr = _compile_node(condition_json, stage, errors, depth=1)
    formula_expr = _compile_formula(formula_json, stage, errors)
    unique: list[str] = []
    for item in errors:
        if item not in unique:
            unique.append(item)
    return CompileResult(
        ok=not unique,
        condition_expr=condition_expr,
        formula_expr=formula_expr,
        errors=unique,
    )
