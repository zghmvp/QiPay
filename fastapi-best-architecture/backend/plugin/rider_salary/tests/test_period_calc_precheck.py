"""周期算薪预检与严格硬失败口径对齐。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from backend.plugin.rider_salary.enums import CalcStage, OrderStatus
from backend.plugin.rider_salary.schema.period import (
    CalcPrecheckResult,
    CalculatePeriodResult,
    CalculateRiderFailure,
)
from backend.plugin.rider_salary.service.calc_service import (
    CalcInput,
    collect_hard_fail_findings,
    missing_delivery_message,
    no_plan_with_orders_message,
    run_calc_pipeline,
)
from backend.plugin.rider_salary.tests.test_calc_pipeline import Segment, _item, _order


def test_collect_hard_fail_matches_pipeline_no_plan() -> None:
    import pytest

    from backend.common.exception import errors

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
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates={start, date(2026, 9, 2), end},
        site_order_dates={start, date(2026, 9, 2)},
        persist_advance=False,
    )
    findings = collect_hard_fail_findings(data)
    assert len(findings) == 1
    code, messages = findings[0]
    assert code == 'no_plan_with_orders'
    assert '2026-09-02' in messages[0]
    assert messages[0] == no_plan_with_orders_message(['2026-09-02（2 单）'])
    with pytest.raises(errors.RequestError, match='无生效方案') as exc_info:
        run_calc_pipeline(data)
    assert exc_info.value.msg == messages[0]


def test_collect_hard_fail_matches_pipeline_missing_delivery() -> None:
    import pytest

    from backend.common.exception import errors

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
    order = _order(1, 'MISS-1', day)
    order.deliver_time = None
    data = CalcInput(
        rider_id=1,
        site_id=1,
        period_start=day,
        period_end=day,
        hire_date=day,
        leave_date=None,
        employ_type='part_time',
        segments=[Segment(plan_version_id=1, start_date=day, end_date=day, items=[item])],
        orders=[order],
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates={day},
        site_order_dates={day},
        persist_advance=False,
    )
    findings = collect_hard_fail_findings(data)
    assert findings[0][0] == 'missing_delivery'
    expected = missing_delivery_message('MISS-1', day)
    assert findings[0][1][0] == expected
    with pytest.raises(errors.RequestError) as exc_info:
        run_calc_pipeline(data)
    assert exc_info.value.msg == expected


def test_calculate_period_result_failed_schema() -> None:
    payload = CalculatePeriodResult(
        calculated=1,
        warnings=[],
        failed=[
            CalculateRiderFailure(
                rider_id=9, job_no='D1', errors=['算薪中止：以下日期有订单但无生效方案：2026-09-02（1 单）']
            ),
        ],
        queued=False,
    )
    assert payload.failed[0].rider_id == 9
    assert '无生效方案' in payload.failed[0].errors[0]


def test_calc_precheck_result_schema_shape() -> None:
    result = CalcPrecheckResult(
        period_id=12,
        can_run=False,
        blockers=[],
        warnings=[],
        eligible_rider_count=0,
        stale_count=2,
    )
    dumped = result.model_dump()
    assert dumped['period_id'] == 12
    assert dumped['can_run'] is False
    assert dumped['stale_count'] == 2
    assert dumped['blockers'] == []


def test_order_status_completed_constant() -> None:
    """夹具守卫：预检与 pipeline 共用 completed 判定。"""
    assert OrderStatus.completed.value == 'completed'
    row = SimpleNamespace(status=OrderStatus.completed.value)
    assert row.status == 'completed'
