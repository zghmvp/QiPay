"""对抗循环 Cycle 4 后端：列表消费站月/status、attention 落地、过期未锁、启用闸门。"""

from __future__ import annotations

import inspect

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import anyio
import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.api.v1.order import get_orders_paginated
from backend.plugin.rider_salary.api.v1.period import get_periods_paginated
from backend.plugin.rider_salary.api.v1.rider import get_riders_paginated
from backend.plugin.rider_salary.crud.order import order_dao
from backend.plugin.rider_salary.crud.rider import rider_dao
from backend.plugin.rider_salary.crud.settle_period import settle_period_dao
from backend.plugin.rider_salary.enums import CalcStage, OrderStatus, PeriodStatus, TrialMode
from backend.plugin.rider_salary.schema.plan_item import GetPlanVersionDetail
from backend.plugin.rider_salary.schema.trial import TrialResult
from backend.plugin.rider_salary.service.calc_service import CalcInput, run_calc_pipeline
from backend.plugin.rider_salary.service.dashboard_service import DashboardService
from backend.plugin.rider_salary.service.order_service import resolve_order_date_window
from backend.plugin.rider_salary.service.plan_service import PlanService, build_trial_result
from backend.plugin.rider_salary.tests.test_calc_pipeline import Segment, _item, _order
from backend.plugin.rider_salary.utils.order_attention import (
    DUE_PERIODS_TITLE,
    LOCK_COUNTDOWN_HORIZON_DAYS,
    abnormal_orders_landing_url,
    due_period_sql_filters,
    due_periods_view_all_link,
    is_lock_due_period,
    lock_countdown_statuses,
    lock_due_countdown,
    lock_due_cutoff,
    order_attention_condition,
)
from backend.plugin.rider_salary.utils.plan_activate import (
    ACTIVATION_TRIAL_MODE_KEY,
    FULL_TRIAL_NOT_PAYROLL_MSG,
    PARTIAL_SEGMENT_FIXED_AMOUNT_MSG,
    assert_activate_trial_is_binding_aware,
    binding_trial_passed,
    has_fixed_period_amount,
    partial_segment_fixed_amount_warning,
    stamp_trial_for_activate,
)

D = Decimal
START = date(2026, 9, 1)
END = date(2026, 9, 30)
TODAY = date(2026, 9, 17)


def _input(*, orders: list, items: list, segments: list | None = None) -> CalcInput:
    segs = segments or [Segment(plan_version_id=1, start_date=START, end_date=END, items=items)]
    return CalcInput(
        rider_id=1,
        site_id=1,
        period_start=START,
        period_end=END,
        hire_date=START,
        leave_date=None,
        employ_type='full_time',
        segments=segs,
        orders=orders,
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates={START, END},
        site_order_dates={START},
        persist_advance=False,
        period_id=1,
    )


def _fixed_base_items(*, amount: int = 2000, version_item_id: int = 1) -> list:
    return [
        _item(
            pk=version_item_id,
            subject_id=1,
            name='底薪',
            stage=CalcStage.period.value,
            sort_order=10,
            condition={},
            formula={'类型': '固定金额', '金额': amount},
        )
    ]


def test_list_apis_consume_site_month_status() -> None:
    order_params = inspect.signature(get_orders_paginated).parameters
    assert 'site_id' in order_params
    assert 'month' in order_params
    assert 'attention' in order_params
    rider_params = inspect.signature(get_riders_paginated).parameters
    assert 'site_id' in rider_params
    assert 'status' in rider_params
    period_params = inspect.signature(get_periods_paginated).parameters
    assert 'site_id' in period_params
    assert 'month' in period_params
    assert 'status' in period_params
    assert 'lock_due' in period_params


