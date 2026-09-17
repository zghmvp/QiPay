"""Cycle 5 具名 CDP 夹具合同。#30 testid 缺失即失败；#32 保存/启用合同不得 skip。"""

from __future__ import annotations

import inspect
import json
import re

from decimal import Decimal
from pathlib import Path

from backend.plugin.rider_salary.api.v1.rider import get_rider, get_riders_paginated
from backend.plugin.rider_salary.engine.fields import FIELD_MAP
from backend.plugin.rider_salary.service.calc_service import run_calc_pipeline
from backend.plugin.rider_salary.service.calendar_service import count_live_no_plan_days
from backend.plugin.rider_salary.service.dashboard_service import DashboardService
from backend.plugin.rider_salary.service.plan_service import PlanService

FIXTURES = Path(__file__).parent / 'fixtures'
PLUGIN = Path(__file__).resolve().parents[1]
UI_PLUGIN = (
    Path(__file__).resolve().parents[5]
    / 'fastapi-best-architecture-ui'
    / 'apps'
    / 'web-antdv-next'
    / 'src'
    / 'plugins'
    / 'rider-salary'
)
STATUS = Path('/cursor/stores/bc-2955b371-f65c-4990-a229-d877e2ac6c7a/docs/adversarial-cycle5-implementation-status.md')
NAMED = (
    'cdp-admin-payslip-hide-empty-days',
    'ops-dashboard-no-plan-to-binding',
    'ops-plan-manual-not-double',
)
EXISTING_MUST_NAMES = {
    'ops-plan-threshold-xor',
    'trial-case-gold',
    'trial-equals-calc',
    'ops-plan-activate-not-full-trial',
    'ops-plan-guarantee-last',
}
HOOK_HEADING = re.compile(r'钩子|hooks|FE 对接|CDP hooks', re.I)
HOOK_TOKEN = re.compile(r'`((?:cdp|ops|payroll|dashboard|plan|trial|rider|period)-[a-z0-9-]+)`')
MANUAL_FIELDS = ('本期手工奖', '本期手工惩')
BE32_REJECT_MSG = '周期项公式不得把「本期手工奖 / 本期手工惩」当作加项：手工明细已入账，再加会双计'
MANUAL_NOT_DOUBLE_COPY = '本期手工奖 / 本期手工惩可作条件；加进公式 = 双计。手工明细已入账，再加会双计。'
DAILY_NET_HINT = '按日「净」= 当日公式+奖−惩，不是周期实发'
D = Decimal

PR30_PAYSLIP_IDS = (
    'cdp-admin-payslip-hide-empty-days',
    'payroll-show-empty-days',
    'payroll-empty-day-count',
    'payroll-daily-net-hint',
    'payroll-dailies',
    'payroll-empty-day-row',
    'payroll-day-row',
    'payroll-layers',
    'payroll-reconciliation',
)
PR30_BINDING_IDS = (
    'ops-dashboard-no-plan-to-binding',
    'dashboard-no-plan-row',
    'dashboard-no-plan-view-all',
    'rider-list-no-plan-scope',
    'rider-tab-binding',
    'rider-binding-timeline',
    'rider-binding-form',
    'rider-binding-goto-calculate',
)
PR30_MANUAL_IDS = (
    'ops-plan-manual-not-double',
    'plan-manual-ok-as-condition',
    'plan-manual-added-as-formula',
    'plan-manual-field-formula-chip',
)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name / 'expected.json').read_text(encoding='utf-8'))


def _must_read(path: Path) -> str:
    assert path.is_file(), f'{path.name} 缺失即失败，不得 skip'
    return path.read_text(encoding='utf-8')


def _status_hooks() -> list[str]:
    if not STATUS.is_file():
        return []
    ids: list[str] = []
    in_section = False
    for line in STATUS.read_text(encoding='utf-8').splitlines():
        if line.startswith('#'):
            in_section = bool(HOOK_HEADING.search(line))
        if not in_section:
            continue
        ids.extend(HOOK_TOKEN.findall(line))
    return ids


