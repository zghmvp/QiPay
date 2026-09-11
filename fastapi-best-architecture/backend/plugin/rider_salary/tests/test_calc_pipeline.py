from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from backend.plugin.rider_salary.engine.compiler import compile_condition, compile_formula
from backend.plugin.rider_salary.engine.segments import PlanItemView, Segment
from backend.plugin.rider_salary.enums import CalcStage, DayStatus, OrderStatus, SubjectDirection
from backend.plugin.rider_salary.service.calc_service import CalcInput, run_calc_pipeline
from backend.utils.timezone import timezone

TZ = timezone.tz_info
D = Decimal


def _item(
    *,
    pk: int,
    subject_id: int,
    name: str,
    stage: str,
    sort_order: int,
    condition: dict | None,
    formula: dict,
    direction: str = SubjectDirection.bonus.value,
    include_in_gross: bool = True,
) -> PlanItemView:
    return PlanItemView(
        id=pk,
        subject_id=subject_id,
        name=name,
        stage=stage,
        sort_order=sort_order,
        condition_json=condition,
        formula_json=formula,
        condition_expr=compile_condition(condition, stage),
        formula_expr=compile_formula(formula, stage),
        enabled=True,
        direction=direction,
        include_in_gross=include_in_gross,
    )


def _dt(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def _order(
    oid: int,
    no: str,
    day: date,
    *,
    status: str = OrderStatus.completed.value,
    night: bool = False,
    distance: float = 3.2,
) -> SimpleNamespace:
    if night:
        order_time = _dt(day, 21, 50)
        deliver_time = _dt(day, 22, 18)
    else:
        order_time = _dt(day, 10, 0)
        deliver_time = _dt(day, 10, 28)
    return SimpleNamespace(
        id=oid,
        order_no=no,
        site_id=1,
        rider_id=1,
        biz_date=day,
        distance_km=D(str(distance)),
        weight_jin=D('4.50'),
        order_time=order_time,
        deliver_time=deliver_time,
        status=status,
        amount=D('28.00'),
    )


def _segment_a() -> Segment:
    night_cond = {
        '逻辑': '且',
        '条件': [{'字段': '送达时刻', '运算符': '在时段内', '值': ['22:00', '06:00']}],
    }
    items = [
        _item(
            pk=1,
            subject_id=94030,
            name='基础单价',
            stage=CalcStage.per_order.value,
            sort_order=10,
            condition={},
            formula={'类型': '固定金额', '金额': 4},
        ),
        _item(
            pk=2,
            subject_id=94026,
            name='夜间补贴',
            stage=CalcStage.per_order.value,
            sort_order=20,
            condition=night_cond,
            formula={'类型': '固定金额', '金额': 2},
        ),
        _item(
            pk=3,
            subject_id=94031,
            name='底薪',
            stage=CalcStage.period.value,
            sort_order=30,
            condition={},
            formula={'类型': '表达式', '表达式': '2000 * 方案生效天数 / 周期天数'},
        ),
    ]
    return Segment(plan_version_id=12, start_date=date(2026, 9, 1), end_date=date(2026, 9, 14), items=items)


def _segment_b() -> Segment:
    formula = {
        '类型': '阶梯',
        '字段': '方案期内单量',
        '模式': '全量落档',
        '计价': '按单价',
        '档位': [
            {'下限': 0, '上限': 300, '值': 5},
            {'下限': 300, '上限': 600, '值': 5.5},
            {'下限': 600, '上限': None, '值': 6},
        ],
    }
    items = [
        _item(
            pk=4,
            subject_id=94033,
            name='提成',
            stage=CalcStage.period.value,
            sort_order=10,
            condition={},
            formula=formula,
        )
    ]
    return Segment(plan_version_id=15, start_date=date(2026, 9, 15), end_date=date(2026, 9, 30), items=items)


def _build_orders() -> list[SimpleNamespace]:
    orders: list[SimpleNamespace] = []
    oid = 1
    a_days = [
        date(2026, 9, 1) + timedelta(days=i)
        for i in range(14)
        if (date(2026, 9, 1) + timedelta(days=i)) != date(2026, 9, 3)
    ]
    b_days = [
        date(2026, 9, 15) + timedelta(days=i)
        for i in range(16)
        if (date(2026, 9, 15) + timedelta(days=i)) != date(2026, 9, 17)
    ]
    night_left = 18
    remaining = 280
    for index, day in enumerate(a_days):
        days_left = len(a_days) - index
        take = remaining // days_left
        remaining -= take
        for _n in range(take):
            night = night_left > 0
            if night:
                night_left -= 1
            orders.append(_order(oid, f'A-{oid}', day, night=night, distance=7.2 if night else 3.2))
            oid += 1
    for _ in range(12):
        orders.append(_order(oid, f'AC-{oid}', date(2026, 9, 1), status=OrderStatus.cancelled.value))
        oid += 1
    remaining = 420
    for index, day in enumerate(b_days):
        days_left = len(b_days) - index
        take = remaining // days_left
        remaining -= take
        for _n in range(take):
            orders.append(_order(oid, f'B-{oid}', day, distance=4.0))
            oid += 1
    for _ in range(23):
        orders.append(_order(oid, f'BC-{oid}', date(2026, 9, 15), status=OrderStatus.cancelled.value))
        oid += 1
    return orders


def _adjustments() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=1,
            subject_id=94017,
            amount=D('200.00'),
            signed_amount=D('200.00'),
            include_in_gross=True,
            direction=SubjectDirection.bonus.value,
            biz_date=date(2026, 9, 1),
            subject=SimpleNamespace(name='全勤奖', direction='bonus', include_in_gross=True),
        ),
        SimpleNamespace(
            id=2,
            subject_id=94003,
            amount=D('50.00'),
            signed_amount=D('-50.00'),
            include_in_gross=True,
            direction=SubjectDirection.penalty.value,
            biz_date=date(2026, 9, 8),
            subject=SimpleNamespace(name='超时', direction='penalty', include_in_gross=True),
        ),
        SimpleNamespace(
            id=3,
            subject_id=94019,
            amount=D('80.00'),
            signed_amount=D('80.00'),
            include_in_gross=True,
            direction=SubjectDirection.bonus.value,
            biz_date=date(2026, 9, 20),
            subject=SimpleNamespace(name='好评奖', direction='bonus', include_in_gross=True),
        ),
        SimpleNamespace(
            id=4,
            subject_id=94015,
            amount=D('120.00'),
            signed_amount=D('-120.00'),
            include_in_gross=False,
            direction=SubjectDirection.penalty.value,
            biz_date=date(2026, 9, 30),
            subject=SimpleNamespace(name='保险费代扣', direction='penalty', include_in_gross=False),
        ),
    ]


