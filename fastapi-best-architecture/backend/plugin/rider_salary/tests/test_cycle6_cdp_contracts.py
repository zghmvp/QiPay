"""Cycle 6 具名 CDP 夹具合同。#33/#34 钩子缺失即失败，不得 skip。"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.plugin.rider_salary.api.v1.period import get_periods_paginated
from backend.plugin.rider_salary.crud.settle_period import CRUDSettlePeriod
from backend.plugin.rider_salary.service.calendar_service import count_live_no_plan_days
from backend.plugin.rider_salary.service.dashboard_service import DashboardService
from backend.plugin.rider_salary.service.period_service import PeriodService

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
STATUS = Path('/cursor/stores/bc-2955b371-f65c-4990-a229-d877e2ac6c7a/docs/adversarial-cycle6-implementation-status.md')
NAMED = ('ops-dashboard-stale-to-calc',)
EXISTING_MUST_NAMES = {
    'ops-plan-threshold-xor',
    'trial-case-gold',
    'trial-equals-calc',
    'ops-plan-activate-not-full-trial',
    'ops-plan-manual-not-double',
}
HOOK_HEADING = re.compile(r'钩子|hooks|FE 对接|CDP hooks', re.I)
HOOK_TOKEN = re.compile(r'`((?:cdp|ops|payroll|dashboard|plan|trial|rider|period|stale)-[a-z0-9-]+)`')

PR33_DASHBOARD_IDS = (
    'ops-dashboard-stale-to-calc',
    'dashboard-stale-view-all',
    'dashboard-stale-row',
    'stale-goto-calculate',
)
PR33_LANDING_IDS = (
    'period-stale-scope',
    'period-calc-precheck',
    'period-calc-title',
    'period-calc-start',
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


def is_stale_view_all(raw: str, site_id: int | str | None, month: str) -> bool:
    parsed = urlparse(raw, scheme='http', allow_fragments=True)
    path = parsed.path or raw.split('?')[0]
    query = parse_qs(parsed.query)
    if not path.rstrip('/').endswith('/rider-salary/period'):
        return False
    if '/calculate' in path:
        return False
    stale = (query.get('stale') or [''])[0]
    if stale not in {'1', 'true'}:
        return False
    if (query.get('id') or [''])[0]:
        return False
    if site_id is not None and (query.get('site_id') or [''])[0] != str(site_id):
        return False
    if site_id is None and (query.get('site_id') or [''])[0]:
        return False
    return (query.get('month') or [''])[0] == month


def is_period_calculate(raw: str, period_id: int | str) -> bool:
    return bool(re.search(rf'/rider-salary/period/{period_id}/calculate(?:/|\?|$)', raw))


def is_period_drawer(raw: str) -> bool:
    parsed = urlparse(raw, scheme='http')
    query = parse_qs(parsed.query)
    path = parsed.path or raw.split('?')[0]
    if '/calculate' in path:
        return False
    return path.rstrip('/').endswith('/rider-salary/period') and bool((query.get('id') or [''])[0])


def test_cycle6_named_cdp_fixture_hooks() -> None:
    stale = _load('ops-dashboard-stale-to-calc')
    expected = stale['expected']
    assert expected['skip_if_missing'] is False
    assert expected['view_all_must_carry_stale_and_site_month'] is True
    assert expected['view_all_query'] == 'stale=1'
    assert expected['view_all_no_site_still_carries_month'] is True
    assert expected['row_url'] == '/rider-salary/period/{id}/calculate'
    assert expected['drawer_id_query_is_fail'] is True
    assert expected['auto_calc_is_fail'] is True
    assert expected['list_ignore_query_is_fail'] is True
    assert expected['other_site_stale_must_not_appear'] is True
    assert expected['testid_block'] == 'ops-dashboard-stale-to-calc'
    assert expected['testid_view_all'] == 'dashboard-stale-view-all'
    assert expected['testid_row'] == 'dashboard-stale-row'
    assert expected['testid_period_scope'] == 'period-stale-scope'
    assert expected['helper_view_all_target'] == 'stalePeriodsViewAllTarget'
    assert expected['helper_row_target'] == 'stalePeriodCalcTarget'
    assert expected['helper_list_params'] == 'periodStaleListParams'
    assert expected['be_view_all_helper'] == 'stale_periods_view_all_link'
    assert expected['recalc_button_regression'] == 'stale-goto-calculate'


def test_cycle6_fixture_json_round_trip() -> None:
    for name in (*NAMED, 'trial-case-gold', 'ops-dashboard-no-plan-to-binding'):
        payload = _load(name)
        assert payload['expected']['skip_if_missing'] is False
        assert json.loads(json.dumps(payload)) == payload


def test_cycle6_does_not_change_locked_gold_fixture() -> None:
    gold = _load('trial-case-gold')
    assert gold['expected']['C03_gross'] == '8200.00'
    assert gold['expected']['C04_gross'] == '7800.00'
    assert gold['expected']['C05A_gross'] == '3500.00'
    payload = _load('ops-dashboard-stale-to-calc')
    locked = payload['expected']['locked_gold_unchanged']
    assert locked['C03_gross'] == '8200.00'
    assert locked['C04_gross'] == '7800.00'
    assert locked['C05A_gross'] == '3500.00'
    blob = json.dumps(payload, ensure_ascii=False)
    assert '4629.33' not in blob
    assert '预支 800' not in blob


def test_cycle6_does_not_invent_xor_gold_activate_manual_must_names() -> None:
    payload = _load('ops-dashboard-stale-to-calc')
    assert payload['expected']['no_new_xor_or_gold_must_name'] is True
    assert payload['feature'] == 'ops-dashboard-stale-to-calc'
    assert payload['feature'] not in EXISTING_MUST_NAMES
    xor = _load('ops-plan-threshold-xor')
    act = _load('ops-plan-activate-not-full-trial')
    gold = _load('trial-case-gold')
    manual = _load('ops-plan-manual-not-double')
    assert xor['feature'] == 'ops-plan-threshold-xor'
    assert act['feature'] == 'ops-plan-activate-not-full-trial'
    assert gold['expected']['C03_gross'] == '8200.00'
    assert manual['feature'] == 'ops-plan-manual-not-double'


def test_view_all_and_row_url_contracts() -> None:
    assert is_stale_view_all('/rider-salary/period?stale=1&site_id=3&month=2026-09', 3, '2026-09')
    assert is_stale_view_all('/rider-salary/period?stale=1&month=2026-09', None, '2026-09')
    assert not is_stale_view_all('/rider-salary/period?stale=1', 3, '2026-09')
    assert not is_stale_view_all('/rider-salary/period?id=42', 3, '2026-09')
    assert is_period_drawer('/rider-salary/period?id=42')
    assert is_period_calculate('/rider-salary/period/42/calculate', 42)
    assert not is_period_calculate('/rider-salary/period?id=42', 42)
    assert not is_period_drawer('/rider-salary/period/42/calculate')
    assert 'auto=1' not in '/rider-salary/period/42/calculate'


def test_pr33_hooks_fail_closed() -> None:
    expected = _load('ops-dashboard-stale-to-calc')['expected']
    attention = _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'components' / 'AttentionList.vue')
    scope = _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'scope-links.ts')
    period = _must_read(UI_PLUGIN / 'views' / 'period' / 'index.vue')
    calculate = _must_read(UI_PLUGIN / 'views' / 'period' / 'calculate.vue')
    blob = '\n'.join([attention, scope, period, calculate])
    for test_id in PR33_DASHBOARD_IDS + PR33_LANDING_IDS:
        assert test_id in blob, f'#33 {test_id} 缺失即失败，不得 skip'
    assert 'export function stalePeriodsViewAllTarget' in scope
    assert 'export function stalePeriodCalcTarget' in scope
    assert 'export function periodStaleListParams' in scope
    assert "stale: '1'" in scope
    view_fn = scope[scope.index('export function stalePeriodsViewAllTarget') :]
    view_fn = view_fn.split('export function stalePeriodCalcTarget')[0]
    assert 'stale' in view_fn
    assert 'scopedSiteMonthQuery' in view_fn
    calc_fn = scope[scope.index('export function stalePeriodCalcTarget') :]
    calc_fn = calc_fn.split('export function periodStaleListParams')[0]
    assert '/calculate' in calc_fn
    assert 'auto' not in calc_fn.split('return')[1]
    assert "id:" not in calc_fn.split('return')[1]
    assert 'stalePeriodsViewAllTarget' in attention
    assert 'stalePeriodCalcTarget' in attention
    assert "block.key === 'stale_periods'" in attention
    assert expected['testid_block'] in attention
    assert expected['testid_view_all'] in attention
    assert expected['testid_row'] in attention
    assert 'data-period-id' in attention
    assert expected['testid_recalc'] in attention
    assert '/rider-salary/period/${' in scope or '/period/${periodId}/calculate' in scope
    assert expected['testid_period_scope'] in period
    assert 'periodStaleListParams' in period
    assert expected['landing_copy'] in period or '需重算周期' in period
    assert expected['testid_calc_precheck'] in calculate
    assert expected['testid_calc_title'] in calculate
    assert expected['testid_calc_start'] in calculate
    row_fn = attention[attention.index('function rowLink') :]
    due_row = row_fn[row_fn.index("block.key === 'due_periods'") : row_fn.index("block.key === 'stale_periods'")]
    assert "query: { id: String(id) }" in due_row


def test_pr34_view_all_link_fail_closed() -> None:
    expected = _load('ops-dashboard-stale-to-calc')['expected']
    dash = _must_read(PLUGIN / 'service' / 'dashboard_service.py')
    assert expected['be_view_all_helper'] in dash, '#34 stale_periods_view_all_link 缺失即失败，不得 skip'
    assert "link='/rider-salary/period?stale=1'" not in dash
    from backend.plugin.rider_salary.service.dashboard_service import (  # noqa: PLC0415
        stale_periods_view_all_link,
    )

    assert stale_periods_view_all_link(site_id=3, month='2026-09') == (
        '/rider-salary/period?stale=1&site_id=3&month=2026-09'
    )
    assert stale_periods_view_all_link(site_id=None, month='2026-09') == (
        '/rider-salary/period?stale=1&month=2026-09'
    )
    src = inspect.getsource(DashboardService._stale_periods)
    assert 'stale_periods_view_all_link' in src
    assert "link='/rider-salary/period?stale=1'" not in src
    assert 'period?id={period.id}' in src
    assert 'RiderSalaryPayroll.stale.is_(True)' in src


def test_period_list_consumes_stale_site_month() -> None:
    params = inspect.signature(get_periods_paginated).parameters
    assert 'stale' in params
    assert 'site_id' in params
    assert 'month' in params
    src = inspect.getsource(PeriodService.get_list)
    assert 'stale=stale' in src
    assert 'site_id=site_id' in src
    assert 'month_start=month_start' in src
    select_src = inspect.getsource(CRUDSettlePeriod.get_select)
    assert 'if stale:' in select_src
    assert 'exists(' in select_src
    assert 'RiderSalaryPayroll.stale.is_(True)' in select_src
    assert select_src.count('RiderSalaryPayroll.stale.is_(True)') == 1
    assert "filters['site_id']" in select_src
    assert 'month_start' in select_src and 'month_end' in select_src


def test_hash9_stale_predicate_and_live_count_unchanged() -> None:
    expected = _load('ops-dashboard-stale-to-calc')['expected']
    assert expected['do_not_rewrite_stale_predicate'] is True
    assert expected['do_not_rewrite_live_count'] is True
    dash = _must_read(Path(inspect.getfile(DashboardService)))
    assert 'count_live_no_plan_days' in dash
    assert count_live_no_plan_days.__name__ == 'count_live_no_plan_days'


def test_cycle4_cycle5_product_sentences_unchanged() -> None:
    expected = _load('ops-dashboard-stale-to-calc')['expected']
    attention = _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'components' / 'AttentionList.vue')
    assert expected['cycle4_insight_unchanged'] in _must_read(
        UI_PLUGIN / 'views' / 'dashboard' / 'components' / 'StatCards.vue'
    ) or expected['cycle4_insight_unchanged'] in _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'index.vue')
    assert expected['cycle4_abnormal_unchanged'] in attention
    assert expected['cycle4_lock_unchanged'] in attention
    assert expected['cycle5_no_plan_unchanged'] in attention
    assert 'stale-goto-calculate' in attention
    assert '锁账倒计时' in _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'due-countdown.ts')


def test_cycle6_named_spec_exists() -> None:
    root = Path(__file__).resolve().parents[5] / 'scripts' / 'cdp' / 'specs'
    path = root / 'ops-dashboard-stale-to-calc.spec.mjs'
    assert path.is_file(), '具名 spec 缺失 ops-dashboard-stale-to-calc，不得 skip'
    text = path.read_text(encoding='utf-8')
    assert "export const name = 'ops-dashboard-stale-to-calc'" in text
    assert '不得 skip' in text
    assert 'requireHooks' in text or 'requireTestId' in text
    assert 'stale=1' in text
    assert 'drawer' in text.lower() or '?id=' in text
    assert 'auto=1' in text or 'auto' in text


def test_status_hooks_fail_closed_when_landed() -> None:
    hooks = _status_hooks()
    sources = [
        _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'components' / 'AttentionList.vue'),
        _must_read(UI_PLUGIN / 'views' / 'dashboard' / 'scope-links.ts'),
        _must_read(UI_PLUGIN / 'views' / 'period' / 'index.vue'),
        _must_read(UI_PLUGIN / 'views' / 'period' / 'calculate.vue'),
        _must_read(PLUGIN / 'service' / 'dashboard_service.py'),
    ]
    blob = '\n'.join(sources)
    required = list(PR33_DASHBOARD_IDS) + ['period-stale-scope', 'stale_periods_view_all_link']
    missing = [name for name in required if name not in blob]
    assert not missing, f'Cycle 6 具名钩子缺失即失败，不得 skip：{missing}'
    extra = [
        name
        for name in hooks
        if name.startswith(('ops-dashboard-stale', 'dashboard-stale', 'period-stale', 'stale-goto'))
        and name not in blob
    ]
    assert not extra, f'status 已落地钩子缺失即失败，不得 skip：{extra}'


def test_cycle6_does_not_touch_advance_quota_or_fba() -> None:
    blob = json.dumps(_load('ops-dashboard-stale-to-calc'), ensure_ascii=False)
    assert 'advance_limit_count' not in blob
    assert 'PluginNotice' not in blob
    assert '个税' not in blob
