"""Cycle 2 具名 CDP 夹具合同（DB-free）。产品未落地时 JSON 仍约束断言。"""

from __future__ import annotations

import inspect
import json

from decimal import Decimal
from pathlib import Path

from backend.plugin.rider_salary.api.v1.period import export_period
from backend.plugin.rider_salary.enums import RecalcJobStatus
from backend.plugin.rider_salary.schema.payroll import GetPayrollDetailItem
from backend.plugin.rider_salary.service.calc_service import finish_period_calc_status
from backend.plugin.rider_salary.service.payroll_service import (
    ADVANCE_SUBJECT_ID,
    build_subject_breakdown,
    gross_from_breakdown,
)
from backend.plugin.rider_salary.service.period_service import (
    CALC_SYNC_LIMIT,
    calc_status_label,
    calc_sync_limit,
    should_queue_calculate,
)
from backend.plugin.rider_salary.service.recalc_job_service import finish_recalc_job_state
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.order_attention import (
    ATTENTION_DURATION_SECONDS,
    attention_confession,
    keep_export_detail_row,
)
from backend.plugin.rider_salary.utils.plan_guarantee import GUARANTEE_LAST_MSG

FIXTURES = Path(__file__).parent / 'fixtures'
D = Decimal


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name / 'expected.json').read_text(encoding='utf-8'))


def test_cycle2_named_cdp_fixture_hooks() -> None:
    gold = _load('trial-case-gold')
    assert gold['expected']['C03_gross'] == '8200.00'
    assert gold['expected']['C04_gross'] == '7800.00'
    assert gold['expected']['C05A_gross'] == '3500.00'
    assert gold['expected']['gold_is_backend'] is True
    assert gold['expected']['skip_if_missing'] is False
    assert gold['expected']['no_numbers_is_fail'] is True
    assert gold['expected']['C17_period_valid_amount'] == '2310.00'
    assert gold['expected']['C17_plan_period_amount'] == '100.00'

    trial = _load('trial-binding-segments')
    assert trial['expected']['cdp_no_numbers_is_fail'] is True
    assert (
        trial['expected']['field_contrast_FIX_C17']['period_valid_field_amount']
        != trial['expected']['field_contrast_FIX_C17']['plan_period_field_on_segment_b_amount']
    )

    g = _load('ops-plan-guarantee-last')
    assert g['expected']['save_fails'] is True
    assert g['expected']['activate_fails'] is True
    assert g['expected']['cancel_must_not_save'] is True
    assert '须放在周期阶段最后' in g['expected']['fail_copy']

    exp = _load('ops-export-attention-parity')
    assert exp['expected']['default_exclude'] is False
    assert exp['expected']['unexcluded_copy'] == '本文件含需关注'
    assert exp['expected']['does_not_change_gross_net'] is True
    assert exp['expected']['exclude_must_strip_detail_rows'] is True
    assert exp['expected']['skip_if_missing'] is False
    assert exp['expected']['testid_confirm'] == 'period-export-confirm'
    assert exp['expected']['testid_count'] == 'period-export-attention-count'
    assert exp['expected']['testid_toggle'] == 'period-export-exclude-toggle'
    assert exp['expected']['testid_admit'] == 'period-export-admit-attention'
    assert 'abnormal' in exp['attention_union']
    assert ATTENTION_DURATION_SECONDS == 3600

    layers = _load('cdp-admin-payslip-layers')
    assert layers['expected']['recon_formula'] == '应发 − 代扣 − 预支抵扣 = 实发'
    assert layers['expected']['layer_titles'] == ['应发', '代扣', '预支抵扣', '实发']
    assert layers['expected']['testid_layers'] == 'payroll-layers'
    assert layers['expected']['testid_recon'] == 'payroll-reconciliation'

    remark = _load('cdp-admin-deduction-remark')
    assert remark['expected']['empty_remark'] == '无说明'
    assert remark['expected']['testid'] == 'payroll-deduction-remark'

    four = _load('cdp-admin-calc-success-four-numbers')
    assert '代扣' in four['expected']['success_columns']
    assert '预支抵扣' in four['expected']['success_columns']
    assert four['expected']['failed_row_shows_rider_name'] is True
    assert four['expected']['detail_testid_layers'] == 'payroll-layers'
    assert four['expected']['detail_testid_recon'] == 'payroll-reconciliation'

    profile = _load('ops-rider-profile-to-payroll')
    assert profile['expected']['cta'] == '本骑手薪资结果'
    assert profile['expected']['testid'] == 'rider-goto-payroll'
    assert profile['expected']['query'] == ['rider_id']
    assert profile['expected']['no_new_menu'] is True
    assert profile['expected']['binding_cta'] == '去周期算薪页'
    assert profile['expected']['binding_testid'] == 'rider-binding-goto-calculate'

    queued = _load('ops-queued-calc-progress')
    assert queued['expected']['sync_limit_default'] == CALC_SYNC_LIMIT == calc_sync_limit() == 200
    assert queued['expected']['failed_gt_zero_forbids_green_complete'] is True
    assert queued['expected']['no_celery'] is True
    assert queued['expected']['last_calc_status_labels'] == ['排队中', '计算中', '完成', '失败']
    assert RecalcJobStatus.queued.label == '排队中'
    assert RecalcJobStatus.running.label == '计算中'
    assert RecalcJobStatus.done.label == '完成'
    assert RecalcJobStatus.failed.label == '失败'
    assert 'exclude_attention' in inspect.signature(export_period).parameters
    assert keep_export_detail_row(exclude_attention=True, order_id=9, attention_ids={9}) is False
    assert keep_export_detail_row(exclude_attention=False, order_id=9, attention_ids={9}) is True
    assert '本文件含需关注' in (attention_confession(count=3, excluded=False) or '')
    assert '须放在周期阶段最后' in GUARANTEE_LAST_MSG
    assert should_queue_calculate(200) is False
    assert should_queue_calculate(201) is True
    assert calc_status_label(RecalcJobStatus.queued.value) == '排队中'
    assert calc_status_label(RecalcJobStatus.running.value) == '计算中'


