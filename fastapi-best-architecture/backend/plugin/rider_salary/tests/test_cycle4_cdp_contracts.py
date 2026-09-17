"""Cycle 4 具名 CDP 夹具合同。#27 选择器缺失即失败，禁止 skip。"""

from __future__ import annotations

import inspect
import json

from datetime import date, timedelta
from pathlib import Path

from backend.plugin.rider_salary.enums import TrialMode
from backend.plugin.rider_salary.service.order_service import OrderService
from backend.plugin.rider_salary.service.rider_service import RiderService
from backend.plugin.rider_salary.utils.order_attention import (
    ATTENTION_DURATION_SECONDS,
    is_attention_order,
    lock_countdown_statuses,
    missing_delivery_condition,
    order_attention_condition,
)

FIXTURES = Path(__file__).parent / 'fixtures'
UI_PLUGIN = (
    Path(__file__).resolve().parents[5]
    / 'fastapi-best-architecture-ui'
    / 'apps'
    / 'web-antdv-next'
    / 'src'
    / 'plugins'
    / 'rider-salary'
)
UI_DASH = UI_PLUGIN / 'views' / 'dashboard'
UI_CAL = UI_PLUGIN / 'views' / 'calendar'
UI_PLAN = UI_PLUGIN / 'views' / 'plan'
UI_ORDER = UI_PLUGIN / 'views' / 'order'
UI_RIDER = UI_PLUGIN / 'views' / 'rider'
UI_PERIOD = UI_PLUGIN / 'views' / 'period'


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name / 'expected.json').read_text(encoding='utf-8'))


def _must_read(path: Path) -> str:
    assert path.is_file(), f'{path.name} 缺失即失败，不得 skip（#27）'
    return path.read_text(encoding='utf-8')


def test_cycle4_named_cdp_fixture_hooks() -> None:
    insight = _load('ops-dashboard-insight-card-scope')
    assert insight['expected']['skip_if_missing'] is False
    assert insight['expected']['testid_root'] == 'ops-dashboard-insight-card-scope'
    assert insight['expected']['testid_on_job'] == 'dashboard-insight-card-on_job_riders'
    assert insight['expected']['testid_top_riders'] == 'dashboard-top-riders'
    assert insight['expected']['testid_rider_list_scope'] == 'rider-list-status-scope'
    assert insight['expected']['empty_import_cta'] == '去导入订单'

    cal = _load('ops-calendar-month-export-confirm')
    assert cal['expected']['testid_calendar_export'] == 'calendar-export-month'
    assert cal['expected']['testid_calendar_confirm'] == 'ops-calendar-month-export-confirm'
    assert cal['expected']['testid_confirm'] == 'period-export-confirm'
    assert cal['expected']['testid_period_row'] == 'period-export-period-row'
    assert cal['expected']['confirm_before_export_network'] is True
    assert cal['expected']['default_exclude_orders'] is False

    att = _load('ops-dashboard-abnormal-attention-landing')
    assert att['expected']['testid_block'] == 'ops-dashboard-abnormal-attention-landing'
    assert att['expected']['testid_view_all'] == 'dashboard-abnormal-view-all'
    assert att['expected']['testid_order_active'] == 'order-attention-active'
    assert att['expected']['query_attention'] == 'attention=1'
    assert att['expected']['status_filter_value'] == '__attention__'
    assert ATTENTION_DURATION_SECONDS == 3600

    lock = _load('ops-dashboard-lock-overdue-visible')
    assert lock['expected']['testid_block'] == 'ops-dashboard-lock-overdue-visible'
    assert lock['expected']['testid_title'] == 'dashboard-lock-title'
    assert lock['expected']['testid_overdue'] == 'dashboard-lock-overdue'
    assert lock['expected']['testid_remaining'] == 'dashboard-lock-remaining'
    assert lock['expected']['testid_view_all'] == 'dashboard-lock-view-all'
    assert lock['expected']['testid_period_scope'] == 'period-lock-due-scope'
    assert lock['expected']['title'] == '锁账倒计时'
    assert lock['expected']['view_all_lock_due'] == 'lock_due=1'
    assert set(lock['expected']['statuses']) == set(lock_countdown_statuses())

    act = _load('ops-plan-activate-not-full-trial')
    assert act['extends'] == 'trial-equals-calc'
    assert act['expected']['hard_copy'] == '整版试算通过 ≠ 按当前绑定出账'
    assert act['expected']['testid_panel'] == 'ops-plan-activate-not-full-trial'
    assert act['expected']['testid_full_not_payroll'] == 'trial-full-not-payroll'
    assert act['expected']['testid_binding_full_amount'] == 'trial-binding-fixed-full-amount'
    assert act['expected']['testid_activate'] == 'plan-activate-not-full-trial'
    assert act['expected']['testid_trial_label'] == 'plan-trial-label'
    assert act['expected']['testid_period_fixed_once'] == 'period-fixed-amount-full-once'
    assert act['expected']['two_segment_fixed_2000_base_total'] == '4000.00'
    assert act['expected']['allocation_segment1_base'] == '933.33'
    assert act['expected']['locked_gold_unchanged']['C03_gross'] == '8200.00'
    assert act['expected']['locked_gold_unchanged']['C04_gross'] == '7800.00'
    assert act['expected']['locked_gold_unchanged']['C05A_gross'] == '3500.00'
    assert act['expected']['no_new_xor_or_gold_must_name'] is True
    assert TrialMode.binding_segments.value == act['expected']['binding_mode']

    trial = _load('trial-equals-calc')
    assert trial['expected']['activate_not_full_trial_testid'] == 'plan-activate-not-full-trial'
    assert trial['expected']['full_version_not_binding_promise_copy'] == '整版试算通过 ≠ 按当前绑定出账'
    assert trial['expected']['testid_full_not_payroll'] == 'trial-full-not-payroll'


