"""下一波抛光 Must：旁路失败持久化 / 锁账硬拦 / live 无方案 / 天气下线。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from backend.plugin.rider_salary.engine.compiler import compile_condition, compile_formula, validate_item
from backend.plugin.rider_salary.engine.fields import RETIRED_FIELDS, retired_field_message
from backend.plugin.rider_salary.enums import BindingType, CalcStage, DayStatus, RecalcJobStatus
from backend.plugin.rider_salary.schema.period import CalculateRiderFailure, GetPeriodWithPayrolls
from backend.plugin.rider_salary.schema.recalc_job import GetRecalcJobDetail
from backend.plugin.rider_salary.service.calc_service import (
    CalcInput,
    collect_hard_fail_findings,
    collect_never_calculated_finding,
    lock_hard_fail_message,
    missing_delivery_message,
    never_calculated_message,
    no_plan_with_orders_message,
    persist_last_calc_failures,
    serialize_calc_failures,
)
from backend.plugin.rider_salary.service.calendar_service import count_live_no_plan_days, resolve_day_status
from backend.plugin.rider_salary.service.period_service import import_gap_deeplink
from backend.plugin.rider_salary.service.recalc_job_service import finish_recalc_job_state
from backend.plugin.rider_salary.service.rider_service import Segment, resolve_effective_plans_from_bindings
from backend.plugin.rider_salary.tests.test_calc_pipeline import Segment as CalcSegment
from backend.plugin.rider_salary.tests.test_calc_pipeline import _item, _order
from backend.plugin.rider_salary.tests.test_master_data import _binding


def test_serialize_and_persist_last_calc_failures() -> None:
    rows = [
        {'rider_id': 9, 'job_no': 'FIX_C17_R1', 'errors': ['算薪中止：以下日期有订单但无生效方案：2026-09-15（1 单）']},
    ]
    dumped = serialize_calc_failures(rows)
    assert dumped[0]['job_no'] == 'FIX_C17_R1'
    assert '无生效方案' in dumped[0]['errors'][0]
    period = SimpleNamespace(last_calc_failures=None)
    persist_last_calc_failures(period, rows)  # type: ignore[arg-type]
    assert period.last_calc_failures == dumped
    persist_last_calc_failures(period, [])  # type: ignore[arg-type]
    assert period.last_calc_failures == []


def test_period_detail_schema_keeps_last_calc_failures() -> None:
    payload = GetPeriodWithPayrolls.model_validate({
        'site_id': 1,
        'rider_id': 0,
        'cycle_type': 'month',
        'start_date': date(2026, 9, 1),
        'end_date': date(2026, 9, 30),
        'status': 'open',
        'id': 12,
        'last_calc_failures': [
            CalculateRiderFailure(rider_id=9, job_no='D1', errors=['字段「是否恶劣天气」已下线，不可用于方案项']),
        ],
    })
    assert payload.last_calc_failures[0].job_no == 'D1'
    assert '是否恶劣天气' in payload.last_calc_failures[0].errors[0]


def test_recalc_job_must_not_finish_complete_when_failed() -> None:
    status, message = finish_recalc_job_state(
        done_periods=2,
        failed_rows=[{'rider_id': 1, 'job_no': 'A', 'errors': ['无生效方案']}],
    )
    assert status == RecalcJobStatus.failed.value
    assert '部分失败' in message
    assert '失败 1 人' in message
    assert '完成：' not in message
    ok_status, ok_msg = finish_recalc_job_state(done_periods=2, failed_rows=[])
    assert ok_status == RecalcJobStatus.done.value
    assert ok_msg.startswith('完成：')


def test_recalc_job_detail_exposes_failed_rider_count() -> None:
    row = GetRecalcJobDetail.model_validate({
        'id': 8,
        'site_id': 13,
        'source': 'stale_batch',
        'status': 'failed',
        'message': '部分失败：已重算 1 个周期，失败 1 人',
        'total_periods': 1,
        'done_periods': 1,
        'rider_count': 2,
        'operator_id': 1,
        'created_time': '2026-09-17T00:00:00+08:00',
        'payload': {
            'failed': [{'rider_id': 9, 'job_no': 'FIX_C17_R1', 'errors': ['无生效方案'], 'period_id': 12}],
            'failed_rider_count': 1,
            'failed_period_ids': [12],
        },
    })
    assert row.failed_rider_count == 1
    assert row.status == RecalcJobStatus.failed.value
    assert '部分失败' in (row.message or '')
    assert '完成：' not in (row.message or '')


def test_lock_uses_same_hard_fail_copy_as_calc() -> None:
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
    data = CalcInput(
        rider_id=1,
        site_id=13,
        period_start=start,
        period_end=date(2026, 9, 3),
        hire_date=start,
        leave_date=None,
        employ_type='part_time',
        segments=[CalcSegment(plan_version_id=1, start_date=start, end_date=start, items=[item])],
        orders=[_order(1, 'P-1', start), _order(2, 'P-2', date(2026, 9, 2))],
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates={start, date(2026, 9, 2)},
        site_order_dates={start, date(2026, 9, 2)},
        persist_advance=False,
    )
    findings = collect_hard_fail_findings(data)
    assert findings[0][0] == 'no_plan_with_orders'
    same = no_plan_with_orders_message(['2026-09-02（1 单）'])
    assert findings[0][1][0] == same
    wrapped = lock_hard_fail_message([same])
    assert wrapped.startswith('锁账中止')
    assert same in wrapped
    miss = missing_delivery_message('MISS-1', start)
    assert '送达时间为空' in miss


def test_lock_never_calculated_and_hard_fail_copy() -> None:
    msg = never_calculated_message('FIX_C17_R1', ['2026-09-15（ORD-1）'])
    assert 'FIX_C17_R1' in msg
    assert '从未成功落库' in msg
    assert '2026-09-15' in msg
    finding = collect_never_calculated_finding(
        job_no='A001',
        completed_orders=[SimpleNamespace(order_no='X1', biz_date=date(2026, 9, 2))],
        has_success_payroll=False,
        already_hard_failed=False,
    )
    assert finding is not None
    assert finding[0] == 'never_calculated'
    assert (
        collect_never_calculated_finding(
            job_no='A001',
            completed_orders=[SimpleNamespace(order_no='X1', biz_date=date(2026, 9, 2))],
            has_success_payroll=True,
            already_hard_failed=False,
        )
        is None
    )
    assert (
        collect_never_calculated_finding(
            job_no='A001',
            completed_orders=[],
            has_success_payroll=False,
            already_hard_failed=False,
        )
        is None
    )
    lock_msg = lock_hard_fail_message([msg])
    assert lock_msg.startswith('锁账中止')
    assert '算薪页' in lock_msg


def test_import_gap_deeplink_is_order_window_not_calendar() -> None:
    link = import_gap_deeplink(13, [date(2026, 9, 10), date(2026, 9, 12)])
    assert link.path == '/rider-salary/order'
    assert link.query == {'site_id': '13', 'date_from': '2026-09-10', 'date_to': '2026-09-12'}
    assert 'calendar' not in link.path


def test_dashboard_no_plan_live_same_predicate_as_calendar() -> None:
    bindings = [
        _binding(BindingType.default, date(2026, 9, 1), date(2026, 9, 14), 11, pk=1),
    ]
    segments = resolve_effective_plans_from_bindings(bindings, date(2026, 9, 1), date(2026, 9, 30))
    completed = {
        date(2026, 9, 15): 2,
        date(2026, 9, 16): 1,
        date(2026, 9, 10): 3,
    }
    assert count_live_no_plan_days(segments, completed, date(2026, 9, 1), date(2026, 9, 30)) == 2
    empty_cache_days = {date(2026, 9, 15): 1}
    no_bind = resolve_effective_plans_from_bindings([], date(2026, 9, 1), date(2026, 9, 30))
    assert count_live_no_plan_days(no_bind, empty_cache_days, date(2026, 9, 1), date(2026, 9, 30)) == 1
    assert (
        resolve_day_status(has_plan=False, order_count=1, valid_order_count=1, imported=True) == DayStatus.no_plan.value
    )
    assert (
        count_live_no_plan_days(
            [Segment(plan_version_id=None, start=date(2026, 9, 1), end=date(2026, 9, 30))],
            {},
            date(2026, 9, 1),
            date(2026, 9, 30),
        )
        == 0
    )


def test_retired_weather_fields_hard_fail_with_item_name() -> None:
    assert '是否恶劣天气' in RETIRED_FIELDS
    assert '是否高温' in RETIRED_FIELDS
    assert '是否大促' in RETIRED_FIELDS
    with pytest.raises(Exception, match='是否恶劣天气') as exc_info:
        compile_condition({'字段': '是否恶劣天气', '运算符': '=', '值': True}, CalcStage.daily.value)
    assert '已下线' in str(exc_info.value)
    result = validate_item(
        CalcStage.daily.value,
        {'字段': '是否高温', '运算符': '=', '值': True},
        {'类型': '固定金额', '金额': 5},
    )
    assert result.ok is False
    assert any('是否高温' in msg and '已下线' in msg for msg in result.errors)
    expr_result = validate_item(
        CalcStage.daily.value,
        {},
        {'类型': '表达式', '表达式': '是否大促 * 1'},
    )
    assert expr_result.ok is False
    assert any(retired_field_message('是否大促') in msg or '是否大促' in msg for msg in expr_result.errors)


def test_holiday_weekend_fields_still_compile() -> None:
    cond = compile_condition({'字段': '是否节假日', '运算符': '=', '值': True}, CalcStage.daily.value)
    assert '是否节假日' in cond
    weekend = compile_condition({'字段': '是否周末', '运算符': '=', '值': True}, CalcStage.daily.value)
    assert '是否周末' in weekend
    formula = compile_formula({'类型': '固定金额', '金额': 4}, CalcStage.daily.value)
    assert formula


def test_weather_subject_codes_disabled_in_init_sql() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / 'sql'
    codes = ('BONUS_BAD_WEATHER', 'BONUS_HIGH_TEMP', 'BONUS_PROMO')
    for path in root.glob('*/*.sql'):
        if path.parent.name == 'patch':
            continue
        if 'destroy' in path.name:
            continue
        text = path.read_text(encoding='utf-8')
        for code in codes:
            assert code in text
            # 种子行必须是 disable，不能再 enable
            line = next(row for row in text.splitlines() if f"'{code}'" in row)
            assert "'disable'" in line
            assert '已下线' in line