def test_resolve_order_month_window() -> None:
    assert resolve_order_date_window(month='2026-09', date_from=None, date_to=None) == (START, END)
    assert resolve_order_date_window(month='2026-09', date_from=date(2026, 9, 10), date_to=None) == (
        date(2026, 9, 10),
        None,
    )
    assert resolve_order_date_window(month=None, date_from=None, date_to=None) == (None, None)
    with pytest.raises(errors.RequestError, match='YYYY-MM'):
        resolve_order_date_window(month='202609', date_from=None, date_to=None)


def test_rider_select_consumes_on_job_status() -> None:
    async def _run() -> str:
        stmt = await rider_dao.get_select(
            site_id=2,
            status='on_job',
            employ_type=None,
            keyword=None,
            site_ids={2},
        )
        return str(stmt.compile(compile_kwargs={'literal_binds': True}))

    sql = anyio.run(_run).lower()
    assert 'on_job' in sql
    assert '2' in sql


def test_period_select_consumes_site_month_and_lock_due() -> None:
    async def _run() -> str:
        stmt = await settle_period_dao.get_select(
            site_id=2,
            rider_id=None,
            status=None,
            month_start=START,
            month_end=END,
            site_ids={2},
            stale=None,
            lock_due=True,
        )
        return str(stmt.compile(compile_kwargs={'literal_binds': True}))

    sql = anyio.run(_run).lower()
    assert 'site_id' in sql
    assert PeriodStatus.open.value in sql
    assert PeriodStatus.reopened.value in sql
    assert 'end_date' in sql
    assert "'locked'" not in sql


def test_order_select_attention_and_month_window() -> None:
    async def _run() -> str:
        stmt = await order_dao.get_select(
            site_ids={2},
            site_id=2,
            rider_id=None,
            date_from=START,
            date_to=END,
            status='abnormal',
            order_no=None,
            import_batch_id=None,
            is_locked=None,
            attention=True,
        )
        return str(stmt.compile(compile_kwargs={'literal_binds': True}))

    sql = anyio.run(_run).lower()
    assert '2026-09-01' in sql
    assert '2026-09-30' in sql
    assert OrderStatus.abnormal.value in sql
    assert OrderStatus.refunded.value in sql
    assert OrderStatus.completed.value in sql
    compiled_cond = str(order_attention_condition().compile(compile_kwargs={'literal_binds': True})).lower()
    assert 'extract' in compiled_cond


def test_abnormal_landing_uses_attention_not_status_only() -> None:
    url = abnormal_orders_landing_url(site_id=3, start=START, end=END)
    assert 'attention=1' in url
    assert 'site_id=3' in url
    assert 'month=2026-09' in url
    assert 'date_from=2026-09-01' in url
    assert 'date_to=2026-09-30' in url
    assert 'status=abnormal' not in url
    row = abnormal_orders_landing_url(site_id=3, start=START, end=END, order_no='AB-1')
    assert 'order_no=AB-1' in row
    assert 'attention=1' in row


def test_due_periods_include_overdue_exclude_far() -> None:
    assert LOCK_COUNTDOWN_HORIZON_DAYS == 3
    assert lock_due_cutoff(TODAY) == date(2026, 9, 20)
    assert is_lock_due_period(status=PeriodStatus.open.value, end_date=date(2026, 9, 10), today=TODAY)
    assert is_lock_due_period(status=PeriodStatus.reopened.value, end_date=date(2026, 9, 19), today=TODAY)
    assert not is_lock_due_period(status=PeriodStatus.open.value, end_date=date(2026, 9, 27), today=TODAY)
    assert not is_lock_due_period(status=PeriodStatus.locked.value, end_date=date(2026, 9, 10), today=TODAY)
    overdue = lock_due_countdown(end_date=date(2026, 9, 10), today=TODAY)
    assert overdue['overdue'] is True
    assert overdue['overdue_days'] == 7
    assert overdue['countdown_text'] == '已过期未锁 7 天'
    upcoming = lock_due_countdown(end_date=date(2026, 9, 19), today=TODAY)
    assert upcoming['overdue'] is False
    assert upcoming['countdown_text'] == '剩余 2 天'
    assert DUE_PERIODS_TITLE == '锁账倒计时'
    view_all = due_periods_view_all_link(4)
    assert view_all == '/rider-salary/period?lock_due=1&site_id=4'
    assert 'status=open' not in view_all
    assert 'status=open' not in due_periods_view_all_link(None)
    assert PeriodStatus.open.value in lock_countdown_statuses()


