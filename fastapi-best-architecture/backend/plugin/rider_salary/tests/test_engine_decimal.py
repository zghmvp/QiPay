"""公式引擎全程 Decimal：分位边界按 ROUND_HALF_UP，不走二进制浮点。"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from backend.plugin.rider_salary.engine.compiler import compile_formula
from backend.plugin.rider_salary.engine.context import (
    build_order_context,
    build_period_context,
    build_segment_context,
    trace_variables,
)
from backend.plugin.rider_salary.engine.evaluator import evaluate_amount
from backend.plugin.rider_salary.engine.fields import COUNT_FIELDS, DECIMAL_FIELDS, NUMBER_FIELDS
from backend.plugin.rider_salary.engine.functions import fn_ceil, fn_floor, fn_minutes, to_minutes
from backend.plugin.rider_salary.engine.ladder import ladder
from backend.plugin.rider_salary.enums import CalcStage
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

ENGINE_DIR = Path(__file__).resolve().parents[1] / 'engine'
PER_ORDER = CalcStage.per_order.value
PERIOD = CalcStage.period.value


def test_number_fields_split_into_decimal_and_count() -> None:
    """金额、距离和计数拆开，合起来刚好是全部数值字段。"""
    assert COUNT_FIELDS.isdisjoint(DECIMAL_FIELDS)
    assert COUNT_FIELDS | DECIMAL_FIELDS == NUMBER_FIELDS


def test_distance_times_unit_price_rounds_half_up() -> None:
    """1.5 公里 × 1.15 元 = 1.725，四舍五入到分是 1.73。"""
    names = {'配送距离': Decimal('1.5')}
    assert evaluate_amount('配送距离 * 1.15', names) == Decimal('1.73')
    assert evaluate_amount('配送距离 * 1.15', {'配送距离': 1.5}) == Decimal('1.73')

    expr = compile_formula(
        {'类型': '字段乘单价', '字段': '配送距离', '单价': Decimal('1.15'), '起算值': 0},
        PER_ORDER,
    )
    assert evaluate_amount(expr, names) == Decimal('1.73')
    # 先乘成 float 再舍入会得到 1.72，用来钉住这次要修的边界。
    assert q2(1.5 * 1.15) == Decimal('1.72')


def test_spec_half_up_examples() -> None:
    """纲要：2.125→2.13，2.135→2.14；底薪 2000×14/30→933.33。"""
    assert evaluate_amount('订单金额', {'订单金额': Decimal('2.125')}) == Decimal('2.13')
    assert evaluate_amount('订单金额', {'订单金额': Decimal('2.135')}) == Decimal('2.14')
    assert evaluate_amount('订单金额', {'订单金额': Decimal('-2.125')}) == Decimal('-2.13')
    assert evaluate_amount('订单金额', {'订单金额': Decimal('0.005')}) == Decimal('0.01')
    assert evaluate_amount('订单金额', {'订单金额': Decimal('-0.005')}) == Decimal('-0.01')
    assert evaluate_amount('2000 * 14 / 30', {}) == Decimal('933.33')


def test_decimal_mixes_with_int_counts() -> None:
    """单价是 Decimal 字面量，单量是 int，乘完仍按分四舍五入。"""
    assert evaluate_amount('周期单量 * 1.15', {'周期单量': 2}) == Decimal('2.30')
    assert evaluate_amount('10 + 配送距离', {'配送距离': Decimal('0.50')}) == Decimal('10.50')
    assert evaluate_amount('方案生效天数 / 周期天数', {'方案生效天数': 14, '周期天数': 30}) == Decimal('0.47')


def test_half_cent_products_follow_decimal_not_float() -> None:
    """第三位小数是 5 时，结果等于 Decimal 舍入；和 float 不一致的样本必须跟 Decimal。"""
    mismatches: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
    checked = 0
    for km_tenths in range(1, 31):
        for rate_hundredths in range(1, 151):
            thousandths = km_tenths * rate_hundredths
            if thousandths % 10 != 5:
                continue
            km = Decimal(km_tenths) / Decimal(10)
            rate = Decimal(rate_hundredths) / Decimal(100)
            product = km * rate
            got = evaluate_amount(f'配送距离 * {rate}', {'配送距离': km})
            assert got == q2(product)
            float_got = q2(float(km) * float(rate))
            if float_got != got:
                mismatches.append((km, rate, got, float_got))
            checked += 1
    assert checked > 0
    assert (Decimal('1.5'), Decimal('1.15'), Decimal('1.73'), Decimal('1.72')) in mismatches


def test_ladder_compares_and_multiplies_in_decimal() -> None:
    """档位边界含下限不含上限；1.5 × 1.15 在落档里仍是 1.725。"""
    tiers = [
        {'下限': 0, '上限': 1, '值': 1},
        {'下限': 1, '上限': 2, '值': Decimal('1.15')},
        {'下限': 2, '上限': None, '值': 2},
    ]
    assert ladder(Decimal('1.5'), '全量落档', '按单价', tiers) == Decimal('1.5') * Decimal('1.15')
    assert q2(ladder(Decimal('1.5'), '全量落档', '按单价', tiers)) == Decimal('1.73')
    assert ladder(Decimal(1), '全量落档', '按单价', tiers) == Decimal('1.15')
    assert ladder(Decimal(2), '全量落档', '按单价', tiers) == Decimal(4)
    assert ladder(Decimal('0.5'), '全量落档', '固定金额', tiers) == Decimal(1)

    progressive = [[0, Decimal('1.5'), Decimal('1.15')], [Decimal('1.5'), None, 2]]
    assert ladder(Decimal('1.5'), '分段累进', '按单价', progressive) == Decimal('1.5') * Decimal('1.15')
    assert ladder(Decimal(2), '分段累进', '按单价', progressive) == (
        Decimal('1.5') * Decimal('1.15') + Decimal('0.5') * 2
    )


def test_whitelist_numbers_are_decimal_and_minutes_are_int() -> None:
    """数值白名单函数返回 Decimal；时刻分钟是 int。"""
    assert fn_floor('1.9') == Decimal(1)
    assert isinstance(fn_floor('1.9'), Decimal)
    assert fn_ceil('1.1') == Decimal(2)
    assert isinstance(fn_ceil('1.1'), Decimal)
    assert fn_minutes('22:18') == 22 * 60 + 18
    assert isinstance(fn_minutes('22:18'), int)
    moment = datetime(2026, 9, 1, 23, 5, tzinfo=timezone.tz_info)
    assert to_minutes(moment) == 23 * 60 + 5
    assert isinstance(to_minutes(moment), int)


def test_context_uses_decimal_for_money_and_int_for_counts() -> None:
    """上下文里的金额、距离是 Decimal，单量和时刻是 int。"""
    moment = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.tz_info)
    order = SimpleNamespace(
        distance_km=Decimal('1.5'),
        weight_jin=Decimal('2.25'),
        amount=Decimal('2.125'),
        order_time=moment,
        deliver_time=moment.replace(minute=28),
        status='completed',
        order_no='D-1',
        id=1,
        biz_date=moment.date(),
    )
    ctx = build_order_context(order, {'日期': '2026-09-01'})
    assert ctx['配送距离'] == Decimal('1.5')
    assert isinstance(ctx['配送距离'], Decimal)
    assert isinstance(ctx['订单金额'], Decimal)
    assert isinstance(ctx['配送时长'], Decimal)
    assert ctx['配送时长'] == Decimal(28)
    assert ctx['下单时刻'] == 10 * 60
    assert isinstance(ctx['下单时刻'], int)

    period = build_period_context(
        period_days=30,
        order_count=10,
        valid_order_count=8,
        attendance_days=6,
        hire_date=moment.date(),
        period_end=moment.date(),
        manual_bonus=Decimal('1.125'),
        manual_penalty=Decimal('-0.5'),
        employ_type='full_time',
    )
    assert period['周期单量'] == 8
    assert isinstance(period['周期单量'], int)
    assert isinstance(period['本期手工奖'], Decimal)
    assert period['本期手工奖'] == Decimal('1.13')
    segment = build_segment_context(
        period,
        plan_order_count=8,
        segment_days=14,
        accrued_gross=Decimal('10.005'),
        per_order_total=Decimal(3),
    )
    assert segment['方案生效天数'] == 14
    assert isinstance(segment['方案生效天数'], int)
    assert segment['本期已计金额'] == Decimal('10.01')
    assert isinstance(segment['本期已计金额'], Decimal)


def test_trace_stringifies_decimal_and_keeps_counts() -> None:
    """calc_trace 只在序列化时把 Decimal 变成字符串，计数仍是 int。"""
    traced = trace_variables('配送距离 * 1.15', {'配送距离': Decimal('1.50'), '周期单量': 8})
    assert traced == {'配送距离': '1.50'}
    counts = trace_variables('周期单量 + 方案生效天数', {'周期单量': 8, '方案生效天数': 14})
    assert counts == {'周期单量': 8, '方案生效天数': 14}
    assert all(isinstance(value, int) for value in counts.values())


def test_engine_source_has_no_float_cast() -> None:
    """engine 里不再把数值转成 float。"""
    hits: list[str] = []
    for path in sorted(ENGINE_DIR.glob('*.py')):
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if 'float(' in line:
                hits.append(f'{path.name}:{lineno}')
    assert hits == []