def test_cross_segment_month_example() -> None:
    orders = _build_orders()
    covered = set()
    day = date(2026, 9, 1)
    while day <= date(2026, 9, 30):
        covered.add(day)
        day += timedelta(days=1)
    data = CalcInput(
        rider_id=1,
        site_id=1,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        hire_date=date(2025, 3, 1),
        leave_date=None,
        employ_type='full_time',
        segments=[_segment_a(), _segment_b()],
        orders=orders,
        day_flags={},
        employ_history=[],
        adjustments=_adjustments(),
        advances=[
            SimpleNamespace(
                id=9,
                amount=D('800.00'),
                remaining_amount=D('800.00'),
                deducted_amount=D('0.00'),
                deduct_status='none',
                paid_time=_dt(date(2026, 9, 7), 12, 0),
            )
        ],
        covered_dates=covered,
        site_order_dates=covered,
        persist_advance=True,
        period_id=1,
    )
    result = run_calc_pipeline(data)
    assert result.order_count == 735
    assert result.valid_order_count == 700
    assert result.per_order_total == D('1156.00')
    assert result.daily_total == D('0.00')
    assert result.period_total == D('3243.33')
    assert result.bonus_total == D('280.00')
    assert result.penalty_total == D('-50.00')
    assert result.gross == D('4629.33')
    assert result.deduction_total == D('120.00')
    assert result.advance_deduction == D('800.00')
    assert result.net == D('3709.33')
    assert result.plan_version_ids == [12, 15]
    night_hits = [row for row in result.details if row.name == '夜间补贴' and row.amount == D('2.00')]
    assert len(night_hits) == 18
    base_hits = [row for row in result.details if row.name == '基础单价']
    assert len(base_hits) == 280
    salary = next(row for row in result.details if row.name == '底薪')
    assert salary.amount == D('933.33')
    assert salary.calc_trace['变量']['方案生效天数'] == 14
    assert salary.calc_trace['变量']['周期天数'] == 30
    commission = next(row for row in result.details if row.name == '提成')
    assert commission.amount == D('2310.00')
    assert commission.calc_trace['变量']['方案期内单量'] == 420
    sep3 = next(row for row in result.dailies if row.biz_date == date(2026, 9, 3))
    assert sep3.day_status == DayStatus.no_orders.value
    assert data.advances[0].remaining_amount == D('0.00')