def test_payslip_recon_and_mixed_include_in_gross_split() -> None:
    items = [
        GetPayrollDetailItem.model_validate({
            'rider_id': 1,
            'stage': 'period',
            'subject_id': 1,
            'amount': D('100.00'),
            'include_in_gross': True,
            'source': 'formula',
            'subject_name': '提成',
        }),
        GetPayrollDetailItem.model_validate({
            'rider_id': 1,
            'stage': 'period',
            'subject_id': 15,
            'amount': D('-50.00'),
            'include_in_gross': False,
            'source': 'manual',
            'subject_name': '保险费代扣',
            'name': '保险费代扣',
        }),
        GetPayrollDetailItem.model_validate({
            'rider_id': 1,
            'stage': 'period',
            'subject_id': 1,
            'amount': D('-10.00'),
            'include_in_gross': False,
            'source': 'manual',
            'subject_name': '提成',
            'name': '提成冲减',
        }),
        GetPayrollDetailItem.model_validate({
            'rider_id': 1,
            'stage': 'period',
            'subject_id': 0,
            'amount': D('-20.00'),
            'include_in_gross': False,
            'source': 'advance',
            'subject_name': '预支抵扣',
        }),
    ]
    breakdown = build_subject_breakdown(items)
    split = [row for row in breakdown if row.subject_id == 1]
    assert len(split) == 2
    assert {row.include_in_gross for row in split} == {True, False}
    assert gross_from_breakdown(breakdown) == q2(D('100.00'))
    gross = q2(D('100.00'))
    deduction = q2(D('60.00'))
    advance = q2(D('20.00'))
    net = q2(gross - deduction - advance)
    assert net == q2(D('20.00'))
    assert ADVANCE_SUBJECT_ID == 0


def test_queued_failed_still_not_green_complete() -> None:
    status, message = finish_recalc_job_state(
        done_periods=1,
        failed_rows=[{'rider_id': 9, 'job_no': 'FIX_C17_R1', 'errors': ['无生效方案']}],
    )
    assert status == RecalcJobStatus.failed.value
    assert '完成：' not in message
    assert '部分失败' in message
    last_status, last_msg = finish_period_calc_status(calculated=3, failed_count=2)
    assert last_status == RecalcJobStatus.failed.value
    assert '部分失败' in last_msg
    assert last_msg != '完成'
    assert '完成' not in last_msg
    ok_status, ok_msg = finish_period_calc_status(calculated=3, failed_count=0)
    assert ok_status == RecalcJobStatus.done.value
    assert ok_msg == '已计算 3 人'
