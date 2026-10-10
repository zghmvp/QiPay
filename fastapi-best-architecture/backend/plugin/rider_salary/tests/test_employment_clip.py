"""在职区间裁剪：月中离职、月初入职、同月入离职，以及算薪名单谓词。"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from backend.plugin.rider_salary.engine.compiler import compile_condition, compile_formula
from backend.plugin.rider_salary.engine.context import clip_date_range
from backend.plugin.rider_salary.engine.segments import PlanItemView, Segment
from backend.plugin.rider_salary.enums import CalcStage, OrderStatus, SubjectDirection
from backend.plugin.rider_salary.service.calc_service import (
    CalcInput,
    CalcResult,
    _resign_before_period_without_facts,
    run_calc_pipeline,
)
from backend.utils.timezone import timezone

TZ = timezone.tz_info
D = Decimal
PERIOD_START = date(2026, 9, 1)
PERIOD_END = date(2026, 9, 30)


def _item(pk: int, name: str, stage: str, sort_order: int, formula: dict) -> PlanItemView:
    return PlanItemView(
        id=pk,
        subject_id=pk,
        name=name,
        stage=stage,
        sort_order=sort_order,
        condition_json={},
        formula_json=formula,
        condition_expr=compile_condition({}, stage),
        formula_expr=compile_formula(formula, stage),
        enabled=True,
        direction=SubjectDirection.bonus.value,
        include_in_gross=True,
    )


def _segment(start: date, end: date, version_id: int = 1, *, with_per_order: bool = False) -> Segment:
    items = [
        _item(1, '按日补贴', CalcStage.daily.value, 10, {'类型': '固定金额', '金额': 10}),
        _item(2, '底薪', CalcStage.period.value, 30, {'类型': '表达式', '表达式': '3000 * 方案生效天数 / 周期天数'}),
    ]
    if with_per_order:
        items.insert(0, _item(3, '基础单价', CalcStage.per_order.value, 5, {'类型': '固定金额', '金额': 4}))
    return Segment(plan_version_id=version_id, start_date=start, end_date=end, items=items)


def _order(day: date, oid: int) -> SimpleNamespace:
    moment = datetime(day.year, day.month, day.day, 10, 0, tzinfo=TZ)
    return SimpleNamespace(
        id=oid,
        order_no=f'ORD-{oid}',
        site_id=1,
        rider_id=1,
        biz_date=day,
        distance_km=D('3.20'),
        weight_jin=D('4.50'),
        order_time=moment,
        deliver_time=moment,
        status=OrderStatus.completed.value,
        amount=D('28.00'),
    )


def _run(**overrides: object) -> CalcResult:
    payload = {
        'rider_id': 1,
        'site_id': 1,
        'period_start': PERIOD_START,
        'period_end': PERIOD_END,
        'hire_date': date(2026, 1, 1),
        'leave_date': None,
        'employ_type': 'full_time',
        'segments': [_segment(PERIOD_START, PERIOD_END)],
        'orders': [],
        'day_flags': {},
        'employ_history': [],
        'adjustments': [],
        'advances': [],
        'covered_dates': set(),
        'site_order_dates': set(),
    }
    payload.update(overrides)
    return run_calc_pipeline(CalcInput(**payload))


def test_clip_date_range_closed_interval() -> None:
    """在职裁剪是闭区间：离职日和入职日都算在内，没有交集则整段跳过。"""
    assert clip_date_range(PERIOD_START, PERIOD_END, date(2026, 1, 1), None) == (PERIOD_START, PERIOD_END)
    assert clip_date_range(PERIOD_START, PERIOD_END, None, date(2026, 9, 10)) == (PERIOD_START, date(2026, 9, 10))
    assert clip_date_range(PERIOD_START, PERIOD_END, date(2026, 9, 5), date(2026, 9, 20)) == (
        date(2026, 9, 5),
        date(2026, 9, 20),
    )
    assert clip_date_range(PERIOD_START, PERIOD_END, date(2026, 9, 10), date(2026, 9, 10)) == (
        date(2026, 9, 10),
        date(2026, 9, 10),
    )
    assert clip_date_range(PERIOD_START, PERIOD_END, None, date(2026, 8, 31)) is None
    assert clip_date_range(PERIOD_START, PERIOD_END, date(2026, 10, 1), None) is None


def test_full_month_without_leave_keeps_full_amount() -> None:
    """入职早于周期、未离职时，按日项和底薪仍按整期 30 天。"""
    result = _run()
    assert result.daily_total == D('300.00')
    assert result.period_total == D('3000.00')
    salary = next(row for row in result.details if row.name == '底薪')
    assert salary.calc_trace['变量']['方案生效天数'] == 30
    assert salary.calc_trace['变量']['周期天数'] == 30


def test_mid_month_leave_prorates_daily_and_base() -> None:
    """9/10 离职：离职日含当日，在职 10 天。按日 10 元 × 10，底薪 3000 × 10/30。"""
    result = _run(leave_date=date(2026, 9, 10))
    daily_days = [row.biz_date for row in result.details if row.stage == CalcStage.daily.value]
    salary = next(row for row in result.details if row.name == '底薪')
    assert result.daily_total == D('100.00')
    assert result.period_total == D('1000.00')
    assert daily_days[0] == date(2026, 9, 1)
    assert daily_days[-1] == date(2026, 9, 10)
    assert len(daily_days) == 10
    assert date(2026, 9, 11) not in daily_days
    assert salary.calc_trace['变量']['方案生效天数'] == 10
    assert salary.calc_trace['变量']['周期天数'] == 30


def test_early_month_hire_prorates_from_hire_date() -> None:
    """9/3 入职：9/1、9/2 不计，在职 28 天，底薪按 28/30。"""
    result = _run(hire_date=date(2026, 9, 3), leave_date=None)
    daily_days = [row.biz_date for row in result.details if row.stage == CalcStage.daily.value]
    salary = next(row for row in result.details if row.name == '底薪')
    assert daily_days[0] == date(2026, 9, 3)
    assert len(daily_days) == 28
    assert result.daily_total == D('280.00')
    assert result.period_total == D('2800.00')
    assert salary.calc_trace['变量']['方案生效天数'] == 28
    assert salary.calc_trace['变量']['周期天数'] == 30


def test_hire_and_leave_in_same_period() -> None:
    """9/5 入职、9/20 离职：闭区间 16 天，底薪按 16/30。"""
    result = _run(hire_date=date(2026, 9, 5), leave_date=date(2026, 9, 20))
    daily_days = [row.biz_date for row in result.details if row.stage == CalcStage.daily.value]
    salary = next(row for row in result.details if row.name == '底薪')
    assert daily_days[0] == date(2026, 9, 5)
    assert daily_days[-1] == date(2026, 9, 20)
    assert len(daily_days) == 16
    assert result.daily_total == D('160.00')
    assert result.period_total == D('1600.00')
    assert salary.calc_trace['变量']['方案生效天数'] == 16


def test_segment_after_leave_does_not_pay_another_base() -> None:
    """9/10 离职后，9/15 起的方案段不再计按日项和底薪。"""
    result = _run(
        leave_date=date(2026, 9, 10),
        segments=[
            _segment(date(2026, 9, 1), date(2026, 9, 14), 1),
            _segment(date(2026, 9, 15), date(2026, 9, 30), 2),
        ],
    )
    salaries = [row for row in result.details if row.name == '底薪']
    assert len(salaries) == 1
    assert salaries[0].plan_version_id == 1
    assert salaries[0].amount == D('1000.00')
    assert salaries[0].calc_trace['变量']['方案生效天数'] == 10
    assert result.daily_total == D('100.00')


def test_orders_on_leave_date_count_and_later_orders_warn() -> None:
    """离职日当天的有效单计薪；次日订单不计，并提示已离职。"""
    result = _run(
        leave_date=date(2026, 9, 10),
        segments=[_segment(PERIOD_START, PERIOD_END, with_per_order=True)],
        orders=[_order(date(2026, 9, 10), 1), _order(date(2026, 9, 11), 2)],
    )
    per_order = [row for row in result.details if row.name == '基础单价']
    assert result.valid_order_count == 1
    assert len(per_order) == 1
    assert per_order[0].biz_date == date(2026, 9, 10)
    assert per_order[0].amount == D('4.00')
    assert any('2026-09-10' in warning and '离职' in warning for warning in result.warnings)


def test_order_before_hire_is_not_paid() -> None:
    """入职日前的有效单不进周期单量，也不产生逐单明细。"""
    result = _run(
        hire_date=date(2026, 9, 11),
        segments=[_segment(PERIOD_START, PERIOD_END, with_per_order=True)],
        orders=[_order(date(2026, 9, 10), 1), _order(date(2026, 9, 11), 2)],
    )
    per_order = [row for row in result.details if row.name == '基础单价']
    assert result.valid_order_count == 1
    assert len(per_order) == 1
    assert per_order[0].biz_date == date(2026, 9, 11)


def test_resign_roster_keeps_leave_date_and_period_facts() -> None:
    """离职日早于周期起点且没有任何本期事实才排除；离职日当天和有订单、有奖惩的仍算。"""
    start = date(2026, 10, 1)
    assert _resign_before_period_without_facts(date(2026, 9, 10), start, has_orders=False, has_adjustments=False)
    assert not _resign_before_period_without_facts(date(2026, 10, 1), start, has_orders=False, has_adjustments=False)
    assert not _resign_before_period_without_facts(None, start, has_orders=False, has_adjustments=False)
    assert not _resign_before_period_without_facts(date(2026, 9, 10), start, has_orders=True, has_adjustments=False)
    assert not _resign_before_period_without_facts(date(2026, 9, 10), start, has_orders=False, has_adjustments=True)
