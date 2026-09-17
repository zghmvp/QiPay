"""FIX_C17 / 绑定感知分段试算金标（DB-free）。"""

from __future__ import annotations

import json

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from backend.plugin.rider_salary.engine.compiler import compile_condition, compile_formula
from backend.plugin.rider_salary.engine.segments import PlanItemView, Segment
from backend.plugin.rider_salary.enums import CalcStage, OrderStatus, SubjectDirection, TrialMode
from backend.plugin.rider_salary.service.calc_service import CalcInput, run_calc_pipeline
from backend.plugin.rider_salary.service.plan_service import build_trial_result
from backend.utils.timezone import timezone

FIXTURE_DIR = Path(__file__).parent / 'fixtures' / 'trial-binding-segments'
EXPECTED = json.loads((FIXTURE_DIR / 'expected.json').read_text(encoding='utf-8'))

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


def _orders_for_range(start: date, end: date, per_day: int, oid_start: int) -> list[SimpleNamespace]:
    rows: list[SimpleNamespace] = []
    oid = oid_start
    day = start
    while day <= end:
        for _i in range(per_day):
            oid += 1
            rows.append(
                SimpleNamespace(
                    id=oid,
                    order_no=f'C17-{oid}',
                    site_id=1,
                    rider_id=1,
                    biz_date=day,
                    distance_km=D('3.00'),
                    weight_jin=D('4.00'),
                    order_time=_dt(day, 10),
                    deliver_time=_dt(day, 10),
                    status=OrderStatus.completed.value,
                    amount=D('20.00'),
                )
            )
        day += timedelta(days=1)
    return rows


def _segment(plan_version_id: int, start: date, end: date, items: list[PlanItemView]) -> Segment:
    return Segment(
        plan_version_id=plan_version_id,
        start_date=start,
        end_date=end,
        plan_version=SimpleNamespace(id=plan_version_id, version_no=1, status='active'),
        items=items,
    )


def _build_rebind_input() -> CalcInput:
    """9/1-14 段A 100单；9/15-17 无方案 50单；9/18-30 段B 100单 → valid=250 plan=200。"""
    # 14 天 × ~7 单 ≈ 100；取整：前 10 天 7 单=70，后 4 天 7.5 → 用 100 固定：每天约 7.14
    # 简化：段 A 共 100 单均摊到 14 天；无方案 50 单到 3 天；段 B 100 单到 13 天
    orders: list[SimpleNamespace] = []
    orders += _orders_for_range(date(2026, 9, 1), date(2026, 9, 10), 7, 0)  # 70
    orders += _orders_for_range(date(2026, 9, 11), date(2026, 9, 14), 7, 70)  # 28 → 98，再补 2
    orders += _orders_for_range(date(2026, 9, 14), date(2026, 9, 14), 2, 98)  # +2 on 14th overlapping ok
    # rewrite A to exact 100: clear and rebuild
    orders = []
    # 段 A：100 单
    for i in range(100):
        day = date(2026, 9, 1) + timedelta(days=i % 14)
        orders.append(
            SimpleNamespace(
                id=i + 1,
                order_no=f'A-{i + 1}',
                site_id=1,
                rider_id=1,
                biz_date=day,
                distance_km=D('3.00'),
                weight_jin=D('4.00'),
                order_time=_dt(day),
                deliver_time=_dt(day),
                status=OrderStatus.completed.value,
                amount=D('20.00'),
            )
        )
    # 无方案三日：50 单
    for i in range(50):
        day = date(2026, 9, 15) + timedelta(days=i % 3)
        orders.append(
            SimpleNamespace(
                id=200 + i,
                order_no=f'G-{i + 1}',
                site_id=1,
                rider_id=1,
                biz_date=day,
                distance_km=D('3.00'),
                weight_jin=D('4.00'),
                order_time=_dt(day),
                deliver_time=_dt(day),
                status=OrderStatus.completed.value,
                amount=D('20.00'),
            )
        )
    # 段 B：100 单
    for i in range(100):
        day = date(2026, 9, 18) + timedelta(days=i % 13)
        orders.append(
            SimpleNamespace(
                id=300 + i,
                order_no=f'B-{i + 1}',
                site_id=1,
                rider_id=1,
                biz_date=day,
                distance_km=D('3.00'),
                weight_jin=D('4.00'),
                order_time=_dt(day),
                deliver_time=_dt(day),
                status=OrderStatus.completed.value,
                amount=D('20.00'),
            )
        )

    ladder = {
        '类型': '阶梯',
        '字段': '方案期内单量',
        '模式': '全量落档',
        '计价': '按单价',
        '档位': [
            {'下限': 0, '上限': 200, '值': 5},
            {'下限': 200, '上限': 400, '值': 5.5},
            {'下限': 400, '上限': None, '值': 6},
        ],
    }
    items_a = [
        _item(
            pk=1,
            subject_id=1,
            name='基础单价',
            stage=CalcStage.per_order.value,
            sort_order=1,
            formula={'类型': '表达式', '表达式': '4'},
        )
    ]
    items_b = [
        _item(
            pk=2,
            subject_id=2,
            name='提成',
            stage=CalcStage.period.value,
            sort_order=1,
            formula=ladder,
        )
    ]
    covered = set()
    day = date(2026, 9, 1)
    while day <= date(2026, 9, 30):
        covered.add(day)
        day += timedelta(days=1)
    return CalcInput(
        rider_id=1,
        site_id=1,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        hire_date=date(2025, 1, 1),
        leave_date=None,
        employ_type='full_time',
        segments=[
            _segment(11, date(2026, 9, 1), date(2026, 9, 14), items_a),
            _segment(12, date(2026, 9, 18), date(2026, 9, 30), items_b),
        ],
        orders=orders,
        day_flags={},
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates=covered,
        site_order_dates=covered,
        persist_advance=False,
        period_id=1,
    )