def test_cycle4_fixture_json_round_trip() -> None:
    for name in (
        'ops-dashboard-insight-card-scope',
        'ops-calendar-month-export-confirm',
        'ops-dashboard-abnormal-attention-landing',
        'ops-dashboard-lock-overdue-visible',
        'ops-plan-activate-not-full-trial',
        'trial-equals-calc',
        'trial-case-gold',
    ):
        payload = _load(name)
        assert payload['expected']['skip_if_missing'] is False
        assert json.loads(json.dumps(payload)) == payload


def test_cycle4_does_not_change_locked_gold_fixture() -> None:
    gold = _load('trial-case-gold')
    assert gold['expected']['C03_gross'] == '8200.00'
    assert gold['expected']['C04_gross'] == '7800.00'
    assert gold['expected']['C05A_gross'] == '3500.00'
    act = _load('ops-plan-activate-not-full-trial')
    assert '4629.33' not in json.dumps(act)


def test_insight_card_hooks_from_pr27_must_not_skip() -> None:
    expected = _load('ops-dashboard-insight-card-scope')['expected']
    stats = _must_read(UI_DASH / 'components' / 'StatCards.vue')
    dash = _must_read(UI_DASH / 'index.vue')
    top = _must_read(UI_DASH / 'components' / 'TopRiders.vue')
    scope = _must_read(UI_DASH / 'scope-links.ts')
    rider = _must_read(UI_RIDER / 'index.vue')
    period = _must_read(UI_PERIOD / 'index.vue')
    assert f'data-testid="{expected["testid_root"]}"' in stats
    assert 'dashboard-insight-card-${item.key}' in stats
    for key in expected['cards']:
        assert f"key: '{key}'" in stats
    assert 'insightCardTarget' in stats
    assert 'site_id' in scope and 'month' in scope
    assert "status: 'on_job'" in scope
    assert 'date_from' in scope and 'date_to' in scope
    assert f'data-testid="{expected["testid_empty_import"]}"' in dash
    assert expected['empty_import_cta'] in dash
    assert 'orderImportTarget' in dash
    assert f'data-testid="{expected["testid_top_riders"]}"' in top
    assert 'calendarRiderTarget' in top
    assert f'data-testid="{expected["testid_rider_list_scope"]}"' in rider
    assert 'initialStatus' in rider
    assert "status: 'on_job'" in scope
    assert 'lock_due' in period or 'initialMonth' in period
    assert 'route.query.month' in period or 'initialMonth' in period
    assert 'advance_limit_count' not in stats
    assert '次数规则' not in stats


