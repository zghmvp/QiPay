"""对抗循环 Cycle 1 后端 Must：缺送达筛 / 锁账硬失败优先 / 最近 recalc_job。"""

from __future__ import annotations

import inspect

from datetime import date
from types import SimpleNamespace

import anyio

from backend.plugin.rider_salary.api.v1.order import get_orders_paginated
from backend.plugin.rider_salary.api.v1.recalc_job import get_latest_recalc_job
from backend.plugin.rider_salary.crud.order import order_dao
from backend.plugin.rider_salary.crud.recalc_job import latest_recalc_job_select
from backend.plugin.rider_salary.enums import CalcStage, OrderStatus, RecalcJobSource
from backend.plugin.rider_salary.schema.period import CalculateRiderFailure
from backend.plugin.rider_salary.schema.recalc_job import GetLatestRecalcJobResult
from backend.plugin.rider_salary.service.calc_service import (
    CalcInput,
    calc_failure_deeplink,
    classify_calc_failure_code,
    collect_hard_fail_findings,
    collect_never_calculated_finding,
    lock_hard_fail_message,
    missing_delivery_message,
    missing_delivery_order_query,
    never_calculated_message,
    no_plan_with_orders_message,
    serialize_calc_failures,
)
from backend.plugin.rider_salary.service.period_service import (
    _blocker_deeplink,
    compose_lock_block_message,
    stale_lock_message,
)
from backend.plugin.rider_salary.tests.test_calc_pipeline import Segment, _item, _order
from backend.plugin.rider_salary.utils.order_attention import missing_delivery_condition


def test_orders_api_query_param_is_missing_delivery() -> None:
    params = inspect.signature(get_orders_paginated).parameters
    assert 'missing_delivery' in params
    assert 'missing_deliver_time' not in params


def test_missing_delivery_condition_is_completed_and_empty_deliver() -> None:
    cond = missing_delivery_condition()
    compiled = str(cond.compile(compile_kwargs={'literal_binds': True}))
    lower = compiled.lower()
    assert 'completed' in lower
    assert 'deliver_time' in lower
    assert 'is null' in lower
    assert OrderStatus.abnormal.value not in lower


def test_order_select_missing_delivery_filter_compiles() -> None:
    async def _run() -> str:
        stmt = await order_dao.get_select(
            site_ids={13},
            site_id=13,
            rider_id=41,
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30),
            status='abnormal',
            order_no=None,
            import_batch_id=None,
            is_locked=None,
            attention=None,
            missing_delivery=True,
        )
        return str(stmt.compile(compile_kwargs={'literal_binds': True}))

    sql = anyio.run(_run).lower()
    assert 'completed' in sql
    assert 'deliver_time' in sql
    assert 'is null' in sql
    assert "'abnormal'" not in sql


