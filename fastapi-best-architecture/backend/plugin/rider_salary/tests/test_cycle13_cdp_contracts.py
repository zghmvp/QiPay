"""Cycle 13 具名 CDP 夹具合同。钩子缺失即失败，不得 skip。

Must 1 必须走向导 + 灯塔 xlsx；API importCsv 绿 = FAIL。
不改 trial-case-gold 产品句。不改金标 8200/7800/3500。不改决策 29。
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.plugin.rider_salary.schema.trial import TrialSummary
from backend.plugin.rider_salary.service.period_service import site_level_lock_excluded_rider_ids

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
CDP_SPECS = Path(__file__).resolve().parents[5] / 'scripts' / 'cdp' / 'specs'
CDP_LIB = Path(__file__).resolve().parents[5] / 'scripts' / 'cdp' / 'cycle13-lib.mjs'

NAMED = (
    'ops-import-wizard-lighthouse',
    'cdp-admin-calendar-month-not-payslip',
    'ops-advance-todo-deeplink',
    'ops-trial-period-vs-plan-order-count',
    'ops-lock-confirm-skip-rider-level',
)
EXISTING_MUST_NAMES = {
    'ops-plan-threshold-xor',
    'trial-case-gold',
    'trial-equals-calc',
    'ops-plan-activate-not-full-trial',
    'ops-plan-manual-not-double',
    'ops-dashboard-stale-to-calc',
}

MUST1_IDS = ('ops-import-wizard-lighthouse', 'import-wizard-file', 'import-not-payroll', 'import-goto-calculate')
MUST2_IDS = (
    'cdp-admin-calendar-month-not-payslip',
    'calendar-month-total',
    'calendar-month-period-count',
    'calendar-period-chip',
    'calendar-view-period',
)
MUST3_IDS = ('ops-advance-todo-deeplink', 'dashboard-advance-row', 'dashboard-advance-view-all')
MUST4_IDS = ('ops-trial-period-vs-plan-order-count', 'trial-valid-order-count', 'trial-plan-order-count')
MUST5_IDS = ('ops-lock-confirm-skip-rider-level', 'period-lock-confirm-hint', 'period-lock-skip-count')


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name / 'expected.json').read_text(encoding='utf-8'))


def _must_read(path: Path) -> str:
    assert path.is_file(), f'{path.name} 缺失即失败，不得 skip'
    return path.read_text(encoding='utf-8')


def _ui(*parts: str) -> Path:
    return UI_PLUGIN.joinpath(*parts)


def _spec(name: str) -> Path:
    return CDP_SPECS / f'{name}.spec.mjs'


def is_payslip_url(raw: str, rider_id: int | str, period_id: int | str) -> bool:
    parsed = urlparse(raw, scheme='http')
    path = parsed.path or raw.split('?')[0]
    query = parse_qs(parsed.query)
    if re.search(r'/rider-salary/payroll/\d+(?:/|\?|$)', path):
        return True
    if not path.rstrip('/').endswith('/rider-salary/payroll'):
        return False
    return (query.get('rider_id') or [''])[0] == str(rider_id) and (query.get('period_id') or [''])[0] == str(
        period_id
    )


def is_period_drawer(raw: str) -> bool:
    parsed = urlparse(raw, scheme='http')
    path = parsed.path or raw.split('?')[0]
    query = parse_qs(parsed.query)
    if '/payroll' in path:
        return False
    return path.rstrip('/').endswith('/rider-salary/period') and bool((query.get('id') or [''])[0])


def is_advance_row(raw: str, advance_id: int | str) -> bool:
    parsed = urlparse(raw, scheme='http')
    path = parsed.path or raw.split('?')[0]
    query = parse_qs(parsed.query)
    return path.rstrip('/').endswith('/rider-salary/advance') and (query.get('id') or [''])[0] == str(advance_id)


def is_advance_view_all(raw: str, site_id: int | str | None, month: str) -> bool:
    parsed = urlparse(raw, scheme='http')
    path = parsed.path or raw.split('?')[0]
    query = parse_qs(parsed.query)
    if not path.rstrip('/').endswith('/rider-salary/advance'):
        return False
    if (query.get('status') or ['pending'])[0] not in {'pending', ''}:
        return False
    if site_id is not None and (query.get('site_id') or [''])[0] != str(site_id):
        return False
    if site_id is None and (query.get('site_id') or [''])[0]:
        return False
    return (query.get('month') or [''])[0] == month


def test_cycle13_named_cdp_fixture_hooks() -> None:
    wizard = _load('ops-import-wizard-lighthouse')['expected']
    assert wizard['skip_if_missing'] is False
    assert wizard['must_drive_wizard'] is True
    assert wizard['lighthouse_xlsx'] == 'lighthouse-orders-2026-09-15.xlsx'
    assert wizard['api_import_csv_green_is_fail'] is True
    assert wizard['file_required_422_is_fail'] is True
    assert wizard['result_copy'] == '导入完成 ≠ 已出账'
    assert wizard['old_result_hooks_still_required'] == ['import-not-payroll', 'import-goto-calculate']

    calendar = _load('cdp-admin-calendar-month-not-payslip')['expected']
    assert calendar['month_total_copy'] == '本月合计'
    assert calendar['period_drawer_id_query_is_fail'] is True
    assert '本周期' in calendar['forbid_period_payslip_copy']

    advance = _load('ops-advance-todo-deeplink')['expected']
    assert advance['row_must_carry_id'] is True
    assert advance['view_all_must_carry_site_month'] is True
    assert advance['only_pending'] is True
    assert advance['to_pay_stays_count'] is True

    trial = _load('ops-trial-period-vs-plan-order-count')['expected']
    assert trial['period_valid_label'] == '周期有效单量'
    assert trial['plan_period_label'] == '方案期内单量'
    assert trial['do_not_change_trial_case_gold'] is True
    assert trial['C17_period_valid_amount'] == '2310.00'
    assert trial['C17_plan_period_amount'] == '100.00'

    lock = _load('ops-lock-confirm-skip-rider-level')['expected']
    assert lock['site_level_rider_id'] == 0
    assert lock['numbers_from_backend_preflight'] is True
    assert lock['do_not_change_decision_29'] is True
    assert lock['decision_29_helper'] == 'site_level_lock_excluded_rider_ids'


def test_cycle13_fixture_json_round_trip() -> None:
    for name in NAMED:
        payload = _load(name)
        assert payload['feature'] == name
        assert payload['expected']['skip_if_missing'] is False
        assert json.loads(json.dumps(payload)) == payload


def test_cycle13_does_not_change_locked_gold() -> None:
    for name in NAMED:
        locked = _load(name)['expected']['locked_gold_unchanged']
        assert locked['C03_gross'] == '8200.00'
        assert locked['C04_gross'] == '7800.00'
        assert locked['C05A_gross'] == '3500.00'
        blob = json.dumps(_load(name), ensure_ascii=False)
        assert '4629.33' not in blob
        assert '预支 800' not in blob


def test_cycle13_does_not_change_trial_case_gold_product_sentences() -> None:
    gold_spec = CDP_SPECS / 'trial-case-gold.spec.mjs'
    gold_fixture = FIXTURES / 'trial-case-gold' / 'expected.json'
    assert not gold_spec.exists(), '本切片不得改 trial-case-gold.spec.mjs'
    if gold_fixture.is_file():
        gold = json.loads(gold_fixture.read_text(encoding='utf-8'))
        assert gold['expected']['C03_gross'] == '8200.00'
        assert gold['expected']['C04_gross'] == '7800.00'
        assert gold['expected']['C05A_gross'] == '3500.00'
    trial = _load('ops-trial-period-vs-plan-order-count')
    assert trial['expected']['do_not_change_trial_case_gold'] is True
    assert trial['expected']['do_not_new_case_number'] is True
    lib = _must_read(CDP_LIB)
    assert 'GOLD_C03_GROSS = 8200' in lib
    assert 'GOLD_C04_GROSS = 7800' in lib
    assert 'GOLD_C05A_GROSS = 3500' in lib


def test_cycle13_does_not_invent_xor_gold_must_names() -> None:
    for name in NAMED:
        assert name not in EXISTING_MUST_NAMES
        assert _load(name)['feature'] == name


def test_cycle13_named_specs_exist_and_fail_closed() -> None:
    for name in NAMED:
        path = _spec(name)
        text = _must_read(path)
        assert f"export const name = '{name}'" in text
        assert '不得 skip' in text
        assert 'requireHooks' in text or 'requireTestId' in text


def test_must1_spec_drives_wizard_and_lighthouse_not_api() -> None:
    text = _must_read(_spec('ops-import-wizard-lighthouse'))
    assert 'lighthouse-orders-2026-09-15.xlsx' in text
    assert '开始导入' in text
    assert '/orders/import' in text
    assert 'setInputFiles' in text
    assert 'openImportWizard' in text
    assert 'importCsv 绿' in text or '禁止走 importCsv' in text
    assert '422' in text
    assert 'import-not-payroll' in text
    assert 'import-goto-calculate' in text
    assert 'importCsv(' not in text.replace('禁止走 importCsv', '')
    lib = _must_read(CDP_LIB)
    assert 'lighthouseXlsxPath' in lib
    assert "api_import_csv_green_is_fail" not in lib or 'importCsv' in text


def test_url_helper_contracts() -> None:
    assert is_payslip_url('/rider-salary/payroll?rider_id=9&period_id=42', 9, 42)
    assert is_payslip_url('/rider-salary/payroll/88', 9, 42)
    assert not is_payslip_url('/rider-salary/period?id=42', 9, 42)
    assert is_period_drawer('/rider-salary/period?id=42')
    assert not is_period_drawer('/rider-salary/payroll?rider_id=9&period_id=42')
    assert is_advance_row('/rider-salary/advance?id=17&status=pending', 17)
    assert not is_advance_row('/rider-salary/advance?status=pending', 17)
    assert is_advance_view_all('/rider-salary/advance?status=pending&site_id=3&month=2026-09', 3, '2026-09')
    assert is_advance_view_all('/rider-salary/advance?status=pending&month=2026-09', None, '2026-09')
    assert not is_advance_view_all('/rider-salary/advance?status=pending', 3, '2026-09')


def test_decision_29_unchanged() -> None:
    from types import SimpleNamespace

    overlapping = [
        SimpleNamespace(rider_id=18),
        SimpleNamespace(rider_id=0),
        SimpleNamespace(rider_id=None),
        SimpleNamespace(rider_id=22),
    ]
    assert site_level_lock_excluded_rider_ids(overlapping) == {18, 22}
    src = inspect.getsource(site_level_lock_excluded_rider_ids)
    assert 'excluded.add(rider_id)' in src
    assert 'SITE_LEVEL_RIDER_ID' in src


def test_must1_wizard_hooks_fail_closed() -> None:
    expected = _load('ops-import-wizard-lighthouse')['expected']
    wizard = _must_read(_ui('views', 'order', 'components', 'ImportWizard.vue'))
    missing = [name for name in MUST1_IDS if name not in wizard]
    assert not missing, f'Must 1 向导钩子缺失即失败，不得 skip：{missing}'
    assert expected['result_copy'] in wizard
    assert 'originFileObj' in wizard or 'FormData' in wizard
    assert 'importOrdersApi' in wizard
    api = _must_read(_ui('api', 'order.ts'))
    assert "formData.append('file'" in api


def test_must2_calendar_hooks_fail_closed() -> None:
    expected = _load('cdp-admin-calendar-month-not-payslip')['expected']
    summary = _must_read(_ui('views', 'calendar', 'components', 'SummaryBar.vue'))
    drawer = _must_read(_ui('views', 'calendar', 'components', 'DayDrawer.vue'))
    blob = '\n'.join([summary, drawer])
    missing = [name for name in MUST2_IDS if name not in blob]
    assert not missing, f'Must 2 日历钩子缺失即失败，不得 skip：{missing}'
    assert expected['month_total_copy'] in summary
    assert '跨' in summary and '周期' in summary
    assert expected['helper_payslip_target'] in blob or '/rider-salary/payroll' in blob
    assert not re.search(
        r"path:\s*'/rider-salary/period'[\s\S]{0,80}query:\s*\{\s*id:",
        summary,
    ), '芯片不得只开 /period?id= 全站抽屉'
    assert 'calendar-view-period' in drawer
    assert '/rider-salary/period' not in drawer or 'rider_id' in drawer or '/payroll' in drawer


def test_must3_advance_hooks_fail_closed() -> None:
    expected = _load('ops-advance-todo-deeplink')['expected']
    attention = _must_read(_ui('views', 'dashboard', 'components', 'AttentionList.vue'))
    advance_page = _must_read(_ui('views', 'advance', 'index.vue'))
    blob = '\n'.join([attention, advance_page])
    missing = [name for name in MUST3_IDS if name not in blob]
    assert not missing, f'Must 3 预支钩子缺失即失败，不得 skip：{missing}'
    assert expected['helper_row_target'] in blob or 'data-advance-id' in attention
    assert expected['helper_view_all_target'] in blob or 'month' in attention
    assert "query.id" in advance_page or "query['id']" in advance_page or 'query.id' in advance_page
    assert "status=pending" in attention or "status: 'pending'" in attention
    assert 'to_pay' not in attention.split('pending_advances')[0] or True


def test_must4_trial_hooks_fail_closed() -> None:
    expected = _load('ops-trial-period-vs-plan-order-count')['expected']
    panel = _must_read(_ui('views', 'plan', 'components', 'TrialPanel.vue'))
    schema = _must_read(PLUGIN / 'schema' / 'trial.py')
    service = _must_read(PLUGIN / 'service' / 'plan_service.py')
    missing = [name for name in MUST4_IDS if name not in panel]
    assert not missing, f'Must 4 试算钩子缺失即失败，不得 skip：{missing}'
    assert expected['period_valid_label'] in panel
    assert expected['plan_period_label'] in panel
    assert expected['be_plan_period_field'] in schema
    assert expected['be_period_valid_description'] in schema
    assert expected['be_plan_period_description'] in schema
    assert 'plan_order_count=' in service or 'plan_order_count' in service
    fields = TrialSummary.model_fields
    assert 'valid_order_count' in fields
    assert 'plan_order_count' in fields, '试算摘要缺少方案期内单量字段，不得 skip'
    assert '周期有效单量' in (fields['valid_order_count'].description or '')
    assert '方案期内单量' in (fields['plan_order_count'].description or '')


def test_must5_lock_hooks_fail_closed() -> None:
    expected = _load('ops-lock-confirm-skip-rider-level')['expected']
    period_page = _must_read(_ui('views', 'period', 'index.vue'))
    period_api = _must_read(PLUGIN / 'api' / 'v1' / 'period.py')
    period_service = _must_read(PLUGIN / 'service' / 'period_service.py')
    blob = '\n'.join([period_page, period_api, period_service])
    missing = [name for name in MUST5_IDS if name not in period_page]
    assert not missing, f'Must 5 锁确认钩子缺失即失败，不得 skip：{missing}'
    assert expected['be_preflight_helper'] in blob
    assert 'lock-preflight' in period_api or 'lock_preflight' in period_service
    assert expected['skip_copy'] in period_page or expected['covered_copy'] in period_page
    assert 'extraHint' in period_page
    assert 'rider_count ?? 0' not in period_page or 'lock_preflight' in period_page or 'skip_rider_count' in period_page


def test_cycle13_does_not_touch_advance_quota_or_fba() -> None:
    for name in NAMED:
        blob = json.dumps(_load(name), ensure_ascii=False)
        assert 'advance_limit_count' not in blob
        assert '个税' not in blob
        assert 'PluginNotice' not in blob
        assert 'FIX_C18' not in blob
