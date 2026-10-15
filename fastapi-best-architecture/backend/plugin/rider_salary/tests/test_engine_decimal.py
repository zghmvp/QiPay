from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.plugin.rider_salary.engine import evaluate_amount_strict, evaluate_condition_strict
from backend.plugin.rider_salary.engine.compiler import CompileError, compile_formula
from backend.plugin.rider_salary.engine.context import (
    build_day_context,
    build_order_context,
    build_period_context,
    build_segment_context,
)
from backend.plugin.rider_salary.engine.evaluator import (
    EvalError,
    evaluate,
    evaluate_amount,
    evaluate_condition,
)
from backend.plugin.rider_salary.engine.ladder import ladder
from backend.plugin.rider_salary.enums import CalcStage
from backend.plugin.rider_salary.utils.money import q2

D = Decimal
PER_ORDER = CalcStage.per_order.value


def test_money_products_round_half_up() -> None:
    """A7：float 会把 0.05×0.7 收成 0.03、1.30×1.15 收成 1.49。"""
    assert evaluate('0.05 * 0.7') == D('0.035')
    assert evaluate_amount('0.05 * 0.7') == D('0.04')
    assert evaluate_amount_strict('0.05 * 0.7') == D('0.04')
    assert evaluate_amount('1.30 * 1.15') == D('1.50')
    assert evaluate_amount_strict('1.30 * 1.15') == D('1.50')
    assert evaluate_amount('2000 * 15 / 31') == D('967.74')
    assert evaluate_amount_strict('2000 * 15 / 31') == D('967.74')
    assert evaluate_amount_strict('2000 * 方案生效天数 / 周期天数', {'方案生效天数': 15, '周期天数': 31}) == D('967.74')
    assert evaluate_amount('1.005') == D('1.01')


def test_float_inputs_from_calc_are_accepted() -> None:
    """calc_service 仍会传入 float(q2(x))，normalize 必须按十进制吃进去。"""
    paid = float(q2(D('1.30')))
    assert evaluate_amount('订单金额 * 1.15', {'订单金额': paid}) == D('1.50')
    assert evaluate_amount('配送距离 * 0.7', {'配送距离': 0.05}) == D('0.04')
    assert evaluate_amount('订单金额', {'订单金额': '1.30'}) == D('1.30')
    assert evaluate_amount('周期天数', {'周期天数': 31}) == D('31.00')
    assert evaluate_amount('周期天数', {'周期天数': None}) == D('0.00')
    assert evaluate_amount('周期天数', {'周期天数': ''}) == D('0.00')


def test_ladder_boundary_hits_lower_inclusive_tier() -> None:
    """B12：0.1+0.2 恰好等于 0.3 档下限，含下不含上，命中 0.3 档。"""
    value = D('0.1') + D('0.2')
    assert value == D('0.3')
    tiers = [[0, 0.3, 1], [0.3, None, 2]]
    assert ladder(value, '全量落档', '固定金额', tiers) == D(2)
    assert ladder(D('0.3') - D('0.01'), '全量落档', '固定金额', tiers) == D(1)
    expr = '阶梯(0.1 + 0.2, "全量落档", "固定金额", [[0, 0.3, 1], [0.3, None, 2]])'
    assert evaluate_amount_strict(expr) == D('2.00')
    # float 中 0.7+0.1 小于 0.8，会落进前一档
    miss_on_float = '阶梯(0.7 + 0.1, "全量落档", "固定金额", [[0, 0.8, 1], [0.8, None, 2]])'
    assert evaluate_amount(miss_on_float) == D('2.00')
    progressive = '阶梯(0.1 + 0.2, "分段累进", "按单价", [[0, 0.3, 10], [0.3, None, 100]])'
    assert evaluate_amount_strict(progressive) == D('3.00')


def test_compiler_tier_continuity_uses_decimal() -> None:
    formula = {
        '类型': '阶梯',
        '字段': '配送距离',
        '模式': '全量落档',
        '计价': '固定金额',
        '档位': [
            {'下限': 0, '上限': '0.30', '值': '1'},
            {'下限': 0.3, '上限': None, '值': 2},
        ],
    }
    expr = compile_formula(formula, PER_ORDER)
    assert evaluate_amount_strict(expr, {'配送距离': D('0.1') + D('0.2')}) == D('2.00')
    broken = {
        '类型': '阶梯',
        '字段': '配送距离',
        '模式': '全量落档',
        '计价': '固定金额',
        '档位': [
            {'下限': 0, '上限': '0.2', '值': 1},
            {'下限': '0.3', '上限': None, '值': 2},
        ],
    }
    with pytest.raises(CompileError, match='连续'):
        compile_formula(broken, PER_ORDER)