def test_calendar_month_export_confirm_hooks_from_pr27_must_not_skip() -> None:
    expected = _load('ops-calendar-month-export-confirm')['expected']
    cal = _must_read(UI_CAL / 'index.vue')
    confirm = _must_read(UI_PERIOD / 'components' / 'ExportConfirmModal.vue')
    stats = _must_read(UI_PERIOD / 'components' / 'export-adjust-stats.ts')
    types = _must_read(UI_PERIOD / 'components' / 'export-confirm-types.ts')
    assert f'data-testid="{expected["testid_calendar_export"]}"' in cal
    assert expected['calendar_cta'] in cal
    assert 'promptExport' in cal
    assert 'periods:' in cal or 'periods =' in cal
    export_fn = cal[cal.index('async function exportMonth') :]
    assert 'promptExport' in export_fn
    assert 'exportPeriodApi' in export_fn
    assert export_fn.index('promptExport') < export_fn.index('exportPeriodApi')
    assert "source: 'calendar'" in export_fn
    assert f'data-testid="{expected["testid_confirm"]}"' in confirm
    assert f'data-testid="{expected["testid_calendar_confirm"]}"' in confirm
    assert f'data-testid="{expected["testid_period_row"]}"' in confirm
    assert f'data-testid="{expected["testid_attention_count"]}"' in confirm
    assert f'data-testid="{expected["testid_adj_booked"]}"' in confirm
    assert f'data-testid="{expected["testid_adj_unbooked"]}"' in confirm
    assert f'data-testid="{expected["testid_adj_annotation"]}"' in confirm
    assert '该骑手该日存在需关注订单' in confirm
    assert f'data-testid="{expected["testid_exclude_toggle"]}"' in confirm
    assert f'data-testid="{expected["testid_adj_sync_toggle"]}"' in confirm
    assert 'excludeAttention = ref(false)' in confirm
    assert 'excludeAttentionAdjustments = ref(false)' in confirm
    assert 'periods?:' in types
    assert 'periodIds' in types
    assert 'resolveExportPeriods' in stats
    assert '缺少周期，无法统计需关注与奖惩条数' in stats
    assert 'data-testid="calendar-month-export"' not in cal
    assert 'if (!data.periodId)' not in stats or 'resolveExportPeriods' in stats


def test_abnormal_attention_landing_hooks_from_pr27_must_not_skip() -> None:
    expected = _load('ops-dashboard-abnormal-attention-landing')['expected']
    attention = _must_read(UI_DASH / 'components' / 'AttentionList.vue')
    scope = _must_read(UI_DASH / 'scope-links.ts')
    order = _must_read(UI_ORDER / 'index.vue')
    assert f"'{expected['testid_block']}'" in attention or f'"{expected["testid_block"]}"' in attention
    assert expected['testid_view_all'] in attention
    assert 'abnormalAttentionTarget' in scope
    assert "attention: '1'" in scope
    assert 'date_from' in scope
    assert 'missing_delivery' not in scope.split('abnormalAttentionTarget')[1][:400]
    assert f'data-testid="{expected["testid_order_active"]}"' in order
    assert "route.query.attention === '1'" in order
    assert "'__attention__'" in order or '"__attention__"' in order
    assert 'attention' in inspect.signature(OrderService.get_list).parameters
    cond = str(order_attention_condition().compile(compile_kwargs={'literal_binds': True})).lower()
    miss = str(missing_delivery_condition().compile(compile_kwargs={'literal_binds': True})).lower()
    assert 'abnormal' in cond and 'refunded' in cond and 'completed' in cond
    assert 'abnormal' not in miss


def test_lock_overdue_visible_hooks_from_pr27_must_not_skip() -> None:
    expected = _load('ops-dashboard-lock-overdue-visible')['expected']
    attention = _must_read(UI_DASH / 'components' / 'AttentionList.vue')
    due = _must_read(UI_DASH / 'due-countdown.ts')
    scope = _must_read(UI_DASH / 'scope-links.ts')
    period = _must_read(UI_PERIOD / 'index.vue')
    assert expected['testid_block'] in attention
    assert f'data-testid="{expected["testid_title"]}"' in attention or expected['testid_title'] in attention
    assert expected['testid_overdue'] in attention
    assert expected['testid_remaining'] in attention
    assert expected['testid_view_all'] in attention
    assert expected['title'] in due
    assert '已过期未锁' in due
    assert '剩余' in due
    assert 'LOCK_COUNTDOWN_HORIZON_DAYS = 3' in due
    assert 'isDueCountdownItem' in due
    assert 'lockCountdownViewAllTarget' in scope
    assert "lock_due: '1'" in scope
    assert "status: 'open'" not in scope.split('lockCountdownViewAllTarget')[1][:250]
    assert f'data-testid="{expected["testid_period_scope"]}"' in period
    assert 'lock_due' in period
    assert '仍要锁' not in attention