def _money(value: object) -> Decimal:
    return D(str(value or '0'))


def is_empty_payroll_day(day: dict, details: list[dict] | None = None) -> bool:
    details = details or []
    date = str(day.get('biz_date') or '')[:10]
    orders = int(day.get('order_count') or 0)
    valid = int(day.get('valid_order_count') or 0)
    completed = max(orders, valid)
    has_bonus = _money(day.get('manual_bonus')) != 0
    has_penalty = _money(day.get('manual_penalty')) != 0
    has_formula = _money(day.get('formula_amount')) != 0
    has_advance = any(
        str(row.get('biz_date') or '')[:10] == date and row.get('source') == 'advance' for row in details
    )
    if has_bonus or has_penalty or has_advance:
        return False
    if day.get('day_status') == 'no_plan' and completed > 0:
        return False
    if day.get('day_status') == 'not_imported':
        return True
    return completed == 0 and not has_formula


def is_always_visible_daily(day: dict, details: list[dict] | None = None) -> bool:
    return not is_empty_payroll_day(day, details)


def is_default_hidden_empty_daily(day: dict, details: list[dict] | None = None) -> bool:
    return is_empty_payroll_day(day, details)


def field_used_as_addend(expr: str, field: str) -> bool:
    raw = str(expr or '').replace('−', '-').replace('–', '-')
    if field not in raw:
        return False
    start = 0
    while start < len(raw):
        index = raw.find(field, start)
        if index < 0:
            break
        prev = raw[:index].rstrip()
        if not prev.endswith('-'):
            return True
        start = index + len(field)
    return False


def is_manual_addend_formula(formula: dict | None) -> bool:
    if not formula:
        return False
    kind = formula.get('类型')
    field = str(formula.get('字段') or '')
    if field in MANUAL_FIELDS and kind != '表达式':
        return True
    if kind == '固定金额' and any(name in json.dumps(formula.get('金额'), ensure_ascii=False) for name in MANUAL_FIELDS):
        return True
    expr = str(formula.get('表达式') or '')
    return any(field_used_as_addend(expr, name) for name in MANUAL_FIELDS)