def test_due_period_sql_filters_include_overdue_window() -> None:
    filters = due_period_sql_filters(TODAY)
    compiled = ' '.join(str(item.compile(compile_kwargs={'literal_binds': True})) for item in filters).lower()
    assert PeriodStatus.open.value in compiled
    assert PeriodStatus.reopened.value in compiled
    assert '2026-09-20' in compiled


def test_dashboard_due_and_abnormal_use_helpers() -> None:
    src = inspect.getsource(DashboardService._due_periods)
    assert 'due_period_sql_filters' in src
    assert 'due_periods_view_all_link' in src
    assert DUE_PERIODS_TITLE in src or 'DUE_PERIODS_TITLE' in src
    assert 'status=open' not in src
    abnormal_src = inspect.getsource(DashboardService._abnormal_orders)
    assert 'abnormal_orders_landing_url' in abnormal_src
    assert 'status=abnormal' not in abnormal_src


def test_activate_rejects_full_version_trial() -> None:
    items_hash = 'abc123'
    full = SimpleNamespace(
        trial_passed=True,
        trial_hash=items_hash,
        items_hash=items_hash,
        trial_snapshot={ACTIVATION_TRIAL_MODE_KEY: TrialMode.full_version.value},
    )
    with pytest.raises(errors.RequestError, match='整版') as exc:
        assert_activate_trial_is_binding_aware(full, items_hash)
    assert '出账' in exc.value.msg or '当前绑定' in exc.value.msg
    assert exc.value.msg == FULL_TRIAL_NOT_PAYROLL_MSG
    legacy = SimpleNamespace(trial_passed=True, trial_hash=items_hash, trial_snapshot={'gross': '2000'})
    with pytest.raises(errors.RequestError, match='整版'):
        assert_activate_trial_is_binding_aware(legacy, items_hash)


def test_activate_accepts_binding_trial_only() -> None:
    items_hash = 'bind-hash'
    version = SimpleNamespace(
        trial_passed=True,
        trial_hash=items_hash,
        trial_snapshot={ACTIVATION_TRIAL_MODE_KEY: TrialMode.binding_segments.value},
    )
    assert_activate_trial_is_binding_aware(version, items_hash)
    assert binding_trial_passed(version) is True
    none = SimpleNamespace(trial_passed=False, trial_hash=None, trial_snapshot=None)
    with pytest.raises(errors.RequestError, match='试算'):
        assert_activate_trial_is_binding_aware(none, items_hash)


def test_stamp_full_version_cannot_unlock_activate() -> None:
    version = SimpleNamespace(trial_passed=False, trial_hash=None, items_hash=None, trial_snapshot=None)
    stamp_trial_for_activate(
        version,
        mode=TrialMode.full_version,
        current_hash='h1',
        summary={'gross': '2000.00'},
    )
    assert version.trial_passed is True
    assert binding_trial_passed(version) is False
    with pytest.raises(errors.RequestError, match='整版'):
        assert_activate_trial_is_binding_aware(version, 'h1')
    stamp_trial_for_activate(
        version,
        mode=TrialMode.binding_segments,
        current_hash='h1',
        summary={'gross': '4000.00'},
    )
    assert binding_trial_passed(version) is True
    assert_activate_trial_is_binding_aware(version, 'h1')


def test_activate_source_uses_binding_gate() -> None:
    src = inspect.getsource(PlanService.activate)
    assert 'assert_activate_trial_is_binding_aware' in src
    trial_src = inspect.getsource(PlanService.trial)
    assert 'stamp_trial_for_activate' in trial_src