def test_fix_c17_binding_segments_order_counts_diverge() -> None:
    expected = EXPECTED['expected']
    result = run_calc_pipeline(_build_rebind_input())
    assert result.valid_order_count == expected['valid_order_count']
    assert result.plan_order_count == expected['plan_order_count']
    assert result.valid_order_count != result.plan_order_count
    assert [row.plan_order_count for row in result.segment_order_counts] == expected['segment_order_counts']
    trial = build_trial_result(result, None, mode=TrialMode.binding_segments)
    assert trial.mode == TrialMode.binding_segments.value
    assert trial.summary.valid_order_count == 250
    assert trial.summary.plan_order_count == 200


def test_fix_c17_field_contrast_ladder() -> None:
    """同阶梯：周期有效单量 vs 方案期内单量（段 B）结果不同。"""
    expected = EXPECTED['expected']['field_contrast_FIX_C17']
    base = _build_rebind_input()
    # 仅段 B，用周期有效单量字段
    ladder_period = {
        '类型': '阶梯',
        '字段': '周期有效单量',
        '模式': '全量落档',
        '计价': '按单价',
        '档位': [{'下限': t['min'], '上限': t['max'], '值': t['price']} for t in expected['ladder']],
    }
    ladder_plan = {
        '类型': '阶梯',
        '字段': '方案期内单量',
        '模式': '全量落档',
        '计价': '按单价',
        '档位': [{'下限': t['min'], '上限': t['max'], '值': t['price']} for t in expected['ladder']],
    }
    items_period = [
        _item(
            pk=3,
            subject_id=3,
            name='提成-周期有效',
            stage=CalcStage.period.value,
            sort_order=1,
            formula=ladder_period,
        )
    ]
    items_plan = [
        _item(
            pk=4,
            subject_id=3,
            name='提成-方案期内',
            stage=CalcStage.period.value,
            sort_order=1,
            formula=ladder_plan,
        )
    ]
    # 整月单段时周期有效=方案期内；这里用完整多段 input 但只换 B 段公式
    data_period = CalcInput(**{
        **base.__dict__,
        'segments': [
            base.segments[0],
            _segment(12, date(2026, 9, 18), date(2026, 9, 30), items_period),
        ],
    })
    data_plan = CalcInput(**{
        **base.__dict__,
        'segments': [
            base.segments[0],
            _segment(12, date(2026, 9, 18), date(2026, 9, 30), items_plan),
        ],
    })
    r_period = run_calc_pipeline(data_period)
    r_plan = run_calc_pipeline(data_plan)
    amt_period = next(d.amount for d in r_period.details if d.name == '提成-周期有效')
    amt_plan = next(d.amount for d in r_plan.details if d.name == '提成-方案期内')
    assert amt_period == D(expected['period_valid_field_amount'])
    assert amt_plan == D(expected['plan_period_field_on_segment_b_amount'])
    assert amt_period != amt_plan


def test_fixture_expected_json_loads() -> None:
    assert EXPECTED['fixture'] == 'FIX_C17'
    assert EXPECTED['expected']['order_counts_diverge'] is True
