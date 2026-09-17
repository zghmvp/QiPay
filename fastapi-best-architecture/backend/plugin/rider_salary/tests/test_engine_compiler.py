from datetime import date

import pytest

from backend.plugin.rider_salary.engine.compiler import compile_condition, compile_formula
from backend.plugin.rider_salary.engine.evaluator import evaluate, evaluate_amount, evaluate_condition
from backend.plugin.rider_salary.engine.functions import to_minutes
from backend.plugin.rider_salary.enums import CalcStage

STAGE = CalcStage.per_order.value


def test_empty_condition_is_true() -> None:
    assert compile_condition({}) == 'True'
    assert compile_condition(None) == 'True'
    assert evaluate_condition('True', {}) is True


def test_overnight_time_range() -> None:
    raw = {
        '逻辑': '且',
        '条件': [
            {'字段': '送达时刻', '运算符': '在时段内', '值': ['22:00', '06:00']},
            {'字段': '配送距离', '运算符': '>', '值': 5},
        ],
    }
    expr = compile_condition(raw, STAGE)
    assert '在时段内(送达时刻, "22:00", "06:00")' in expr
    assert '配送距离 > 5' in expr
    names_hit = {'送达时刻': to_minutes('22:18'), '配送距离': 7.2}
    names_miss = {'送达时刻': to_minutes('10:28'), '配送距离': 7.2}
    assert evaluate_condition(expr, names_hit) is True
    assert evaluate_condition(expr, names_miss) is False
    overnight = {'送达时刻': to_minutes('00:20'), '配送距离': 6}
    assert evaluate_condition(expr, overnight) is True


def test_datetime_minutes_use_app_timezone() -> None:
    from datetime import datetime
    from datetime import timezone as dt_timezone

    utc_1025_shanghai = datetime(2026, 9, 1, 2, 25, tzinfo=dt_timezone.utc)
    utc_2305_shanghai = datetime(2026, 9, 1, 15, 5, tzinfo=dt_timezone.utc)
    assert to_minutes(utc_1025_shanghai) == 10 * 60 + 25
    assert to_minutes(utc_2305_shanghai) == 23 * 60 + 5
    from types import SimpleNamespace

    from backend.plugin.rider_salary.engine.context import build_day_context, build_order_context

    day = date(2026, 9, 1)
    order = SimpleNamespace(
        order_time=utc_1025_shanghai,
        deliver_time=utc_2305_shanghai,
        distance_km=7.2,
        weight_jin=1,
        amount=1,
        status='completed',
        order_no='tz',
        id=1,
        biz_date=day,
    )
    ctx = build_order_context(order, build_day_context(1, day, 'part_time'))
    assert ctx['下单时刻'] == 10 * 60 + 25
    assert ctx['送达时刻'] == 23 * 60 + 5


def test_night_window_shanghai_2305_hits_1300_misses() -> None:
    """清单 #2：送达 23:05 Asia/Shanghai 命中夜间加价，13:00 不命中。

    UTC 05:00 = 上海 13:00；若按 UTC 取时分会落入 22:00–06:00 而误命中。
    """
    from datetime import datetime
    from datetime import timezone as dt_timezone

    from backend.utils.timezone import timezone as app_tz

    expr = compile_condition({'字段': '送达时刻', '运算符': '在时段内', '值': ['22:00', '06:00']}, STAGE)
    shanghai_2305 = datetime(2026, 9, 1, 23, 5, tzinfo=app_tz.tz_info)
    shanghai_1300 = datetime(2026, 9, 1, 13, 0, tzinfo=app_tz.tz_info)
    utc_as_2305 = datetime(2026, 9, 1, 15, 5, tzinfo=dt_timezone.utc)
    utc_as_1300 = datetime(2026, 9, 1, 5, 0, tzinfo=dt_timezone.utc)
    assert evaluate_condition(expr, {'送达时刻': to_minutes(shanghai_2305)}) is True
    assert evaluate_condition(expr, {'送达时刻': to_minutes(utc_as_2305)}) is True
    assert evaluate_condition(expr, {'送达时刻': to_minutes(shanghai_1300)}) is False
    assert evaluate_condition(expr, {'送达时刻': to_minutes(utc_as_1300)}) is False


def test_belong_and_not_belong() -> None:
    raw = {
        '逻辑': '且',
        '条件': [
            {'字段': '星期', '运算符': '不属于', '值': [6, 7]},
            {'字段': '配送时长', '运算符': '在区间内', '值': [0, 60]},
        ],
    }
    expr = compile_condition(raw, STAGE)
    assert 'not in' in expr
    assert evaluate_condition(expr, {'星期': 1, '配送时长': 28}) is True
    assert evaluate_condition(expr, {'星期': 6, '配送时长': 28}) is False
    belong = {'字段': '订单状态', '运算符': '属于', '值': ['completed', 'abnormal']}
    belong_expr = compile_condition(belong, STAGE)
    assert evaluate_condition(belong_expr, {'订单状态': 'completed'}) is True
    assert evaluate_condition(belong_expr, {'订单状态': 'cancelled'}) is False