def test_version_schema_exposes_binding_trial_flag() -> None:
    payload = GetPlanVersionDetail.model_validate({
        'id': 1,
        'plan_id': 1,
        'version_no': 1,
        'status': 'draft',
        'mode_tag': 'custom',
        'is_used': False,
        'items_hash': 'h',
        'trial_hash': 'h',
        'trial_passed': True,
        'trial_snapshot': {ACTIVATION_TRIAL_MODE_KEY: TrialMode.full_version.value, 'gross': '2000'},
        'created_time': '2026-09-01T00:00:00+08:00',
    })
    assert payload.trial_mode == TrialMode.full_version.value
    assert payload.binding_trial_passed is False
    bound = payload.model_copy(update={'trial_snapshot': {ACTIVATION_TRIAL_MODE_KEY: TrialMode.binding_segments.value}})
    rebound = GetPlanVersionDetail.model_validate(bound.model_dump())
    assert rebound.binding_trial_passed is True


def test_cross_segment_fixed_base_2000_times_2_is_4000() -> None:
    items = _fixed_base_items()
    segs = [
        Segment(plan_version_id=1, start_date=START, end_date=date(2026, 9, 14), items=items),
        Segment(plan_version_id=2, start_date=date(2026, 9, 15), end_date=END, items=items),
    ]
    result = run_calc_pipeline(_input(orders=[_order(1, 'FIX-1', START)], items=items, segments=segs))
    salaries = [row for row in result.details if row.name == '底薪']
    assert len(salaries) == 2
    assert all(row.amount == D('2000.00') for row in salaries)
    assert sum((row.amount for row in salaries), D('0.00')) == D('4000.00')
    assert result.period_total == D('4000.00')
    built = build_trial_result(result, None, mode=TrialMode.binding_segments)
    assert built.matches_official_calculate is True
    assert built.summary.period_total == D('4000.00')
    full = build_trial_result(result, 'h', mode=TrialMode.full_version)
    assert full.matches_official_calculate is False


def test_full_version_single_segment_fixed_base_is_2000() -> None:
    items = _fixed_base_items()
    result = run_calc_pipeline(_input(orders=[_order(1, 'FULL-1', START)], items=items))
    salaries = [row for row in result.details if row.name == '底薪']
    assert len(salaries) == 1
    assert salaries[0].amount == D('2000.00')
    assert result.period_total == D('2000.00')


def test_prorated_base_933_regression() -> None:
    from backend.plugin.rider_salary.tests.test_calc_pipeline import test_cross_segment_month_example

    test_cross_segment_month_example()


def test_partial_segment_fixed_amount_warning() -> None:
    items = [{'stage': 'period', 'enabled': True, 'formula_json': {'类型': '固定金额', '金额': 2000}}]
    assert has_fixed_period_amount(items) is True
    segs = [SimpleNamespace(start_date=START, end_date=date(2026, 9, 14))]
    warn = partial_segment_fixed_amount_warning(items, START, END, segs)
    assert warn == PARTIAL_SEGMENT_FIXED_AMOUNT_MSG
    assert '全额' in warn
    expr_items = [
        {
            'stage': 'period',
            'enabled': True,
            'formula_json': {'类型': '表达式', '表达式': '2000 * 方案生效天数 / 周期天数'},
        }
    ]
    assert partial_segment_fixed_amount_warning(expr_items, START, END, segs) is None


def test_trial_result_full_version_not_official() -> None:
    result = TrialResult.model_validate({
        'passed': True,
        'mode': 'full_version',
        'mode_label': '整版试算',
        'matches_official_calculate': False,
        'summary': {
            'order_count': 1,
            'gross': '2000.00',
            'deduction_total': '0.00',
            'net': '2000.00',
            'per_order_total': '0.00',
            'daily_total': '0.00',
            'period_total': '2000.00',
            'manual_bonus': '0.00',
            'manual_penalty': '0.00',
        },
    })
    assert result.matches_official_calculate is False