def test_functions_accept_and_return_decimal() -> None:
    assert isinstance(evaluate('最大值(0.1, 0.2)'), Decimal)
    assert evaluate('最大值(0.1, 0.2)') == D('0.2')
    assert evaluate('最小值(0.1, 0.2)') == D('0.1')
    assert evaluate('取整(1.9)') == D('1')
    assert evaluate('取整(-1.1)') == D('-2')
    assert evaluate('向上取整(1.1)') == D('2')
    assert evaluate('向上取整(-1.1)') == D('-1')
    assert evaluate('绝对值(-1.25)') == D('1.25')
    assert evaluate('四舍五入(1.005, 2)') == D('1.01')
    assert evaluate('四舍五入(-1.005, 2)') == D('-1.01')
    assert isinstance(evaluate('阶梯(1, "全量落档", "固定金额", [[0, None, 2]])'), Decimal)


def test_strict_empty_and_errors() -> None:
    """B9：严格版暴露失败原因；空表达式条件为真、金额为 0。"""
    assert evaluate_condition_strict('') is True
    assert evaluate_condition_strict('   ') is True
    assert evaluate_condition_strict(None) is True
    assert evaluate_amount_strict('') == D('0.00')
    assert evaluate_amount_strict('   ') == D('0.00')
    assert evaluate_amount_strict(None) == D('0.00')
    assert evaluate_condition_strict('配送距离 > 5', {'配送距离': 1}) is False
    assert evaluate_amount_strict('2') == D('2.00')

    with pytest.raises(EvalError, match='除零'):
        evaluate_amount_strict('1 / 0')
    with pytest.raises(EvalError, match='除零'):
        evaluate_condition_strict('2000 / 周期天数', {'周期天数': 0})
    with pytest.raises(EvalError, match='字段未定义：神秘字段'):
        evaluate_amount_strict('神秘字段 + 1')
    with pytest.raises(EvalError, match='字段未定义：神秘字段'):
        evaluate_condition_strict('神秘字段 > 1')
    with pytest.raises(EvalError, match='数值无效'):
        evaluate_amount_strict('配送距离', {'配送距离': 'abc'})

    assert evaluate_amount('1 / 0') == D('0.00')
    assert evaluate_condition('1 / 0') is False
    assert evaluate_amount('神秘字段') == D('0.00')
    assert evaluate_condition('神秘字段 > 1') is False
    assert evaluate_amount('配送距离', {'配送距离': 'abc'}) == D('0.00')
    # 宽松版空表达式仍走原路径：evaluate 视空表达式为 True，金额因此是 1
    assert evaluate_amount('') == D('1.00')
    assert evaluate_condition('') is True


def test_context_numeric_fields_are_decimal() -> None:
    day = date(2026, 9, 1)
    order = SimpleNamespace(
        distance_km=D('7.20'),
        weight_jin=1.5,
        amount='28.00',
        deliver_time=None,
        status='completed',
        order_no='n',
        id=1,
        biz_date=day,
    )
    ctx = build_order_context(order, build_day_context(1, day, None, 'part_time'))
    assert isinstance(ctx['配送距离'], Decimal)
    assert ctx['配送距离'] == D('7.20')
    assert ctx['商品重量'] == D('1.5')
    assert ctx['订单金额'] == D('28.00')
    assert ctx['送达时刻'] is None

    period = build_period_context(
        period_days=31,
        order_count=10,
        valid_order_count=8,
        attendance_days=6,
        hire_date=date(2026, 1, 1),
        period_end=date(2026, 9, 30),
        manual_bonus=D('1.105'),
        manual_penalty=D('-0.20'),
        employ_type='full_time',
    )
    assert isinstance(period['周期天数'], Decimal)
    assert period['周期天数'] == D(31)
    assert period['本期手工奖'] == D('1.11')
    assert period['本期手工惩'] == D('-0.20')
    segment = build_segment_context(
        period,
        plan_order_count=15,
        segment_days=15,
        accrued_gross=D('10.005'),
        per_order_total=D('3.335'),
    )
    assert segment['方案期内单量'] == D(15)
    assert segment['方案生效天数'] == D(15)
    assert segment['本期已计金额'] == D('10.01')
    assert segment['本期逐单金额'] == D('3.34')