def test_missing_delivery_order_query_matches_frontend_contract() -> None:
    query = missing_delivery_order_query(
        rider_id=41,
        site_id=13,
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    assert query['missing_delivery'] == '1'
    assert query['status'] == OrderStatus.completed.value
    assert query['rider_id'] == '41'
    assert query['site_id'] == '13'
    assert query['date_from'] == '2026-09-01'
    assert query['date_to'] == '2026-09-30'


def test_precheck_and_failure_see_orders_pass_missing_delivery_filter() -> None:
    period = SimpleNamespace(site_id=13, start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))
    link = _blocker_deeplink('missing_delivery', rider_id=41, period=period)  # type: ignore[arg-type]
    assert link is not None
    assert link.path == '/rider-salary/order'
    assert link.query is not None
    assert link.query['missing_delivery'] == '1'
    assert link.query['status'] == 'completed'
    fail_link = calc_failure_deeplink(
        code='missing_delivery',
        rider_id=41,
        site_id=13,
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    assert fail_link is not None
    assert fail_link['query']['missing_delivery'] == '1'
    dumped = serialize_calc_failures([
        {
            'rider_id': 41,
            'job_no': 'D5A001',
            'errors': [missing_delivery_message('MISS-1', date(2026, 9, 15))],
            'code': 'missing_delivery',
            'deeplink': fail_link,
        }
    ])
    row = CalculateRiderFailure.model_validate(dumped[0])
    assert row.code == 'missing_delivery'
    assert row.deeplink is not None
    assert row.deeplink.query is not None
    assert row.deeplink.query['missing_delivery'] == '1'


def test_lock_hard_fail_reasons_before_stale_recalc() -> None:
    hard = [
        no_plan_with_orders_message(['2026-09-15（1 单）']),
        missing_delivery_message('MISS-1', date(2026, 9, 15)),
        never_calculated_message('FIX_C17_R1', ['2026-09-15（ORD-1）']),
    ]
    stale_only = compose_lock_block_message(hard_fail_errors=[], stale_job_nos=['A001'])
    assert stale_only == stale_lock_message(['A001'])
    assert '请先重算' in (stale_only or '')

    both = compose_lock_block_message(hard_fail_errors=hard, stale_job_nos=['FIX_C17_R1'])
    assert both is not None
    assert both.startswith('锁账中止')
    assert '无生效方案' in both
    assert '送达时间为空' in both
    assert '从未成功落库' in both
    assert both.find('锁账中止') < both.find('请先重算')
    assert not both.startswith('存在需重算')
    assert '仍要锁' not in both
    wrapped = lock_hard_fail_message(hard)
    assert '仍要锁' not in wrapped
    assert compose_lock_block_message(hard_fail_errors=[], stale_job_nos=[]) is None


def test_empty_no_plan_days_do_not_block_lock() -> None:
    start = date(2026, 9, 1)
    end = date(2026, 9, 3)
    cancelled = _order(1, 'C-1', start, status=OrderStatus.cancelled.value)
    data = CalcInput(
        rider_id=1,
        site_id=13,
        period_start=start,
        period_end=end,
        hire_date=start,
        leave_date=None,
        employ_type='part_time',
        segments=[],
        orders=[cancelled],
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates=set(),
        site_order_dates={start},
        persist_advance=False,
    )
    assert collect_hard_fail_findings(data) == []
    extra = collect_never_calculated_finding(
        job_no='A001',
        completed_orders=[],
        has_success_payroll=False,
        already_hard_failed=False,
    )
    assert extra is None
    assert compose_lock_block_message(hard_fail_errors=[], stale_job_nos=[]) is None
    # 有完成单无方案才硬拦
    item = _item(
        pk=1,
        subject_id=1,
        name='基础单价',
        stage=CalcStage.per_order.value,
        sort_order=10,
        condition={},
        formula={'类型': '固定金额', '金额': 4},
    )
    with_orders = CalcInput(
        rider_id=1,
        site_id=13,
        period_start=start,
        period_end=end,
        hire_date=start,
        leave_date=None,
        employ_type='part_time',
        segments=[Segment(plan_version_id=1, start_date=start, end_date=start, items=[item])],
        orders=[_order(2, 'P-2', date(2026, 9, 2))],
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates={start, date(2026, 9, 2)},
        site_order_dates={start, date(2026, 9, 2)},
        persist_advance=False,
    )
    findings = collect_hard_fail_findings(with_orders)
    assert findings[0][0] == 'no_plan_with_orders'


def test_latest_recalc_job_api_and_select() -> None:
    params = inspect.signature(get_latest_recalc_job).parameters
    assert 'site_id' in params
    stmt = latest_recalc_job_select(site_id=13)
    sql = str(stmt.compile(compile_kwargs={'literal_binds': True})).lower()
    assert 'rs_recalc_job' in sql
    assert 'site_id' in sql
    assert 'limit' in sql
    sourced = latest_recalc_job_select(site_id=13, source=RecalcJobSource.import_batch.value)
    sourced_sql = str(sourced.compile(compile_kwargs={'literal_binds': True})).lower()
    assert RecalcJobSource.import_batch.value in sourced_sql
    empty = GetLatestRecalcJobResult(site_id=13, job=None)
    assert empty.job is None
    assert empty.site_id == 13


def test_classify_calc_failure_codes() -> None:
    assert classify_calc_failure_code(missing_delivery_message('X', date(2026, 9, 1))) == 'missing_delivery'
    assert classify_calc_failure_code(no_plan_with_orders_message(['2026-09-02（1 单）'])) == 'no_plan_with_orders'
    assert classify_calc_failure_code(never_calculated_message('A', ['2026-09-02（X）'])) == 'never_calculated'
    assert classify_calc_failure_code('公式计算失败') is None