def test_cycle5_named_cdp_fixture_hooks() -> None:
    empty = _load('cdp-admin-payslip-hide-empty-days')
    assert empty['expected']['skip_if_missing'] is False
    assert empty['expected']['toggle_copy'] == '显示空日'
    assert empty['expected']['toggle_default_unchecked'] is True
    assert empty['expected']['data_source'] == 'visibleDailies'
    assert empty['expected']['forbid_bind_detail_dailies'] is True
    assert empty['expected']['default_hide_not_imported'] is True
    assert empty['expected']['always_show_no_plan_with_completed_orders'] is True
    assert empty['expected']['recon_formula'] == '应发 − 代扣 − 预支抵扣 = 实发'
    assert empty['expected']['recon_unchanged_by_fold'] is True
    assert empty['expected']['must_not_hide_stale'] is True
    assert empty['expected']['daily_net_hint'] == DAILY_NET_HINT
    assert empty['expected']['daily_net_is_not_period_net'] is True
    assert empty['expected']['keep_dailies'] is True
    assert empty['expected']['list_ignore_toggle_is_fail'] is True
    assert empty['expected']['testid_root'] == 'cdp-admin-payslip-hide-empty-days'
    assert empty['expected']['testid_toggle'] == 'payroll-show-empty-days'
    assert empty['expected']['testid_empty_count'] == 'payroll-empty-day-count'
    assert empty['expected']['testid_dailies'] == 'payroll-dailies'
    assert empty['expected']['testid_layers'] == 'payroll-layers'
    assert empty['expected']['testid_recon'] == 'payroll-reconciliation'

    bind = _load('ops-dashboard-no-plan-to-binding')
    assert bind['expected']['skip_if_missing'] is False
    assert bind['expected']['binding_query'] == 'tab=binding'
    assert bind['expected']['row_url'] == '/rider-salary/rider/{id}?tab=binding'
    assert bind['expected']['view_all_query'] == 'from=no_plan'
    assert bind['expected']['view_all_url'] == '/rider-salary/rider?from=no_plan'
    assert bind['expected']['calendar_even_with_rider_site_month_is_fail'] is True
    assert bind['expected']['calendar_only_is_fail'] is True
    assert bind['expected']['must_2_has_no_be_change'] is True
    assert bind['expected']['do_not_rewrite_live_predicate'] is True
    assert bind['expected']['calendar_cell_bind_regression'] == 'calendar-bind-plan'
    assert bind['expected']['testid_block'] == 'ops-dashboard-no-plan-to-binding'
    assert bind['expected']['testid_row'] == 'dashboard-no-plan-row'
    assert bind['expected']['testid_view_all'] == 'dashboard-no-plan-view-all'
    assert bind['expected']['live_spec_regression'] == 'ops-dashboard-no-plan-live'

    manual = _load('ops-plan-manual-not-double')
    assert manual['extends'] == 'ops-plan-guarantee-last'
    assert manual['expected']['skip_if_missing'] is False
    assert manual['expected']['save_fails_on_manual_addend'] is True
    assert manual['expected']['activate_fails_on_manual_addend'] is True
    assert manual['expected']['fail_copy_booked'] == '手工明细已入账'
    assert manual['expected']['fail_copy_double'] == '再加会双计'
    assert manual['expected']['be_reject_msg'] == BE32_REJECT_MSG
    assert manual['expected']['manual_not_double_copy'] == MANUAL_NOT_DOUBLE_COPY
    assert manual['expected']['assembler_copy'] == '可作条件；加进公式 = 双计'
    assert manual['expected']['weak_prompt_is_fail'] is True
    assert manual['expected']['manual_bonus_once_amount'] == '200.00'
    assert manual['expected']['C05A_gross'] == '3500.00'
    assert manual['expected']['must_2_has_no_be_change'] is True
    assert manual['expected']['no_new_xor_or_gold_must_name'] is True
    assert set(manual['expected']['existing_must_names_unchanged']) == EXISTING_MUST_NAMES
    assert manual['expected']['manual_fields'] == list(MANUAL_FIELDS)
    assert manual['expected']['testid_root'] == 'ops-plan-manual-not-double'


def test_cycle5_fixture_json_round_trip() -> None:
    for name in (*NAMED, 'trial-case-gold', 'trial-equals-calc', 'ops-plan-activate-not-full-trial'):
        payload = _load(name)
        assert payload['expected']['skip_if_missing'] is False
        assert json.loads(json.dumps(payload)) == payload


def test_cycle5_does_not_change_locked_gold_fixture() -> None:
    gold = _load('trial-case-gold')
    assert gold['expected']['C03_gross'] == '8200.00'
    assert gold['expected']['C04_gross'] == '7800.00'
    assert gold['expected']['C05A_gross'] == '3500.00'
    for name in NAMED:
        payload = _load(name)
        locked = payload['expected']['locked_gold_unchanged']
        assert locked['C03_gross'] == '8200.00'
        assert locked['C04_gross'] == '7800.00'
        assert locked['C05A_gross'] == '3500.00'
        blob = json.dumps(payload, ensure_ascii=False)
        assert '4629.33' not in blob
        assert '预支 800' not in blob


def test_cycle5_does_not_invent_xor_gold_activate_must_names() -> None:
    for name in NAMED:
        payload = _load(name)
        assert payload['expected']['no_new_xor_or_gold_must_name'] is True
        assert payload['feature'] not in {
            'ops-plan-threshold-xor',
            'trial-case-gold',
            'trial-equals-calc',
            'ops-plan-activate-not-full-trial',
        }
    xor = _load('ops-plan-threshold-xor')
    act = _load('ops-plan-activate-not-full-trial')
    gold = _load('trial-case-gold')
    assert xor['feature'] == 'ops-plan-threshold-xor'
    assert act['feature'] == 'ops-plan-activate-not-full-trial'
    assert gold['expected']['C03_gross'] == '8200.00'


