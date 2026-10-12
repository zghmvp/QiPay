"""P2-07：离职告警按日去重、方案版本去重、保底不含手工奖惩（Q-01 方案 B）。"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from backend.plugin.rider_salary.engine.compiler import compile_condition, compile_formula
from backend.plugin.rider_salary.engine.fields import FIELD_MAP
from backend.plugin.rider_salary.engine.segments import PlanItemView, Segment
from backend.plugin.rider_salary.enums import CalcStage, OrderStatus, SubjectDirection
from backend.plugin.rider_salary.service.calc_service import CalcInput, CalcResult, run_calc_pipeline
from backend.utils.timezone import timezone

TZ = timezone.tz_info
D = Decimal
START = date(2026, 9, 1)
END = date(2026, 9, 30)
LEAVE = date(2026, 9, 10)


def _item(pk: int, name: str, stage: str, formula: dict) -> PlanItemView:
    return PlanItemView(
        id=pk,
        subject_id=pk,
        name=name,
        stage=stage,
        sort_order=pk * 10,
        condition_json={},
        formula_json=formula,
        condition_expr=compile_condition({}, stage),
        formula_expr=compile_formula(formula, stage),
        enabled=True,
        direction=SubjectDirection.bonus.value,
        include_in_gross=True,
    )


def _segment(version_id: int, start: date, end: date, items: list[PlanItemView] | None = None) -> Segment:
    return Segment(plan_version_id=version_id, start_date=start, end_date=end, items=items or [])


def _order(day: date, oid: int, *, status: str = OrderStatus.completed.value) -> SimpleNamespace:
    moment = datetime(day.year, day.month, day.day, 10, 0, tzinfo=TZ)
    return SimpleNamespace(
        id=oid,
        order_no=f'P207-{oid}',
        site_id=1,
        rider_id=1,
        biz_date=day,
        distance_km=D('1.00'),
        weight_jin=D('1.00'),
        order_time=moment,
        deliver_time=moment,
        status=status,
        amount=D('10.00'),
    )


def _adjustment(oid: int, signed: str, direction: str, day: date) -> SimpleNamespace:
    return SimpleNamespace(
        id=oid,
        subject_id=oid,
        amount=D(signed).copy_abs(),
        signed_amount=D(signed),
        include_in_gross=True,
        direction=direction,
        biz_date=day,
        subject=SimpleNamespace(name='手工奖惩', direction=direction, include_in_gross=True),
    )


def _run(**overrides: object) -> CalcResult:
    payload = {
        'rider_id': 1,
        'site_id': 1,
        'period_start': START,
        'period_end': END,
        'hire_date': date(2026, 1, 1),
        'leave_date': None,
        'employ_type': 'full_time',
        'segments': [_segment(1, START, END)],
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


def _leave_warnings(warnings: list[str]) -> list[str]:
    return [item for item in warnings if '离职' in item]


def test_leave_warnings_are_dated_and_deduped() -> None:
    """同一天多笔订单只留一条；不同日期各带自己的日期，不再每天重复同一句。"""
    result = _run(
        leave_date=LEAVE,
        segments=[
            _segment(1, START, END, [_item(1, '基础单价', CalcStage.per_order.value, {'类型': '固定金额', '金额': 4})])
        ],
        orders=[
            _order(LEAVE, 1),
            _order(date(2026, 9, 12), 2),
            _order(date(2026, 9, 11), 3),
            _order(date(2026, 9, 11), 4),
            _order(date(2026, 9, 13), 5, status=OrderStatus.cancelled.value),
            _order(date(2026, 8, 31), 6),
        ],
    )
    assert _leave_warnings(result.warnings) == [
        '2026-09-11 骑手已于 2026-09-10 离职，该日订单未计薪',
        '2026-09-12 骑手已于 2026-09-10 离职，该日订单未计薪',
    ]
    paid = [row for row in result.details if row.name == '基础单价']
    assert len(paid) == 1
    assert paid[0].biz_date == LEAVE


def test_leave_warning_without_segment_still_names_each_day() -> None:
    """绑定被截到离职日后，次月没有方案段，仍按未计薪日期各写一条。"""
    result = _run(
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        leave_date=LEAVE,
        segments=[],
        orders=[
            _order(date(2026, 10, 3), 1),
            _order(date(2026, 10, 3), 2),
            _order(date(2026, 10, 1), 3),
        ],
    )
    assert _leave_warnings(result.warnings) == [
        '2026-10-01 骑手已于 2026-09-10 离职，该日订单未计薪',
        '2026-10-03 骑手已于 2026-09-10 离职，该日订单未计薪',
    ]


def test_plan_version_ids_dedupe_discontinuous_segments() -> None:
    """同一版本中间断开后再出现只保留第一次；不同版本仍按出现顺序保留。"""
    same = _run(
        segments=[
            _segment(8, date(2026, 9, 1), date(2026, 9, 10)),
            _segment(8, date(2026, 9, 20), date(2026, 9, 30)),
        ],
    )
    assert same.plan_version_ids == [8]

    returned = _run(
        segments=[
            _segment(15, date(2026, 9, 1), date(2026, 9, 5)),
            _segment(12, date(2026, 9, 10), date(2026, 9, 15)),
            _segment(15, date(2026, 9, 20), date(2026, 9, 30)),
        ],
    )
    assert returned.plan_version_ids == [15, 12]

    distinct = _run(
        segments=[
            _segment(12, date(2026, 9, 1), date(2026, 9, 14)),
            _segment(15, date(2026, 9, 15), date(2026, 9, 30)),
        ],
    )
    assert distinct.plan_version_ids == [12, 15]


def test_guarantee_excludes_manual_adjustments() -> None:
    """Q-01 方案 B：保底看的本期已计金额不含手工奖惩，扣罚后实发可以低于保底。"""
    day = START
    result = _run(
        period_end=day,
        segments=[
            _segment(
                3,
                day,
                day,
                [
                    _item(1, '基础单价', CalcStage.per_order.value, {'类型': '固定金额', '金额': 10}),
                    _item(
                        2,
                        '保底补足',
                        CalcStage.period.value,
                        {'类型': '表达式', '表达式': '最大值(0, 100 - 本期已计金额)'},
                    ),
                ],
            )
        ],
        orders=[_order(day, 1), _order(day, 2)],
        adjustments=[
            _adjustment(11, '40.00', SubjectDirection.bonus.value, day),
            _adjustment(12, '-50.00', SubjectDirection.penalty.value, day),
        ],
    )
    guarantee = next(row for row in result.details if row.name == '保底补足')
    assert guarantee.amount == D('80.00')
    assert Decimal(str(guarantee.calc_trace['变量']['本期已计金额'])) == D('20.00')
    assert result.per_order_total == D('20.00')
    assert result.bonus_total == D('40.00')
    assert result.penalty_total == D('-50.00')
    assert result.gross == D('90.00')
    assert result.gross < D('100.00')
    assert '不含手工奖惩' in FIELD_MAP['本期已计金额'].description
