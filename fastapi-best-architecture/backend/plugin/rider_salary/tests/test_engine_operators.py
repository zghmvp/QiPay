"""运算符矩阵与公式 AST 白名单。"""

from datetime import date
from decimal import Decimal

import pytest

from backend.plugin.rider_salary.engine.compiler import CompileError, compile_condition, compile_formula, validate_item
from backend.plugin.rider_salary.engine.evaluator import EvalError, evaluate, evaluate_condition
from backend.plugin.rider_salary.engine.fields import get_field
from backend.plugin.rider_salary.engine.operators import OPERATORS_BY_TYPE, operator_allowed, operators_for_field
from backend.plugin.rider_salary.enums import CalcStage

STAGE = CalcStage.per_order.value
PERIOD = CalcStage.period.value

# 产品方案 §3.2
_MATRIX = {
    'number': ('=', '≠', '>', '≥', '<', '≤', '在区间内', '不在区间内'),
    'time': ('=', '≠', '在时段内'),
    'enum': ('=', '≠', '属于', '不属于'),
    'bool': ('=', '≠'),
    'date': ('=', '≠', '>', '≥', '<', '≤', '在区间内'),
}
_SAMPLE_FIELD = {
    'number': '配送距离',
    'time': '送达时刻',
    'enum': '订单状态',
    'bool': '是否高温',
    'date': '日期',
}


def test_operator_matrix_matches_product_spec() -> None:
    """各字段类型的运算符与产品方案 §3.2 一致。"""
    assert OPERATORS_BY_TYPE == _MATRIX
    for type_name, field_name in _SAMPLE_FIELD.items():
        assert tuple(operators_for_field(field_name)) == _MATRIX[type_name]
        spec = get_field(field_name)
        assert spec is not None
        for operator in _MATRIX[type_name]:
            assert operator_allowed(spec, operator) is True


@pytest.mark.parametrize(
    ('field_name', 'operator'),
    [
        ('是否高温', '在区间内'),
        ('日期', '不在区间内'),
        ('送达时刻', '>'),
        ('送达时刻', '不在时段内'),
        ('配送距离', '在时段内'),
    ],
)
def test_operator_rejected_when_type_mismatch(field_name: str, operator: str) -> None:
    """类型不匹配的运算符不能编译。"""
    raw = {'字段': field_name, '运算符': operator, '值': 1}
    with pytest.raises(CompileError, match='不能用于字段'):
        compile_condition(raw, STAGE)


def test_bool_not_equal_compiles_and_evaluates() -> None:
    """是否高温 ≠ 是：不是高温时命中，是高温时不命中。"""
    raw = {'字段': '是否高温', '运算符': '≠', '值': True}
    expr = compile_condition(raw, STAGE)
    assert expr == '是否高温 != True'
    assert evaluate_condition(expr, {'是否高温': False}) is True
    assert evaluate_condition(expr, {'是否高温': True}) is False


def test_date_ge_compiles_and_evaluates() -> None:
    """日期 ≥ 某日按 ISO 字符串比较，含当天，早于该日不命中。"""
    raw = {'字段': '日期', '运算符': '≥', '值': '2026-09-01'}
    expr = compile_condition(raw, STAGE)
    assert expr == '日期 >= "2026-09-01"'
    assert evaluate_condition(expr, {'日期': '2026-09-01'}) is True
    assert evaluate_condition(expr, {'日期': date(2026, 9, 15)}) is True
    assert evaluate_condition(expr, {'日期': '2026-08-31'}) is False


def test_date_range_uses_iso_strings() -> None:
    """日期区间两端规范成 ISO 日期后再比较。"""
    raw = {'字段': '日期', '运算符': '在区间内', '值': ['2026-09-01', '2026-09-30']}
    expr = compile_condition(raw, STAGE)
    assert expr == '在区间内(日期, "2026-09-01", "2026-09-30")'
    assert evaluate_condition(expr, {'日期': '2026-09-15'}) is True
    assert evaluate_condition(expr, {'日期': '2026-10-01'}) is False