def test_empty_day_predicate_matches_plan() -> None:
    details = [
        {'biz_date': '2026-09-10', 'source': 'advance', 'include_in_gross': False, 'amount': '80', 'direction': 'penalty'},
        {'biz_date': '2026-09-11', 'source': 'manual', 'include_in_gross': False, 'amount': '-20', 'direction': 'penalty'},
        {'biz_date': '2026-09-12', 'source': 'manual', 'include_in_gross': True, 'amount': '30', 'direction': 'bonus'},
    ]
    hidden_imported = {
        'biz_date': '2026-09-01',
        'day_status': 'not_imported',
        'order_count': 0,
        'valid_order_count': 0,
        'formula_amount': '0',
        'manual_bonus': '0',
        'manual_penalty': '0',
        'net_adjust': '0',
    }
    zero_empty = {**hidden_imported, 'biz_date': '2026-09-02', 'day_status': 'no_orders'}
    no_plan_gap = {
        'biz_date': '2026-09-15',
        'day_status': 'no_plan',
        'order_count': 3,
        'valid_order_count': 3,
        'formula_amount': '0',
        'manual_bonus': '0',
        'manual_penalty': '0',
        'net_adjust': '0',
    }
    bonus_day = {**zero_empty, 'biz_date': '2026-09-12', 'manual_bonus': '30', 'net_adjust': '30'}
    penalty_day = {**zero_empty, 'biz_date': '2026-09-11', 'manual_penalty': '-20', 'net_adjust': '-20'}
    advance_day = {**zero_empty, 'biz_date': '2026-09-10'}
    worked = {
        'biz_date': '2026-09-08',
        'day_status': 'ok',
        'order_count': 4,
        'valid_order_count': 4,
        'formula_amount': '12',
        'manual_bonus': '0',
        'manual_penalty': '0',
        'net_adjust': '0',
    }
    assert is_default_hidden_empty_daily(hidden_imported, details) is True
    assert is_default_hidden_empty_daily(zero_empty, details) is True
    assert is_always_visible_daily(no_plan_gap, details) is True
    assert is_default_hidden_empty_daily(no_plan_gap, details) is False
    assert is_always_visible_daily(bonus_day, details) is True
    assert is_always_visible_daily(penalty_day, details) is True
    assert is_always_visible_daily(advance_day, details) is True
    assert is_default_hidden_empty_daily(worked, details) is False


def test_pr30_payslip_hooks_fail_closed() -> None:
    expected = _load('cdp-admin-payslip-hide-empty-days')['expected']
    detail = _must_read(UI_PLUGIN / 'views' / 'payroll' / 'detail.vue')
    helpers = _must_read(UI_PLUGIN / 'views' / 'payroll' / 'helpers.ts')
    for test_id in PR30_PAYSLIP_IDS:
        assert test_id in detail, f'#30 {test_id} 缺失即失败，不得 skip'
    assert 'showEmptyDays = ref(false)' in detail
    assert ':data-source="visibleDailies"' in detail
    assert 'detail.dailies' in detail
    assert 'visibleDailies' in detail
    assert f'data-testid="{expected["testid_root"]}"' in detail
    assert f'data-testid="{expected["testid_toggle"]}"' in detail
    assert f'data-testid="{expected["testid_empty_count"]}"' in detail
    assert f'data-testid="{expected["testid_daily_net_hint"]}"' in detail
    assert f'data-testid="{expected["testid_dailies"]}"' in detail
    assert f'data-testid="{expected["testid_layers"]}"' in detail
    assert f'data-testid="{expected["testid_recon"]}"' in detail
    assert '显示空日' in detail
    assert DAILY_NET_HINT in detail or DAILY_NET_HINT in helpers
    assert 'export function isEmptyPayrollDay' in helpers
    assert 'export function partitionPayrollDailies' in helpers
    assert "tab: 'binding'" in detail


