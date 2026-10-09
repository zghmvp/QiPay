"""P2-03：周期阶段不能引用日期和日单量；用工类型按段末历史取值，月中变化时切段。"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.plugin.rider_salary.engine.compiler import CompileError, compile_condition, compile_formula, validate_item
from backend.plugin.rider_salary.engine.context import (
    build_day_context,
    build_period_context,
    tenure_days,
    tenure_months,
)
from backend.plugin.rider_salary.engine.fields import (
    FIELDS,
    PERIOD_STAGE_BANNED_FIELDS,
    TYPE_NUMBER,
    field_available,
)
from backend.plugin.rider_salary.engine.segments import Segment, employ_type_on, split_segments_by_employ
from backend.plugin.rider_salary.enums import CalcStage, OrderStatus, SubjectDirection
from backend.plugin.rider_salary.service.calc_service import CalcInput, run_calc_pipeline
from backend.utils.timezone import timezone

TZ = timezone.tz_info
PERIOD = CalcStage.period.value
DAILY = CalcStage.daily.value
PER_ORDER = CalcStage.per_order.value
DAY = date(2026, 9, 1)
MONTH_START = date(2026, 9, 1)
MONTH_END = date(2026, 9, 30)


def _history(employ_type: str, start: date, end: date | None) -> SimpleNamespace:
    return SimpleNamespace(employ_type=employ_type, start_date=start, end_date=end)


def _item(pk: int, name: str, stage: str, condition: dict | None, formula: dict) -> object:
    from backend.plugin.rider_salary.engine.segments import PlanItemView

    return PlanItemView(
        id=pk,
        subject_id=pk,
        name=name,
        stage=stage,
        sort_order=pk * 10,
        condition_json=condition,
        formula_json=formula,
        condition_expr=compile_condition(condition, stage),
        formula_expr=compile_formula(formula, stage),
        enabled=True,
        direction=SubjectDirection.bonus.value,
        include_in_gross=True,
    )


def _pipeline(**overrides: object) -> object:
    payload = {
        'rider_id': 1,
        'site_id': 1,
        'period_start': MONTH_START,
        'period_end': MONTH_END,
        'hire_date': date(2025, 3, 1),
        'leave_date': None,
        'employ_type': 'full_time',
        'segments': [],
        'orders': [],
        'day_flags': {},
        'employ_history': [],
        'adjustments': [],
        'advances': [],
        'covered_dates': set(),
        'site_order_dates': set(),
        'persist_advance': False,
    }
    payload.update(overrides)
    return run_calc_pipeline(CalcInput(**payload))


def test_period_stage_rejects_date_and_daily_counts() -> None:
    """保存周期项时，引用日期或三个日单量要在编译期被拒，错误是中文。"""
    banned = ('日期', '日单量', '日总单量', '日有效单量')
    assert set(banned) == set(PERIOD_STAGE_BANNED_FIELDS)
    for name in banned:
        assert field_available(name, PERIOD) is False
        with pytest.raises(CompileError, match=f'周期阶段不能引用字段「{name}」'):
            compile_condition({'字段': name, '运算符': '=', '值': '2026-09-01' if name == '日期' else 1}, PERIOD)
        with pytest.raises(CompileError, match=f'周期阶段不能引用字段「{name}」'):
            compile_formula({'类型': '表达式', '表达式': name}, PERIOD)

    saved = validate_item(
        PERIOD,
        {
            '逻辑': '且',
            '条件': [
                {'字段': '日期', '运算符': '≥', '值': '2026-09-01'},
                {'字段': '周期单量', '运算符': '>', '值': 0},
            ],
        },
        {'类型': '表达式', '表达式': '日单量 + 日总单量 + 日有效单量'},
    )
    assert saved.ok is False
    assert '周期阶段不能引用字段「日期」' in saved.errors
    assert '周期阶段不能引用字段「日单量」' in saved.errors
    assert '周期阶段不能引用字段「日总单量」' in saved.errors
    assert '周期阶段不能引用字段「日有效单量」' in saved.errors

    ladder = validate_item(
        PERIOD,
        {},
        {
            '类型': '阶梯',
            '字段': '日有效单量',
            '模式': '全量落档',
            '计价': '按单价',
            '档位': [{'下限': 0, '上限': None, '值': 1}],
        },
    )
    assert ladder.ok is False
    assert ladder.errors == ['周期阶段不能引用字段「日有效单量」']

    rate = validate_item(PERIOD, {}, {'类型': '字段乘单价', '字段': '日单量', '单价': 1, '起算值': 0})
    assert rate.ok is False
    assert '周期阶段不能引用字段「日单量」' in rate.errors

    # 按日仍可用；逐单可以用日期，但不能用日单量。
    assert compile_condition({'字段': '日期', '运算符': '=', '值': '2026-09-01'}, DAILY)
    assert compile_formula({'类型': '表达式', '表达式': '日单量 + 日总单量 + 日有效单量'}, DAILY)
    assert compile_condition({'字段': '日期', '运算符': '=', '值': '2026-09-01'}, PER_ORDER)
    with pytest.raises(CompileError, match='字段「日单量」在该阶段不可用'):
        compile_formula({'类型': '表达式', '表达式': '日单量'}, PER_ORDER)


def test_period_context_has_no_meaningless_daily_placeholders() -> None:
    """周期上下文不再塞恒为 0 的日单量，也不再可选地塞一个日期。"""
    ctx = build_period_context(
        period_days=30,
        order_count=2,
        valid_order_count=1,
        attendance_days=1,
        hire_date=date(2025, 3, 1),
        period_end=MONTH_END,
        manual_bonus=Decimal(0),
        manual_penalty=Decimal(0),
        employ_type='full_time',
    )
    for name in PERIOD_STAGE_BANNED_FIELDS:
        assert name not in ctx
    assert ctx['周期单量'] == 1
    assert ctx['周期总单量'] == 2


def test_employ_on_prefers_latest_covering_history() -> None:
    """同一天被多段盖住时，取开始日最晚的一段；结束日当天仍算在这段里。"""
    history = [
        _history('part_time', date(2026, 9, 1), date(2026, 9, 30)),
        _history('full_time', date(2026, 9, 15), date(2026, 9, 20)),
    ]
    assert employ_type_on(history, 'part_time', date(2026, 9, 15)) == 'full_time'
    assert employ_type_on(history, 'part_time', date(2026, 9, 20)) == 'full_time'
    assert employ_type_on(history, 'part_time', date(2026, 9, 21)) == 'part_time'
    assert employ_type_on([], 'full_time', date(2026, 9, 1)) == 'full_time'


def test_split_keeps_stable_segment_and_cuts_on_change() -> None:
    """类型不变不切段；变化落在首日或末日时，边界日单独成段。不同方案段不会被并回去。"""
    stable = Segment(plan_version_id=1, start_date=MONTH_START, end_date=MONTH_END, items=[])
    assert split_segments_by_employ([stable], [], 'full_time')[0] is stable

    early = Segment(plan_version_id=1, start_date=MONTH_START, end_date=date(2026, 9, 10), items=[])
    late = Segment(plan_version_id=2, start_date=date(2026, 9, 11), end_date=MONTH_END, items=[])
    kept = split_segments_by_employ([early, late], [], 'full_time')
    assert kept[0] is early
    assert kept[1] is late

    last_day = split_segments_by_employ(
        [stable],
        [
            _history('part_time', MONTH_START, date(2026, 9, 29)),
            _history('full_time', date(2026, 9, 30), None),
        ],
        'part_time',
    )
    assert [(row.start_date, row.end_date) for row in last_day] == [
        (MONTH_START, date(2026, 9, 29)),
        (date(2026, 9, 30), date(2026, 9, 30)),
    ]

    first_day = split_segments_by_employ(
        [stable],
        [
            _history('full_time', MONTH_START, MONTH_START),
            _history('part_time', date(2026, 9, 2), None),
        ],
        'part_time',
    )
    assert [(row.start_date, row.end_date) for row in first_day] == [
        (MONTH_START, MONTH_START),
        (date(2026, 9, 2), MONTH_END),
    ]


def test_period_item_uses_history_not_current_snapshot() -> None:
    """整段用工类型没变时不切段，周期项用历史值，不用骑手当前快照。"""
    segment = Segment(
        plan_version_id=4,
        start_date=MONTH_START,
        end_date=MONTH_END,
        items=[
            _item(
                1,
                '兼职补贴',
                PERIOD,
                {'字段': '用工类型', '运算符': '=', '值': 'part_time'},
                {'类型': '固定金额', '金额': 80},
            )
        ],
    )
    result = _pipeline(
        employ_type='full_time',
        segments=[segment],
        employ_history=[_history('part_time', MONTH_START, None)],
    )
    hits = [row for row in result.details if row.name == '兼职补贴']
    assert len(hits) == 1
    assert hits[0].amount == Decimal('80.00')
    assert hits[0].calc_trace['变量']['用工类型'] == 'part_time'
    assert result.plan_version_ids == [4]
    assert result.period_total == Decimal('80.00')


def test_employ_change_splits_segment_and_period_item_uses_segment_end() -> None:
    """用工类型月中变化后切成两段，每段按自己的段末历史计算。"""
    segment = Segment(
        plan_version_id=7,
        start_date=MONTH_START,
        end_date=MONTH_END,
        items=[
            _item(
                1,
                '兼职补贴',
                PERIOD,
                {'字段': '用工类型', '运算符': '=', '值': 'part_time'},
                {'类型': '表达式', '表达式': '10 * 方案生效天数'},
            ),
            _item(
                2,
                '全职补贴',
                PERIOD,
                {'字段': '用工类型', '运算符': '=', '值': 'full_time'},
                {'类型': '表达式', '表达式': '20 * 方案生效天数'},
            ),
        ],
    )
    result = _pipeline(
        employ_type='part_time',
        segments=[segment],
        employ_history=[
            _history('part_time', MONTH_START, date(2026, 9, 10)),
            _history('full_time', date(2026, 9, 11), None),
        ],
    )
    part = next(row for row in result.details if row.name == '兼职补贴')
    full = next(row for row in result.details if row.name == '全职补贴')
    assert part.amount == Decimal('100.00')
    assert part.calc_trace['变量']['用工类型'] == 'part_time'
    assert part.calc_trace['变量']['方案生效天数'] == 10
    assert full.amount == Decimal('400.00')
    assert full.calc_trace['变量']['用工类型'] == 'full_time'
    assert full.calc_trace['变量']['方案生效天数'] == 20
    assert result.period_total == Decimal('500.00')
    assert result.plan_version_ids == [7]


def _eq(name: str, value: object) -> dict:
    return {'字段': name, '运算符': '=', '值': value}


def _stage_fields(stage: str) -> list:
    return [item for item in FIELDS if stage in item.stages]


def _condition_for(stage: str, values: dict) -> dict | None:
    leaves = []
    for spec in _stage_fields(stage):
        if spec.type == TYPE_NUMBER:
            continue
        if spec.type == 'time':
            continue
        leaves.append(_eq(spec.name, values[spec.name]))
    if spec_times := [item.name for item in _stage_fields(stage) if item.type == 'time']:
        clocks = {'下单时刻': '10:00', '送达时刻': '10:28'}
        leaves.extend(_eq(name, clocks[name]) for name in spec_times)
    if not leaves:
        return {}
    if len(leaves) == 1:
        return leaves[0]
    return {'逻辑': '且', '条件': leaves}


def _formula_for(stage: str) -> dict:
    names = [item.name for item in _stage_fields(stage) if item.type == TYPE_NUMBER]
    return {'类型': '表达式', '表达式': ' + '.join(names)}


def test_compiled_stage_fields_exist_and_mean_something_at_runtime() -> None:
    """编译期开放的字段，流水线上下文里一定有，而且是这笔单、这一天、这一段的真实值。"""
    day_ctx = build_day_context(1, DAY, None, 'part_time')
    order_values = {
        **day_ctx,
        '订单状态': OrderStatus.completed.value,
    }
    items = [
        _item(1, '逐单契约', PER_ORDER, _condition_for(PER_ORDER, order_values), _formula_for(PER_ORDER)),
        _item(2, '按日契约', DAILY, _condition_for(DAILY, day_ctx), _formula_for(DAILY)),
        _item(3, '周期契约', PERIOD, _condition_for(PERIOD, {'用工类型': 'part_time'}), _formula_for(PERIOD)),
    ]
    segment = Segment(plan_version_id=1, start_date=DAY, end_date=DAY, items=items)
    completed = SimpleNamespace(
        id=1,
        order_no='C-1',
        site_id=1,
        rider_id=1,
        biz_date=DAY,
        distance_km=Decimal('1.5'),
        weight_jin=Decimal('2.25'),
        order_time=datetime(2026, 9, 1, 10, 0, tzinfo=TZ),
        deliver_time=datetime(2026, 9, 1, 10, 28, tzinfo=TZ),
        status=OrderStatus.completed.value,
        amount=Decimal('28.00'),
    )
    cancelled = SimpleNamespace(
        id=2,
        order_no='C-2',
        site_id=1,
        rider_id=1,
        biz_date=DAY,
        distance_km=Decimal(1),
        weight_jin=Decimal(1),
        order_time=datetime(2026, 9, 1, 11, 0, tzinfo=TZ),
        deliver_time=datetime(2026, 9, 1, 11, 10, tzinfo=TZ),
        status=OrderStatus.cancelled.value,
        amount=Decimal(1),
    )
    result = _pipeline(
        period_start=DAY,
        period_end=DAY,
        employ_type='full_time',
        segments=[segment],
        orders=[completed, cancelled],
        employ_history=[_history('part_time', DAY, None)],
        covered_dates={DAY},
        site_order_dates={DAY},
    )
    by_name = {row.name: row for row in result.details}
    assert set(by_name) >= {'逐单契约', '按日契约', '周期契约'}

    expected_by_stage = {
        '逐单契约': PER_ORDER,
        '按日契约': DAILY,
        '周期契约': PERIOD,
    }
    for name, stage in expected_by_stage.items():
        variables = by_name[name].calc_trace['变量']
        missing = [item.name for item in _stage_fields(stage) if item.name not in variables]
        assert missing == []

    order_vars = by_name['逐单契约'].calc_trace['变量']
    daily_vars = by_name['按日契约'].calc_trace['变量']
    period_vars = by_name['周期契约'].calc_trace['变量']
    assert order_vars['配送距离'] == '1.5'
    assert order_vars['日期'] == '2026-09-01'
    assert order_vars['用工类型'] == 'part_time'
    assert daily_vars['日期'] == '2026-09-01'
    assert daily_vars['日单量'] == 1
    assert daily_vars['日有效单量'] == 1
    assert daily_vars['日总单量'] == 2
    assert daily_vars['用工类型'] == 'part_time'
    assert period_vars['周期单量'] == 1
    assert period_vars['周期有效单量'] == 1
    assert period_vars['周期总单量'] == 2
    assert period_vars['出勤天数'] == 1
    assert period_vars['周期天数'] == 1
    assert period_vars['方案生效天数'] == 1
    assert period_vars['方案期内单量'] == 1
    assert period_vars['用工类型'] == 'part_time'
    assert period_vars['工龄月数'] == tenure_months(date(2025, 3, 1), DAY)
    assert period_vars['入职天数'] == tenure_days(date(2025, 3, 1), DAY)
    for name in PERIOD_STAGE_BANNED_FIELDS:
        assert name not in period_vars
