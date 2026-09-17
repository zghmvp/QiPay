from datetime import date
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest

from openpyxl import load_workbook

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import CycleType, PayrollKind, PayrollStatus, PeriodStatus
from backend.plugin.rider_salary.service.export_service import (
    ADJUSTMENT_HEADERS,
    DETAIL_HEADERS,
    NET_HEADERS,
    SHEET_ADJUSTMENT,
    SHEET_DETAIL,
    SHEET_NET,
    SHEET_SUMMARY,
    SUMMARY_HEADERS,
    summarize_trace,
)
from backend.plugin.rider_salary.service.period_service import (
    assert_can_transition,
    build_lock_preflight_result,
    count_lock_freeze_targets,
    covering_period_ranges,
    is_site_level_period,
    reversible_payrolls,
    site_level_lock_excluded_rider_ids,
    stale_lock_message,
)
from backend.plugin.rider_salary.utils.excel import write_workbook


def test_generate_half_month_two_periods() -> None:
    ranges = covering_period_ranges(CycleType.half_month, None, 2026, 9)
    assert ranges == [
        (date(2026, 9, 1), date(2026, 9, 15)),
        (date(2026, 9, 16), date(2026, 9, 30)),
    ]


def test_generate_month_one_period() -> None:
    ranges = covering_period_ranges(CycleType.month, None, 2026, 9)
    assert ranges == [(date(2026, 9, 1), date(2026, 9, 30))]


def test_generate_custom_anchor_covers_month() -> None:
    ranges = covering_period_ranges(CycleType.custom, {'anchor_day': 26}, 2026, 9)
    assert ranges == [
        (date(2026, 8, 26), date(2026, 9, 25)),
        (date(2026, 9, 26), date(2026, 10, 25)),
    ]


def test_lock_rejects_stale_drafts() -> None:
    msg = stale_lock_message(['A001', 'A002'])
    assert msg == '存在需重算的薪资结果：工号 A001、A002，请先重算'


def test_illegal_transition_rejected() -> None:
    with pytest.raises(errors.RequestError, match='结算周期当前状态为开放，不允许执行标记发薪'):
        assert_can_transition(PeriodStatus.open.value, PeriodStatus.paid.value)
    with pytest.raises(errors.RequestError, match='结算周期当前状态为已发薪，不允许执行锁账'):
        assert_can_transition(PeriodStatus.paid.value, PeriodStatus.locked.value)
    assert assert_can_transition(PeriodStatus.open.value, PeriodStatus.locked.value) == '锁账'
    assert assert_can_transition(PeriodStatus.reopened.value, PeriodStatus.locked.value) == '锁账'
    assert assert_can_transition(PeriodStatus.locked.value, PeriodStatus.paid.value) == '标记发薪'
    assert assert_can_transition(PeriodStatus.locked.value, PeriodStatus.reopened.value) == '反冲补发'
    assert assert_can_transition(PeriodStatus.paid.value, PeriodStatus.reopened.value) == '反冲补发'


def test_reverse_selects_finalized_and_skips_reversal() -> None:
    payrolls = [
        SimpleNamespace(
            kind=PayrollKind.normal.value,
            status=PayrollStatus.finalized.value,
            reversed=False,
            net=Decimal('100.00'),
        ),
        SimpleNamespace(
            kind=PayrollKind.reversal.value,
            status=PayrollStatus.finalized.value,
            reversed=False,
            net=Decimal('-100.00'),
        ),
        SimpleNamespace(
            kind=PayrollKind.normal.value,
            status=PayrollStatus.draft.value,
            reversed=False,
            net=Decimal('8.00'),
        ),
        SimpleNamespace(
            kind=PayrollKind.supplement.value,
            status=PayrollStatus.paid.value,
            reversed=True,
            net=Decimal('12.00'),
        ),
        SimpleNamespace(
            kind=PayrollKind.normal.value,
            status=PayrollStatus.paid.value,
            reversed=False,
            net=Decimal('50.00'),
        ),
    ]
    selected = reversible_payrolls(payrolls)
    assert [item.net for item in selected] == [Decimal('100.00'), Decimal('50.00')]


def test_export_workbook_headers() -> None:
    content = write_workbook([
        (SHEET_SUMMARY, SUMMARY_HEADERS, [['A001', '张伟']]),
        (SHEET_DETAIL, DETAIL_HEADERS, []),
        (SHEET_ADJUSTMENT, ADJUSTMENT_HEADERS, []),
        (SHEET_NET, NET_HEADERS, [['A001', '张伟', 100, -100, 90, 90]]),
    ])
    workbook = load_workbook(BytesIO(content))
    assert workbook.sheetnames == [SHEET_SUMMARY, SHEET_DETAIL, SHEET_ADJUSTMENT, SHEET_NET]
    assert [cell.value for cell in workbook[SHEET_SUMMARY][1]] == SUMMARY_HEADERS
    assert [cell.value for cell in workbook[SHEET_DETAIL][1]] == DETAIL_HEADERS
    assert [cell.value for cell in workbook[SHEET_ADJUSTMENT][1]] == ADJUSTMENT_HEADERS
    assert [cell.value for cell in workbook[SHEET_NET][1]] == NET_HEADERS
    assert workbook[SHEET_SUMMARY]['A2'].value == 'A001'