def test_activate_not_full_trial_hooks_from_pr27_must_not_skip() -> None:
    expected = _load('ops-plan-activate-not-full-trial')['expected']
    helpers = _must_read(UI_PLAN / 'helpers.ts')
    trial = _must_read(UI_PLAN / 'components' / 'TrialPanel.vue')
    editor = _must_read(UI_PLAN / 'editor.vue')
    index = _must_read(UI_PLAN / 'index.vue')
    formula = _must_read(UI_PLAN / 'components' / 'FormulaBuilder.vue')
    assert expected['hard_copy'] in helpers
    assert 'FULL_TRIAL_NOT_PAYROLL' in helpers
    assert 'BINDING_FIXED_FULL_AMOUNT' in helpers
    assert 'ACTIVATE_CONFIRM_CONTENT' in helpers
    assert expected['hard_copy'] in helpers
    assert '每段各计一次全额' in helpers
    assert '各计一次全额' in helpers
    assert expected['segment_full_amount_copy'] in helpers
    assert 'ACTIVATE_CONFIRM_CONTENT' in helpers
    assert expected['hard_copy'] in helpers
    assert expected['testid_panel'] in trial
    assert f'data-testid="{expected["testid_full_not_payroll"]}"' in trial
    assert f'data-testid="{expected["testid_binding_full_amount"]}"' in trial
    assert f'data-testid="{expected["testid_activate"]}"' in editor
    assert f'data-testid="{expected["testid_trial_label"]}"' in editor
    assert f'data-testid="{expected["testid_activate"]}"' in index
    assert f'data-testid="{expected["testid_period_fixed_once"]}"' in formula
    assert "text: '试算通过 ✓'" not in helpers
    assert 'bindingTrialPassed' in helpers
    assert TrialMode.binding_segments.value == 'binding_segments'


def test_rider_and_order_list_must_consume_query() -> None:
    assert 'status' in inspect.signature(RiderService.get_list).parameters
    assert 'attention' in inspect.signature(OrderService.get_list).parameters
    rider = _must_read(UI_RIDER / 'index.vue')
    order = _must_read(UI_ORDER / 'index.vue')
    assert 'initialStatus' in rider
    assert 'setValues' in rider
    assert "route.query.attention === '1'" in order


def test_attention_predicate_unchanged_from_cycle2() -> None:
    from datetime import datetime
    from datetime import timezone as dt_timezone

    from backend.plugin.rider_salary.enums import OrderStatus

    start = datetime(2026, 9, 1, 10, 0, tzinfo=dt_timezone.utc)
    timeout = start + timedelta(seconds=3601)
    on_time = start + timedelta(minutes=20)
    assert is_attention_order(status=OrderStatus.abnormal.value, order_time=start, deliver_time=on_time)
    assert is_attention_order(status=OrderStatus.refunded.value, order_time=start, deliver_time=on_time)
    assert is_attention_order(status=OrderStatus.completed.value, order_time=start, deliver_time=timeout)
    assert not is_attention_order(status=OrderStatus.completed.value, order_time=start, deliver_time=on_time)
    assert not is_attention_order(status=OrderStatus.completed.value, order_time=start, deliver_time=None)


def test_due_period_visibility_contract() -> None:
    today = date(2026, 9, 17)

    def visible(end: date) -> bool:
        return end <= today + timedelta(days=3)

    assert visible(date(2026, 9, 10)) is True
    assert visible(date(2026, 9, 20)) is True
    assert visible(date(2026, 9, 27)) is False
    due = _must_read(UI_DASH / 'due-countdown.ts')
    assert 'daysLeft <= LOCK_COUNTDOWN_HORIZON_DAYS' in due or 'daysLeft <= 3' in due
