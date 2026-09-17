"""Cycle 2 案例金标（DB-free pipeline）：C03=8200 / C04=7800 / C05A=3500 / C17 2310 vs 100。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from backend.plugin.rider_salary.engine.compiler import compile_condition, compile_formula
from backend.plugin.rider_salary.engine.segments import PlanItemView, Segment
from backend.plugin.rider_salary.enums import CalcStage, OrderStatus, SubjectDirection
from backend.plugin.rider_salary.service.calc_service import CalcInput, run_calc_pipeline
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

TZ = timezone.tz_info
D = Decimal


def _item(*, pk: int, subject_id: int, name: str, stage: str, sort_order: int, formula: dict) -> PlanItemView:
    return PlanItemView(
        id=pk,
        subject_id=subject_id,
        name=name,
        stage=stage,
        sort_order=sort_order,
        condition_json=None,
        formula_json=formula,
        condition_expr=compile_condition(None, stage),
        formula_expr=compile_formula(formula, stage),
        enabled=True,
        direction=SubjectDirection.bonus.value,
        include_in_gross=True,
    )


def _dt(day: date, hour: int = 10) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=TZ)


def _orders(count: int, start: date) -> list[SimpleNamespace]:
    rows: list[SimpleNamespace] = []
    for i in range(count):
        day = start + timedelta(days=i % 30)
        rows.append(
            SimpleNamespace(
                id=i + 1,
                order_no=f'GOLD-{i + 1}',
                site_id=1,
                rider_id=1,
                biz_date=day,
                distance_km=D('3.00'),
                weight_jin=D('4.00'),
                order_time=_dt(day),
                deliver_time=_dt(day, 10),
                status=OrderStatus.completed.value,
                amount=D('20.00'),
            )
        )
    return rows


def _input(items: list[PlanItemView], orders: list[SimpleNamespace]) -> CalcInput:
    start = date(2026, 9, 1)
    end = date(2026, 9, 30)
    covered = {start + timedelta(days=i) for i in range(30)}
    return CalcInput(
        rider_id=1,
        site_id=1,
        period_start=start,
        period_end=end,
        hire_date=date(2025, 1, 1),
        leave_date=None,
        employ_type='full_time',
        segments=[
            Segment(plan_version_id=1, start_date=start, end_date=end, items=items),
        ],
        orders=orders,
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates=covered,
        site_order_dates=covered,
        persist_advance=False,
        period_id=1,
    )


C03_LADDER = {
    '类型': '阶梯',
    '字段': '周期有效单量',
    '模式': '全量落档',
    '计价': '按单价',
    '档位': [
        {'下限': 0, '上限': 400, '值': 4},
        {'下限': 400, '上限': 700, '值': 5},
        {'下限': 700, '上限': None, '值': 6},
    ],
}

C17_LADDER = {
    '类型': '阶梯',
    '字段': '周期有效单量',
    '模式': '全量落档',
    '计价': '按单价',
    '档位': [
        {'下限': 0, '上限': 300, '值': 5},
        {'下限': 300, '上限': 600, '值': 5.5},
        {'下限': 600, '上限': None, '值': 6},
    ],
}


def _c03_items(*, progressive: bool) -> list[PlanItemView]:
    ladder = dict(C03_LADDER)
    if progressive:
        ladder['模式'] = '分段累进'
    return [
        _item(
            pk=1,
            subject_id=94030,
            name='基础单价',
            stage=CalcStage.per_order.value,
            sort_order=10,
            formula={'类型': '固定金额', '金额': 3},
        ),
        _item(
            pk=2,
            subject_id=94031,
            name='底薪',
            stage=CalcStage.period.value,
            sort_order=20,
            formula={'类型': '表达式', '表达式': '3000 * 方案生效天数 / 周期天数'},
        ),
        _item(
            pk=3,
            subject_id=94033,
            name='提成',
            stage=CalcStage.period.value,
            sort_order=30,
            formula=ladder,
        ),
    ]


def test_fix_c03_gross_8200() -> None:
    result = run_calc_pipeline(_input(_c03_items(progressive=False), _orders(650, date(2026, 9, 1))))
    assert result.valid_order_count == 650
    assert result.per_order_total == D('1950.00')
    commission = next(row for row in result.details if row.name == '提成')
    salary = next(row for row in result.details if row.name == '底薪')
    assert salary.amount == D('3000.00')
    assert commission.amount == D('3250.00')
    assert result.gross == D('8200.00')


def test_fix_c04_gross_7800() -> None:
    result = run_calc_pipeline(_input(_c03_items(progressive=True), _orders(650, date(2026, 9, 1))))
    commission = next(row for row in result.details if row.name == '提成')
    assert commission.amount == D('2850.00')
    assert result.gross == D('7800.00')
    c03 = run_calc_pipeline(_input(_c03_items(progressive=False), _orders(650, date(2026, 9, 1))))
    assert c03.gross - result.gross == D('400.00')


def test_fix_c05a_gross_3500() -> None:
    items = [
        _item(
            pk=1,
            subject_id=1,
            name='提成',
            stage=CalcStage.per_order.value,
            sort_order=10,
            formula={'类型': '固定金额', '金额': 3.5},
        ),
        _item(
            pk=2,
            subject_id=2,
            name='周期加价',
            stage=CalcStage.period.value,
            sort_order=20,
            formula={'类型': '固定金额', '金额': 0},
        ),
        _item(
            pk=3,
            subject_id=3,
            name='保底补足',
            stage=CalcStage.period.value,
            sort_order=90,
            formula={'类型': '表达式', '表达式': '最大值(0, 3500 - 本期已计金额)'},
        ),
    ]
    result = run_calc_pipeline(_input(items, _orders(800, date(2026, 9, 1))))
    topup = next(row for row in result.details if row.name == '保底补足')
    assert result.per_order_total == D('2800.00')
    assert topup.amount == D('700.00')
    assert result.gross == D('3500.00')


def test_fix_c17_amount_fork_2310_vs_100() -> None:
    """同档 5/5.5/6：420 单全量落档 2310；段内 20 单方案期内=100。"""
    period_items = [
        _item(
            pk=1,
            subject_id=3,
            name='提成-周期有效',
            stage=CalcStage.period.value,
            sort_order=1,
            formula=C17_LADDER,
        )
    ]
    plan_items = [
        _item(
            pk=2,
            subject_id=3,
            name='提成-方案期内',
            stage=CalcStage.period.value,
            sort_order=1,
            formula={**C17_LADDER, '字段': '方案期内单量'},
        )
    ]
    r_period = run_calc_pipeline(_input(period_items, _orders(420, date(2026, 9, 1))))
    amt_period = next(d.amount for d in r_period.details if d.name == '提成-周期有效')
    assert amt_period == D('2310.00')

    start = date(2026, 9, 1)
    end = date(2026, 9, 30)
    covered = {start + timedelta(days=i) for i in range(30)}
    data_plan = CalcInput(
        rider_id=1,
        site_id=1,
        period_start=start,
        period_end=end,
        hire_date=date(2025, 1, 1),
        leave_date=None,
        employ_type='full_time',
        segments=[
            Segment(plan_version_id=1, start_date=start, end_date=date(2026, 9, 2), items=plan_items),
        ],
        orders=_orders(20, start),
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates=covered,
        site_order_dates=covered,
        persist_advance=False,
        period_id=1,
    )
    r_plan = run_calc_pipeline(data_plan)
    amt_plan = next(d.amount for d in r_plan.details if d.name == '提成-方案期内')
    assert amt_plan == D('100.00')
    assert amt_period != amt_plan
    assert q2(amt_period) != q2(amt_plan)