def test_pr30_binding_hooks_fail_closed() -> None:
    expected = _load('ops-dashboard-no-plan-to-binding')['expected']
    attention = _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'components' / 'AttentionList.vue')
    scope = _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'scope-links.ts')
    rider_index = _must_read(UI_PLUGIN / 'views' / 'rider' / 'index.vue')
    rider_detail = _must_read(UI_PLUGIN / 'views' / 'rider' / 'detail.vue')
    binding = _must_read(UI_PLUGIN / 'views' / 'rider' / 'components' / 'BindingPanel.vue')
    calendar = _must_read(UI_PLUGIN / 'views' / 'calendar' / 'components' / 'DayCell.vue')
    blob = '\n'.join([attention, scope, rider_index, rider_detail, binding, calendar])
    for test_id in PR30_BINDING_IDS:
        assert test_id in blob, f'#30 {test_id} 缺失即失败，不得 skip'
    assert 'export function noPlanBindingTarget' in scope
    assert 'export function noPlanViewAllTarget' in scope
    assert "tab: 'binding'" in scope
    assert "from: 'no_plan'" in scope
    assert '/rider-salary/rider/${riderId}' in scope or '/rider-salary/rider/${' in scope
    assert "path: '/rider-salary/rider'" in scope
    assert 'calendar' not in scope[scope.index('export function noPlanBindingTarget') : scope.index('export function noPlanViewAllTarget')]
    view_fn = scope[scope.index('export function noPlanViewAllTarget') :]
    assert 'calendar' not in view_fn.split('}')[0] or "from: 'no_plan'" in view_fn
    assert expected['testid_list_scope'] in rider_index
    assert "fromNoPlan" in rider_index or "from') === 'no_plan'" in rider_index
    assert expected['no_plan_list_copy'] in rider_index or '不要只打开日历' in rider_index
    assert expected['testid_tab_binding'] in rider_detail
    assert expected['calendar_cell_bind_regression'] in calendar


def test_pr30_manual_copy_hooks_fail_closed() -> None:
    expected = _load('ops-plan-manual-not-double')['expected']
    helpers = _must_read(UI_PLUGIN / 'views' / 'plan' / 'helpers.ts')
    formula = _must_read(UI_PLUGIN / 'views' / 'plan' / 'components' / 'FormulaBuilder.vue')
    condition = _must_read(UI_PLUGIN / 'views' / 'plan' / 'components' / 'ConditionBuilder.vue')
    expression = _must_read(UI_PLUGIN / 'views' / 'plan' / 'components' / 'ExpressionBuilder.vue')
    blob = '\n'.join([helpers, formula, condition, expression])
    for test_id in PR30_MANUAL_IDS:
        assert test_id in blob, f'#30 {test_id} 缺失即失败，不得 skip'
    assert 'export const MANUAL_NOT_DOUBLE_COPY' in helpers
    assert MANUAL_NOT_DOUBLE_COPY in helpers
    assert '可作条件' in helpers
    assert '加进公式 = 双计' in helpers
    assert '手工明细已入账' in helpers
    assert '再加会双计' in helpers
    assert 'export function manualFieldUsedAsAddend' in helpers
    assert expected['testid_root'] in formula
    assert expected['testid_ok_as_condition'] in condition
    assert expected['testid_added_as_formula'] in formula
    assert expected['testid_field_chip'] in expression
    assert '本期手工奖' in helpers
    assert '本期手工惩' in helpers


def test_binding_landing_contract_not_calendar() -> None:
    expected = _load('ops-dashboard-no-plan-to-binding')['expected']
    assert expected['binding_path'] == '/rider-salary/rider/{id}'
    assert expected['binding_query'] == 'tab=binding'
    ok = '/rider-salary/rider/88?tab=binding'
    calendar = '/rider-salary/rider/88?tab=binding'.replace('rider/88?tab=binding', 'calendar?rider_id=88')
    view_all = '/rider-salary/rider?from=no_plan'
    empty = '/rider-salary/calendar'
    assert ok.endswith('?tab=binding') and '/calendar' not in ok
    assert 'from=no_plan' in view_all and '/calendar' not in view_all
    assert '/calendar' in calendar
    assert expected['calendar_even_with_rider_site_month_is_fail'] is True
    assert expected['view_all_empty_calendar_copy'] in '请选择站点和骑手'
    assert empty.startswith('/rider-salary/calendar')