def test_time_eq_and_ne_compare_minutes() -> None:
    """时刻等于、不等于先转成自 0 点起的分钟数。"""
    eq = compile_condition({'字段': '送达时刻', '运算符': '=', '值': '22:00'}, STAGE)
    ne = compile_condition({'字段': '送达时刻', '运算符': '≠', '值': '22:00'}, STAGE)
    assert eq == '送达时刻 == 1320'
    assert ne == '送达时刻 != 1320'
    assert evaluate_condition(eq, {'送达时刻': '22:00'}) is True
    assert evaluate_condition(eq, {'送达时刻': '21:59'}) is False
    assert evaluate_condition(ne, {'送达时刻': '10:00'}) is True
    assert evaluate_condition(ne, {'送达时刻': '22:00'}) is False


def test_not_group_rejects_multiple_children() -> None:
    """「非」组有多个子项时报错，不再只取第一项。"""
    raw = {
        '逻辑': '非',
        '条件': [
            {'字段': '是否高温', '运算符': '=', '值': True},
            {'字段': '是否周末', '运算符': '=', '值': True},
        ],
    }
    with pytest.raises(CompileError, match='只能有一个子条件'):
        compile_condition(raw, STAGE)


def test_not_group_single_child() -> None:
    """「非」组只有一个子条件时编译为 not。"""
    raw = {'逻辑': '非', '条件': [{'字段': '是否高温', '运算符': '=', '值': True}]}
    expr = compile_condition(raw, STAGE)
    assert expr == 'not (是否高温 == True)'
    assert evaluate_condition(expr, {'是否高温': False}) is True
    assert evaluate_condition(expr, {'是否高温': True}) is False


@pytest.mark.parametrize(
    ('expr', 'stage', 'fragment'),
    [
        ('2 ** 10', STAGE, r'\*\*'),
        ('2 % 3', STAGE, '%'),
        ('2 // 3', STAGE, '//'),
        ('配送距离 > 5', STAGE, '比较运算符'),
        ('配送距离 and 1', STAGE, '逻辑运算符'),
        ('not 配送距离', STAGE, 'not'),
    ],
)
def test_formula_ast_rejects_undocumented_operators(expr: str, stage: str, fragment: str) -> None:
    """公式 AST 白名单拒绝幂、取模和比较。"""
    with pytest.raises(CompileError, match=fragment):
        compile_formula({'类型': '表达式', '表达式': expr}, stage)


def test_power_rejected_by_validate_and_evaluate() -> None:
    """2 ** 10 不能通过校验，直接求值也会失败。"""
    result = validate_item(STAGE, {}, {'类型': '表达式', '表达式': '2 ** 10'})
    assert result.ok is False
    assert any('**' in item for item in result.errors)
    with pytest.raises(EvalError):
        evaluate('2 ** 10')


def test_documented_formula_operators_still_compile() -> None:
    """加减乘除、正负号和白名单函数仍可编译求值。"""
    expr = compile_formula({'类型': '表达式', '表达式': '最大值(0, 3000 - 本期已计金额)'}, PERIOD)
    assert expr == '最大值(0, 3000 - 本期已计金额)'
    assert evaluate(expr, {'本期已计金额': 1000}) == 2000
    negative = compile_formula({'类型': '表达式', '表达式': '-配送距离'}, STAGE)
    assert evaluate(negative, {'配送距离': 3}) == -3
    divided = compile_formula({'类型': '表达式', '表达式': '2000 * 方案生效天数 / 周期天数'}, PERIOD)
    assert evaluate(divided, {'方案生效天数': 15, '周期天数': 30}) == 1000
    rounded = compile_formula({'类型': '表达式', '表达式': '四舍五入(配送距离, 位数=2)'}, STAGE)
    assert evaluate(rounded, {'配送距离': 1.235}) == Decimal('1.24')
    with pytest.raises(CompileError, match='除以常数 0'):
        compile_formula({'类型': '表达式', '表达式': '配送距离 / 0'}, STAGE)