def test_summarize_trace_one_line_chinese() -> None:
    text = summarize_trace({
        '条件': '配送距离 > 5',
        '条件结果': True,
        '公式': '(配送距离 - 5) * 0.8',
        '变量': {'配送距离': 7.2},
        '结果': 1.76,
    })
    assert '条件：配送距离 > 5（真）' in text
    assert '公式：(配送距离 - 5) * 0.8' in text
    assert '配送距离=7.2' in text
    assert '结果=1.76' in text


def test_site_level_lock_skips_rider_level_periods() -> None:
    overlapping = [
        SimpleNamespace(rider_id=18),
        SimpleNamespace(rider_id=0),
        SimpleNamespace(rider_id=None),
        SimpleNamespace(rider_id=22),
    ]
    assert site_level_lock_excluded_rider_ids(overlapping) == {18, 22}


def test_lock_preflight_site_level_reports_freeze_and_decision29_skip() -> None:
    excluded = site_level_lock_excluded_rider_ids([
        SimpleNamespace(rider_id=18),
        SimpleNamespace(rider_id=0),
        SimpleNamespace(rider_id=22),
    ])
    window_order_riders = [1, 1, 18, 22, 30]
    freeze_order, freeze_adj, freeze_payroll, lock_riders = count_lock_freeze_targets(
        is_site_level=True,
        period_rider_id=0,
        excluded_rider_ids=excluded,
        order_rider_ids=window_order_riders,
        adjustment_rider_ids=[18, 30],
        payroll_rider_ids=[1, 30],
    )
    assert freeze_order == 3
    assert freeze_adj == 1
    assert freeze_payroll == 2
    assert lock_riders == 2
    result = build_lock_preflight_result(
        is_site_level=True,
        excluded_rider_ids=excluded,
        freeze_order_count=freeze_order,
        freeze_adjustment_count=freeze_adj,
        freeze_payroll_count=freeze_payroll,
        lock_rider_count=lock_riders,
    )
    assert result.lock_rider_count == 2
    assert result.lock_rider_count != len(set(window_order_riders))
    assert result.skip_rider_count == 2
    assert result.skip_hint == '跳过骑手级覆盖 2 人'
    assert '跳过骑手级覆盖 2 人' in result.confirm_hint
    assert '将冻结订单 3 笔' in result.confirm_hint
    assert result.is_site_level is True


def test_lock_preflight_skip_zero_still_named() -> None:
    freeze_order, freeze_adj, freeze_payroll, lock_riders = count_lock_freeze_targets(
        is_site_level=True,
        period_rider_id=0,
        excluded_rider_ids=set(),
        order_rider_ids=[7, 8],
        adjustment_rider_ids=[7],
        payroll_rider_ids=[7, 8],
    )
    result = build_lock_preflight_result(
        is_site_level=True,
        excluded_rider_ids=set(),
        freeze_order_count=freeze_order,
        freeze_adjustment_count=freeze_adj,
        freeze_payroll_count=freeze_payroll,
        lock_rider_count=lock_riders,
    )
    assert result.skip_rider_count == 0
    assert result.lock_rider_count == 2
    assert result.skip_hint == '跳过骑手级覆盖 0 人'
    assert '跳过骑手级覆盖 0 人' in result.confirm_hint


def test_lock_preflight_rider_level_skip_is_zero() -> None:
    freeze_order, freeze_adj, freeze_payroll, lock_riders = count_lock_freeze_targets(
        is_site_level=False,
        period_rider_id=18,
        excluded_rider_ids={18, 22},
        order_rider_ids=[18, 18, 22],
        adjustment_rider_ids=[18],
        payroll_rider_ids=[18],
    )
    assert freeze_order == 2
    assert freeze_adj == 1
    assert freeze_payroll == 1
    assert lock_riders == 1
    result = build_lock_preflight_result(
        is_site_level=False,
        excluded_rider_ids={18, 22},
        freeze_order_count=freeze_order,
        freeze_adjustment_count=freeze_adj,
        freeze_payroll_count=freeze_payroll,
        lock_rider_count=lock_riders,
    )
    assert result.skip_rider_count == 0
    assert result.skip_hint == '跳过骑手级覆盖 0 人'
    assert is_site_level_period(SimpleNamespace(rider_id=0)) is True
    assert is_site_level_period(SimpleNamespace(rider_id=18)) is False