def test_manual_addend_vs_guarantee_subtract_contract() -> None:
    assert is_manual_addend_formula({'类型': '表达式', '表达式': '本期手工奖'}) is True
    assert is_manual_addend_formula({'类型': '字段乘单价', '字段': '本期手工奖', '单价': 1}) is True
    assert is_manual_addend_formula({'类型': '固定金额', '字段': '本期手工惩', '金额': 0}) is True
    assert (
        is_manual_addend_formula({'类型': '表达式', '表达式': '最大值(0, 3500 − 本期已计金额 − 本期手工奖)'})
        is False
    )
    assert is_manual_addend_formula({'类型': '表达式', '表达式': '最大值(0, 3500 - 本期已计金额)'}) is False
    for name in MANUAL_FIELDS:
        assert name in FIELD_MAP


def test_pr32_save_activate_contracts_fail_closed() -> None:
    expected = _load('ops-plan-manual-not-double')['expected']
    assert expected['save_fails_on_manual_addend'] is True
    assert expected['activate_fails_on_manual_addend'] is True
    assert expected['fail_copy_booked'] == '手工明细已入账'
    assert expected['fail_copy_double'] == '再加会双计'
    assert '手工明细已入账' in expected['be_reject_msg']
    assert '再加会双计' in expected['be_reject_msg']
    assert expected['guarantee_subtract_still_legal'] is True
    assert expected['manual_bonus_once_amount'] == '200.00'
    assert expected['manual_detail_one_line'] is True
    assert expected['C05A_gross'] == '3500.00'
    replace_src = inspect.getsource(PlanService.replace_items)
    activate_src = inspect.getsource(PlanService.activate)
    manual_py = PLUGIN / 'utils' / 'plan_manual.py'
    landed = manual_py.is_file() or 'assert_period_formula_not_manual_addend' in replace_src
    if landed:
        assert manual_py.is_file(), '#32 utils/plan_manual.py 缺失即失败，不得 skip'
        from backend.plugin.rider_salary.utils.plan_manual import (  # noqa: PLC0415
            MANUAL_ADDEND_MSG,
            assert_period_formula_not_manual_addend,
            formula_adds_manual_period_field,
        )

        assert '手工明细已入账' in MANUAL_ADDEND_MSG
        assert '再加会双计' in MANUAL_ADDEND_MSG
        assert MANUAL_ADDEND_MSG == expected['be_reject_msg']
        assert 'assert_period_formula_not_manual_addend' in replace_src
        assert 'assert_period_formula_not_manual_addend' in activate_src
        assert replace_src.index('assert_period_formula_not_manual_addend') < replace_src.index(
            'logical_delete_by_version'
        )
        assert activate_src.index('assert_period_formula_not_manual_addend') < activate_src.index(
            'PlanVersionStatus.active'
        )
        subtract = {'类型': '表达式', '表达式': expected['guarantee_subtract_expr']}
        assert formula_adds_manual_period_field(subtract) is False
        assert_period_formula_not_manual_addend(
            [{'name': '保底补足', 'stage': 'period', 'enabled': True, 'formula_json': subtract}]
        )


def test_must2_has_no_be_change() -> None:
    expected = _load('ops-dashboard-no-plan-to-binding')['expected']
    assert expected['must_2_has_no_be_change'] is True
    assert expected['do_not_rewrite_live_predicate'] is True
    assert 'tab' not in inspect.signature(get_riders_paginated).parameters
    assert 'tab' not in inspect.signature(get_rider).parameters
    dash = _must_read(Path(inspect.getfile(DashboardService)))
    assert 'count_live_no_plan_days' in dash
    assert 'from=no_plan' not in dash
    assert count_live_no_plan_days.__name__ == 'count_live_no_plan_days'