def test_nested_or() -> None:
    raw = {
        '逻辑': '或',
        '条件': [
            {'字段': '是否节假日', '运算符': '=', '值': True},
            {'字段': '是否周末', '运算符': '=', '值': True},
        ],
    }
    expr = compile_condition(raw, STAGE)
    assert '是否节假日 == True' in expr
    assert '是否周末 == True' in expr
    assert evaluate_condition(expr, {'是否节假日': False, '是否周末': True}) is True
    assert evaluate_condition(expr, {'是否节假日': False, '是否周末': False}) is False


def test_nested_and_or_with_night() -> None:
    raw = {
        '逻辑': '且',
        '条件': [
            {'字段': '送达时刻', '运算符': '在时段内', '值': ['22:00', '06:00']},
            {'字段': '配送距离', '运算符': '>', '值': 5},
            {
                '逻辑': '或',
                '条件': [
                    {'字段': '是否节假日', '运算符': '=', '值': True},
                    {'字段': '是否周末', '运算符': '=', '值': True},
                ],
            },
        ],
    }
    expr = compile_condition(raw, STAGE)
    names = {
        '送达时刻': to_minutes('22:18'),
        '配送距离': 7.2,
        '是否节假日': False,
        '是否周末': True,
    }
    assert evaluate_condition(expr, names) is True
    names['是否周末'] = False
    assert evaluate_condition(expr, names) is False


def test_compare_amount_and_status() -> None:
    raw = {
        '逻辑': '且',
        '条件': [
            {'字段': '订单金额', '运算符': '≥', '值': 50},
            {'字段': '订单状态', '运算符': '=', '值': 'completed'},
        ],
    }
    expr = compile_condition(raw, STAGE)
    assert evaluate_condition(expr, {'订单金额': 50, '订单状态': 'completed'}) is True
    assert evaluate_condition(expr, {'订单金额': 49.99, '订单状态': 'completed'}) is False


def test_weight_gt() -> None:
    expr = compile_condition({'逻辑': '且', '条件': [{'字段': '商品重量', '运算符': '>', '值': 20}]}, STAGE)
    assert expr == '商品重量 > 20' or '商品重量 > 20' in expr
    assert evaluate_condition(expr, {'商品重量': 25}) is True
    assert evaluate_condition(expr, {'商品重量': 20}) is False


def test_not_in_time_range() -> None:
    raw = {'字段': '送达时刻', '运算符': '不在时段内', '值': ['22:00', '06:00']}
    expr = compile_condition(raw, STAGE)
    assert evaluate_condition(expr, {'送达时刻': to_minutes('10:00')}) is True
    assert evaluate_condition(expr, {'送达时刻': to_minutes('23:00')}) is False


def test_formula_fixed() -> None:
    expr = compile_formula({'类型': '固定金额', '金额': 2})
    assert expr == '2'
    assert evaluate_amount(expr, {}) == evaluate_amount('2', {})


def test_formula_field_rate() -> None:
    expr = compile_formula({'类型': '字段乘单价', '字段': '配送距离', '单价': 0.8, '起算值': 5}, STAGE)
    assert '最大值' in expr
    assert evaluate_amount(expr, {'配送距离': 7.2}) == evaluate_amount('1.76', {})
    assert evaluate_amount(expr, {'配送距离': 3}) == evaluate_amount('0', {})


def test_formula_ladder_compile() -> None:
    formula = {
        '类型': '阶梯',
        '字段': '周期单量',
        '模式': '全量落档',
        '计价': '按单价',
        '档位': [
            {'下限': 0, '上限': 300, '值': 5},
            {'下限': 300, '上限': 600, '值': 5.5},
            {'下限': 600, '上限': None, '值': 6},
        ],
    }
    expr = compile_formula(formula, CalcStage.period.value)
    assert expr.startswith('阶梯(周期单量')
    assert evaluate(expr, {'周期单量': 420}) == pytest.approx(420 * 5.5)


def test_formula_expression() -> None:
    expr = compile_formula({'类型': '表达式', '表达式': '最大值(0, 3000 - 本期已计金额)'}, CalcStage.period.value)
    assert expr == '最大值(0, 3000 - 本期已计金额)'
    assert evaluate_amount(expr, {'本期已计金额': 2089.33}) == evaluate_amount('910.67', {})