def test_night_surcharge_shanghai_2305_hits_1300_misses() -> None:
    """清单 #2：流水线层夜间补贴，23:05 命中、13:00 不命中（含 UTC 存盘）。"""
    from datetime import timezone as dt_timezone

    night_cond = {
        '逻辑': '且',
        '条件': [{'字段': '送达时刻', '运算符': '在时段内', '值': ['22:00', '06:00']}],
    }
    items = [
        _item(
            pk=1,
            subject_id=1,
            name='基础单价',
            stage=CalcStage.per_order.value,
            sort_order=10,
            condition={},
            formula={'类型': '固定金额', '金额': 4},
        ),
        _item(
            pk=2,
            subject_id=2,
            name='夜间补贴',
            stage=CalcStage.per_order.value,
            sort_order=20,
            condition=night_cond,
            formula={'类型': '固定金额', '金额': 2},
        ),
    ]
    day = date(2026, 9, 1)

    def _one(oid: int, no: str, order_time: datetime, deliver_time: datetime) -> SimpleNamespace:
        return SimpleNamespace(
            id=oid,
            order_no=no,
            site_id=1,
            rider_id=1,
            biz_date=day,
            distance_km=D('3.20'),
            weight_jin=D('4.50'),
            order_time=order_time,
            deliver_time=deliver_time,
            status=OrderStatus.completed.value,
            amount=D('28.00'),
        )

    utc = dt_timezone.utc
    orders = [
        _one(1, 'N-2305', _dt(day, 22, 30), datetime(2026, 9, 1, 23, 5, tzinfo=TZ)),
        _one(2, 'N-UTC', datetime(2026, 9, 1, 14, 30, tzinfo=utc), datetime(2026, 9, 1, 15, 5, tzinfo=utc)),
        _one(3, 'D-1300', _dt(day, 12, 30), datetime(2026, 9, 1, 13, 0, tzinfo=TZ)),
        _one(4, 'D-UTC', datetime(2026, 9, 1, 4, 30, tzinfo=utc), datetime(2026, 9, 1, 5, 0, tzinfo=utc)),
    ]
    data = CalcInput(
        rider_id=1,
        site_id=1,
        period_start=day,
        period_end=day,
        hire_date=day,
        leave_date=None,
        employ_type='part_time',
        segments=[Segment(plan_version_id=1, start_date=day, end_date=day, items=items)],
        orders=orders,
        day_flags={},
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates={day},
        site_order_dates={day},
        persist_advance=False,
    )
    result = run_calc_pipeline(data)
    night_by_order = {
        row.order_id: row.amount for row in result.details if row.name == '夜间补贴' and row.amount == D('2.00')
    }
    assert set(night_by_order) == {1, 2}
    assert 3 not in night_by_order
    assert 4 not in night_by_order
    assert result.per_order_total == D('20.00')


def test_trial_does_not_deduct_advance() -> None:
    item = _item(
        pk=1,
        subject_id=1,
        name='基础单价',
        stage=CalcStage.per_order.value,
        sort_order=10,
        condition={},
        formula={'类型': '固定金额', '金额': 4},
    )
    day = date(2026, 9, 1)
    orders = [_order(1, 'X-1', day)]
    data = CalcInput(
        rider_id=1,
        site_id=1,
        period_start=day,
        period_end=day,
        hire_date=day,
        leave_date=None,
        employ_type='part_time',
        segments=[Segment(plan_version_id=1, start_date=day, end_date=day, items=[item])],
        orders=orders,
        day_flags={},
        employ_history=[],
        adjustments=[],
        advances=[
            SimpleNamespace(
                id=1,
                amount=D('100.00'),
                remaining_amount=D('100.00'),
                deducted_amount=D('0.00'),
                deduct_status='none',
                paid_time=_dt(day, 8, 0),
            )
        ],
        covered_dates={day},
        site_order_dates={day},
        persist_advance=False,
    )
    result = run_calc_pipeline(data)
    assert result.advance_deduction == D('0.00')
    assert result.advance_deductible == D('4.00')
    assert data.advances[0].remaining_amount == D('100.00')