def test_pipeline_still_writes_manual_after_period_items() -> None:
    src = _must_read(Path(run_calc_pipeline.__code__.co_filename))
    period_at = src.index('CalcStage.period.value')
    manual_at = src.index('DetailSource.manual.value')
    assert period_at < manual_at
    assert 'DetailSource.manual.value' in src
    assert MANUAL_FIELDS[0] in FIELD_MAP
    text = _must_read(Path(inspect.getfile(PlanService)))
    assert 'assert_threshold_price_period_items_xor' in text
    assert 'ops-plan-threshold-xor' not in NAMED


def test_cycle5_named_specs_exist() -> None:
    root = Path(__file__).resolve().parents[5] / 'scripts' / 'cdp' / 'specs'
    for name in NAMED:
        path = root / f'{name}.spec.mjs'
        assert path.is_file(), f'具名 spec 缺失 {name}，不得 skip'
        text = path.read_text(encoding='utf-8')
        assert f"export const name = '{name}'" in text
        assert '不得 skip' in text
        assert 'requireHooks' in text or 'requireTestId' in text


def test_existing_cycle2_payslip_hooks_still_in_ui() -> None:
    expected = _load('cdp-admin-payslip-hide-empty-days')['expected']
    detail = _must_read(UI_PLUGIN / 'views' / 'payroll' / 'detail.vue')
    assert f'data-testid="{expected["testid_layers"]}"' in detail
    assert f'data-testid="{expected["testid_recon"]}"' in detail
    assert f'data-testid="{expected["testid_tabs"]}"' in detail
    assert 'dailies' in detail
    rider = _must_read(UI_PLUGIN / 'views' / 'rider' / 'index.vue')
    assert 'tab=binding' in rider or "tab: 'binding'" in rider or 'query.tab' in rider
    attention = _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'components' / 'AttentionList.vue')
    assert 'no_plan_days' in attention
    calendar = _must_read(UI_PLUGIN / 'views' / 'calendar' / 'components' / 'DayCell.vue')
    assert 'calendar-bind-plan' in calendar


def test_status_hooks_fail_closed_when_landed() -> None:
    hooks = _status_hooks()
    sources = [
        _must_read(UI_PLUGIN / 'views' / 'payroll' / 'detail.vue'),
        _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'components' / 'AttentionList.vue'),
        _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'scope-links.ts'),
        _must_read(UI_PLUGIN / 'views' / 'plan' / 'helpers.ts'),
        _must_read(UI_PLUGIN / 'views' / 'plan' / 'components' / 'FormulaBuilder.vue'),
        _must_read(UI_PLUGIN / 'views' / 'plan' / 'components' / 'ConditionBuilder.vue'),
        _must_read(UI_PLUGIN / 'views' / 'plan' / 'components' / 'ExpressionBuilder.vue'),
        _must_read(UI_PLUGIN / 'views' / 'rider' / 'detail.vue'),
        _must_read(UI_PLUGIN / 'views' / 'rider' / 'index.vue'),
        _must_read(UI_PLUGIN / 'views' / 'rider' / 'components' / 'BindingPanel.vue'),
    ]
    blob = '\n'.join(sources)
    required = list(PR30_PAYSLIP_IDS) + list(PR30_BINDING_IDS) + list(PR30_MANUAL_IDS)
    missing = [name for name in required if name not in blob]
    assert not missing, f'#30 具名钩子缺失即失败，不得 skip：{missing}'
    extra = [name for name in hooks if name not in blob]
    assert not extra, f'status 已落地钩子缺失即失败，不得 skip：{extra}'


def test_cycle5_does_not_touch_advance_quota_or_fba() -> None:
    empty = json.dumps(_load('cdp-admin-payslip-hide-empty-days'), ensure_ascii=False)
    bind = json.dumps(_load('ops-dashboard-no-plan-to-binding'), ensure_ascii=False)
    manual = json.dumps(_load('ops-plan-manual-not-double'), ensure_ascii=False)
    for blob in (empty, bind, manual):
        assert 'advance_limit_count' not in blob
        assert 'PluginNotice' not in blob
        assert '个税' not in blob
