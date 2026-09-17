"""Cycle 1 CDP 夹具合同（DB-free）。产品 API 未落地时这些 JSON 仍约束具名断言。"""

from __future__ import annotations

import json

from datetime import date
from pathlib import Path

from backend.plugin.rider_salary.service.calc_service import (
    lock_hard_fail_message,
    missing_delivery_message,
    never_calculated_message,
    no_plan_with_orders_message,
)
from backend.plugin.rider_salary.service.period_service import (
    compose_lock_block_message,
    stale_lock_message,
)
from backend.plugin.rider_salary.service.recalc_job_service import finish_recalc_job_state

FIXTURES = Path(__file__).parent / 'fixtures'


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name / 'expected.json').read_text(encoding='utf-8'))


def test_cycle1_named_cdp_fixture_hooks() -> None:
    cal = _load('ops-calendar-adjust-date-window')
    assert cal['expected']['cta'] == '录入奖惩'
    assert cal['expected']['query_must'] == ['date_from', 'date_to', 'rider_id']

    imp = _load('ops-import-not-payroll')
    assert imp['expected']['result_copy'] == '导入完成 ≠ 已出账'
    assert imp['expected']['primary_cta'] == '去周期算薪页'
    assert imp['expected']['after_close_find_latest_site_job'] is True
    assert imp['expected']['frontend_calls_latest_api'] is True
    assert imp['expected']['localstorage_only_on_api_failure'] is True
    assert imp['expected']['ui_after_close'] == ['order-last-recalc', 'dashboard-batch-job']
    latest = imp['expected']['latest_job']
    assert latest['http'] == 200
    assert latest['job_nullable'] is True
    assert latest['shape'] == ['site_id', 'job']
    assert latest['must_not_skip_as_missing'] is True

    miss = _load('ops-order-missing-delivery-filter')
    assert miss['order_no'] == 'FIX_C17_MISSDEL_20260910'
    assert miss['expected']['ui_label'] == '已完成且送达为空'
    assert miss['expected']['query_param'] == 'missing_delivery'
    assert miss['expected']['filter_completed_and_null_deliver'] is True
    assert miss['expected']['ignore_param_is_fail'] is True

    lock = _load('ops-lock-reason-matches-calc')
    assert lock['expected']['hard_fail_outranks_stale'] is True
    assert lock['expected']['hard_fail_before_stale_in_msg'] is True
    assert lock['expected']['msg_starts_with'] == '锁账中止'
    assert lock['expected']['forbid_still_lock'] is True
    assert lock['isolated_zero_stale_spec'] == 'ops-lock-preflight-hard-fail'

    picker = _load('ops-payroll-list-period-picker')
    assert picker['expected']['not_primary_key_input'] is True
    assert picker['expected']['value_is_period_id'] is True

    subj = _load('cdp-admin-subject-filter-name')
    assert subj['expected']['tag_uses_subject_name'] is True
    assert '科目 ID n' in subj['expected']['forbid_label']


def test_lock_hard_fail_copy_not_stale_sentence() -> None:
    stale = stale_lock_message(['FIX_C17_R1'])
    hard = lock_hard_fail_message([no_plan_with_orders_message(['2026-09-15（1 单）'])])
    miss = missing_delivery_message('FIX_C17_MISSDEL_20260910', date(2026, 9, 10))
    never = never_calculated_message('FIX_C17_R1', ['2026-09-15（ORD-1）'])
    assert '请先重算' in stale
    assert '请先重算' not in hard
    assert '锁账中止' in hard
    assert '无生效方案' in hard
    assert '送达时间为空' in miss
    assert '从未成功落库' in never
    assert '仍要锁' not in stale
    assert '仍要锁' not in hard
    both = compose_lock_block_message(hard_fail_errors=[hard], stale_job_nos=['FIX_C17_R1'])
    assert both is not None
    assert both.startswith('锁账中止')
    assert both.find('锁账中止') < both.find('请先重算')


def test_recalc_partial_fail_not_done_complete() -> None:
    status, message = finish_recalc_job_state(
        done_periods=1,
        failed_rows=[{'rider_id': 9, 'job_no': 'FIX_C17_R1', 'errors': ['无生效方案']}],
    )
    assert status == 'failed'
    assert '部分失败' in message
    assert '失败 1 人' in message
    assert not message.startswith('完成：')