def test_no_plan_day_warning() -> None:
    item = _item(
        pk=1,
        subject_id=1,
        name='基础单价',
        stage=CalcStage.per_order.value,
        sort_order=10,
        condition={},
        formula={'类型': '固定金额', '金额': 4},
    )
    start = date(2026, 9, 1)
    end = date(2026, 9, 3)
    orders = [
        _order(1, 'P-1', start),
        _order(2, 'P-2', date(2026, 9, 2)),
        _order(3, 'P-3', date(2026, 9, 2)),
    ]
    data = CalcInput(
        rider_id=1,
        site_id=1,
        period_start=start,
        period_end=end,
        hire_date=start,
        leave_date=None,
        employ_type='part_time',
        segments=[Segment(plan_version_id=1, start_date=start, end_date=start, items=[item])],
        orders=orders,
        day_flags={},
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates={start, date(2026, 9, 2), end},
        site_order_dates={start, date(2026, 9, 2)},
        persist_advance=False,
    )
    result = run_calc_pipeline(data)
    assert any('2026-09-02 无生效方案' in msg and '2 单未计薪' in msg for msg in result.warnings)
    day2 = next(row for row in result.dailies if row.biz_date == date(2026, 9, 2))
    assert day2.day_status == DayStatus.no_plan.value
    assert result.per_order_total == D('4.00')
    assert result.valid_order_count == 3


def test_d2_parse_maps_to_calc_segments() -> None:
    from backend.plugin.rider_salary.engine.segments import segments_from_d2
    from backend.plugin.rider_salary.enums import BindingType
    from backend.plugin.rider_salary.service.rider_service import (
        BindingView,
        resolve_effective_plans_from_bindings,
    )

    bindings = [
        BindingView(
            binding_type=BindingType.default.value,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 10),
            plan_version_id=12,
            id=1,
        ),
        BindingView(
            binding_type=BindingType.override.value,
            start_date=date(2026, 9, 15),
            end_date=date(2026, 9, 20),
            plan_version_id=15,
            id=2,
        ),
    ]
    d2 = resolve_effective_plans_from_bindings(bindings, date(2026, 9, 1), date(2026, 9, 20))
    assert any(item.plan_version_id is None for item in d2)
    mapped = segments_from_d2(d2)
    assert [(item.plan_version_id, item.start_date, item.end_date) for item in mapped] == [
        (12, date(2026, 9, 1), date(2026, 9, 10)),
        (15, date(2026, 9, 15), date(2026, 9, 20)),
    ]


def test_guarantee_and_accrued() -> None:
    items = [
        _item(
            pk=1,
            subject_id=1,
            name='提成',
            stage=CalcStage.per_order.value,
            sort_order=10,
            condition={},
            formula={'类型': '固定金额', '金额': 3.5},
        ),
        _item(
            pk=2,
            subject_id=2,
            name='保底补足',
            stage=CalcStage.period.value,
            sort_order=90,
            condition={},
            formula={'类型': '表达式', '表达式': '最大值(0, 3500 - 本期已计金额)'},
        ),
    ]
    start = date(2026, 9, 1)
    end = date(2026, 9, 30)
    orders = [_order(i, f'G-{i}', start) for i in range(800)]
    data = CalcInput(
        rider_id=1,
        site_id=1,
        period_start=start,
        period_end=end,
        hire_date=start,
        leave_date=None,
        employ_type='full_time',
        segments=[Segment(plan_version_id=1, start_date=start, end_date=end, items=items)],
        orders=orders,
        day_flags={},
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates={start},
        site_order_dates={start},
        persist_advance=False,
    )
    result = run_calc_pipeline(data)
    assert result.per_order_total == D('2800.00')
    guarantee = next(row for row in result.details if row.name == '保底补足')
    assert guarantee.amount == D('700.00')
    assert result.gross == D('3500.00')


def test_recalc_must_restore_advance_before_rededuct() -> None:
    """ARCH-1：draft 重算若不回滚 remaining，第二次抵扣为 0"""
    from backend.plugin.rider_salary.service.payroll_service import apply_advance_restore, compute_advance_deduction

    adv = SimpleNamespace(
        id=9,
        amount=D('800.00'),
        remaining_amount=D('800.00'),
        deducted_amount=D('0.00'),
        deduct_status='none',
        paid_time=_dt(date(2026, 9, 7), 12, 0),
    )
    first, lines = compute_advance_deduction([adv], D('4509.33'), persist=True)
    assert first == D('800.00')
    assert adv.remaining_amount == D('0.00')
    lost, _ = compute_advance_deduction([adv], D('4509.33'), persist=True)
    assert lost == D('0.00')
    apply_advance_restore(adv, lines[0].amount)
    assert adv.remaining_amount == D('800.00')
    second, _ = compute_advance_deduction([adv], D('4509.33'), persist=True)
    assert second == D('800.00')
    assert adv.remaining_amount == D('0.00')
