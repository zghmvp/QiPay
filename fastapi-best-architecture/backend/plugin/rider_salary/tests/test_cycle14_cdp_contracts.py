"""Cycle 14 具名 CDP 夹具合同。钩子缺失即失败，不得 skip。

Must 2 必须走工作台缺口行 → 向导预填该站该日；只进订单列表 / API importCsv 绿 = FAIL。
Must 4 必须走向导 + 跳过错误行；把本席写成「仍 422」= FAIL。
Must 5 不验收 Cycle 13 芯片 / 查看周期进条。
不改 trial-case-gold 产品句。不改金标 8200/7800/3500。不改 FBA。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
CDP_SPECS = Path(__file__).resolve().parents[5] / 'scripts' / 'cdp' / 'specs'
CDP_LIB = Path(__file__).resolve().parents[5] / 'scripts' / 'cdp' / 'cycle14-lib.mjs'
CDP_HARNESS = Path(__file__).resolve().parents[5] / 'scripts' / 'cdp' / 'harness.mjs'

NAMED = (
    'ops-due-stale-row-level-label',
    'ops-import-gap-wizard-that-day',
    'ops-abnormal-order-deeplink',
    'ops-import-skip-errors-not-all-success',
    'cdp-admin-day-drawer-not-daily-payslip',
)
EXISTING_MUST_NAMES = {
    'ops-plan-threshold-xor',
    'trial-case-gold',
    'trial-equals-calc',
    'ops-plan-activate-not-full-trial',
    'ops-plan-manual-not-double',
    'ops-dashboard-stale-to-calc',
    'ops-import-wizard-lighthouse',
    'cdp-admin-calendar-month-not-payslip',
    'ops-advance-todo-deeplink',
    'ops-trial-period-vs-plan-order-count',
    'ops-lock-confirm-skip-rider-level',
}

MUST1_IDS = (
    'ops-due-stale-row-level-label',
    'dashboard-due-row',
    'dashboard-stale-row',
    'dashboard-row-level',
    'dashboard-row-rider-name',
)
MUST2_IDS = (
    'ops-import-gap-wizard-that-day',
    'dashboard-import-gap-row',
    'import-wizard',
    'import-wizard-site',
    'import-wizard-date-from',
    'import-wizard-date-to',
)
MUST3_IDS = (
    'ops-abnormal-order-deeplink',
    'dashboard-abnormal-row',
    'dashboard-abnormal-view-all',
)
MUST3_LANDING_IDS = ('order-detail-open', 'order-row-active')
MUST4_IDS = (
    'ops-import-skip-errors-not-all-success',
    'import-skip-errors',
    'import-success-rows',
    'import-failed-rows',
    'import-error-report',
    'import-not-payroll',
)
MUST5_IDS = (
    'cdp-admin-day-drawer-not-daily-payslip',
    'day-drawer-formula-amount',
    'day-drawer-net',
    'day-drawer-period-not-daily',
)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name / 'expected.json').read_text(encoding='utf-8'))


def _must_read(path: Path) -> str:
    assert path.is_file(), f'{path.name} 缺失即失败，不得 skip'
    return path.read_text(encoding='utf-8')


def _read_optional(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def _ui(*parts: str) -> Path:
    return UI_PLUGIN.joinpath(*parts)


def _spec(name: str) -> Path:
    return CDP_SPECS / f'{name}.spec.mjs'


def _query(raw: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(raw, scheme='http').query)


def _path(raw: str) -> str:
    return urlparse(raw, scheme='http').path or raw.split('?')[0]


def landing_period_id(raw: str) -> str:
    path = _path(raw)
    calc = re.search(r'/rider-salary/period/(\d+)/calculate', path)
    if calc:
        return calc.group(1)
    detail = re.search(r'/rider-salary/period/(\d+)(?:/|$)', path)
    if detail:
        return detail.group(1)
    query = _query(raw)
    return (query.get('id') or query.get('period_id') or [''])[0]


def is_due_row_landing(raw: str, period_id: int | str) -> bool:
    path = _path(raw)
    if landing_period_id(raw) != str(period_id):
        return False
    if '/calculate' in path:
        return False
    return '/rider-salary/period' in path


def is_stale_row_landing(raw: str, period_id: int | str) -> bool:
    path = _path(raw)
    return landing_period_id(raw) == str(period_id) and bool(
        re.search(r'/rider-salary/period/\d+/calculate', path)
    )


def is_order_list_only_landing(raw: str) -> bool:
    return _path(raw).rstrip('/').endswith('/rider-salary/order')


def is_calendar_landing(raw: str) -> bool:
    return '/rider-salary/calendar' in _path(raw)


def is_import_gap_wizard_prefill(site_id, date, date_from, date_to) -> bool:
    if not date:
        return False
    return str(date_from) == str(date) and str(date_to) == str(date) and site_id is not None


def is_abnormal_row_landing(raw: str, order_id: int | str | None, order_no: str | None) -> bool:
    path = _path(raw)
    query = _query(raw)
    if '/rider-salary/order' not in path:
        return False
    if order_id is not None and (query.get('id') or [''])[0] == str(order_id):
        return True
    if order_no and (query.get('order_no') or [''])[0] == order_no:
        return True
    return False


def is_abnormal_view_all(raw: str, site_id: int | str | None, month: str) -> bool:
    path = _path(raw)
    query = _query(raw)
    if not path.rstrip('/').endswith('/rider-salary/order'):
        return False
    if (query.get('attention') or [''])[0] != '1':
        return False
    if site_id is not None and (query.get('site_id') or [''])[0] != str(site_id):
        return False
    from_ = (query.get('date_from') or query.get('month') or [''])[0]
    return from_.startswith(month) or (query.get('month') or [''])[0] == month


def is_day_drawer_not_daily_payslip(text: str) -> bool:
    return bool(re.search(r'周期项不落日|对账看条', text or ''))


def test_cycle14_named_cdp_fixture_hooks() -> None:
    due = _load('ops-due-stale-row-level-label')['expected']
    assert due['skip_if_missing'] is False
    assert due['site_level_copy'] == '站点级'
    assert due['same_range_unlabeled_is_fail'] is True
    assert due['other_period_id_is_fail'] is True
    assert due['do_not_change_decision_29'] is True

    gap = _load('ops-import-gap-wizard-that-day')['expected']
    assert gap['must_drive_dashboard_gap_row'] is True
    assert gap['must_open_existing_wizard'] is True
    assert gap['order_list_only_is_fail'] is True
    assert gap['api_import_csv_green_is_fail'] is True
    assert gap['q14_3_order_list_filter_not_enough'] is True

    abnormal = _load('ops-abnormal-order-deeplink')['expected']
    assert abnormal['row_must_carry_id_or_order_no'] is True
    assert abnormal['view_all_stays_attention_1_site_month'] is True
    assert abnormal['rewrite_attention_predicate_is_fail'] is True

    skip = _load('ops-import-skip-errors-not-all-success')['expected']
    assert skip['must_drive_wizard'] is True
    assert skip['must_check_skip_errors'] is True
    assert skip['writing_still_422_is_fail'] is True
    assert skip['all_success_copy_is_fail'] == '全部导入成功'
    assert skip['old_result_hooks_still_required'] == ['import-not-payroll']

    drawer = _load('cdp-admin-day-drawer-not-daily-payslip')['expected']
    assert drawer['assert_cycle13_chip_landing'] is False
    assert drawer['do_not_assert_calendar_period_chip'] is True
    assert '周期项不落日' in drawer['period_item_not_daily_copy']
    assert '对账看条' in drawer['period_item_not_daily_copy']


def test_cycle14_fixture_json_round_trip() -> None:
    for name in NAMED:
        payload = _load(name)
        assert payload['feature'] == name
        assert payload['expected']['skip_if_missing'] is False
        assert json.loads(json.dumps(payload)) == payload


def test_cycle14_does_not_change_locked_gold() -> None:
    for name in NAMED:
        locked = _load(name)['expected']['locked_gold_unchanged']
        assert locked['C03_gross'] == '8200.00'
        assert locked['C04_gross'] == '7800.00'
        assert locked['C05A_gross'] == '3500.00'
        blob = json.dumps(_load(name), ensure_ascii=False)
        assert '4629.33' not in blob
        assert '预支 800' not in blob


def test_cycle14_does_not_change_trial_case_gold_product_sentences() -> None:
    gold_spec = CDP_SPECS / 'trial-case-gold.spec.mjs'
    gold_fixture = FIXTURES / 'trial-case-gold' / 'expected.json'
    assert not gold_spec.exists(), '本切片不得改 trial-case-gold.spec.mjs'
    if gold_fixture.is_file():
        gold = json.loads(gold_fixture.read_text(encoding='utf-8'))
        assert gold['expected']['C03_gross'] == '8200.00'
        assert gold['expected']['C04_gross'] == '7800.00'
        assert gold['expected']['C05A_gross'] == '3500.00'
    lib = _must_read(CDP_LIB)
    assert 'GOLD_C03_GROSS = 8200' in lib
    assert 'GOLD_C04_GROSS = 7800' in lib
    assert 'GOLD_C05A_GROSS = 3500' in lib


def test_cycle14_does_not_invent_old_must_names() -> None:
    for name in NAMED:
        assert name not in EXISTING_MUST_NAMES
        assert _load(name)['feature'] == name
    harness = _must_read(CDP_HARNESS)
    for name in NAMED:
        assert name in harness
    assert harness.count('export const name') == 0


def test_cycle14_named_specs_exist_and_fail_closed() -> None:
    for name in NAMED:
        path = _spec(name)
        text = _must_read(path)
        assert f"export const name = '{name}'" in text
        assert '不得 skip' in text
        assert 'requireHooks' in text or 'requireTestId' in text


def test_must1_spec_labels_site_vs_rider_and_keeps_period_id() -> None:
    text = _must_read(_spec('ops-due-stale-row-level-label'))
    assert '站点级' in text
    assert 'dashboard-due-row' in text
    assert 'dashboard-stale-row' in text
    assert 'period_id' in text
    assert '另一条' in text
    assert 'requireHooks' in text
    lib = _must_read(CDP_LIB)
    assert 'isDueRowLanding' in lib
    assert 'isStaleRowLanding' in lib


def test_must2_spec_drives_gap_row_to_wizard_not_order_list_or_api() -> None:
    text = _must_read(_spec('ops-import-gap-wizard-that-day'))
    assert '导入覆盖缺口' in text
    assert 'dashboard-import-gap-row' in text
    assert 'import-wizard' in text
    assert 'date_from' in text or 'dateFrom' in text
    assert 'date_to' in text or 'dateTo' in text
    assert 'waitWizardOpen' in text
    assert 'MUST2_WIZARD_HOOKS' in text or 'import-wizard-date-from' in text
    assert 'importCsv(' not in text.replace('禁止走 importCsv', '').replace('禁止 API importCsv', '')
    assert '订单空列表' in text or '只进订单' in text
    assert '/calendar' in text
    assert 'openImportWizard' not in text
    lib = _must_read(CDP_LIB)
    assert 'isOrderListOnlyLanding' in lib
    assert 'isImportGapWizardPrefill' in lib
    assert 'assertNoImportCsvGreen' in lib


def test_must3_spec_deeplinks_this_order() -> None:
    text = _must_read(_spec('ops-abnormal-order-deeplink'))
    assert 'dashboard-abnormal-row' in text
    assert 'data-order-id' in text or 'order_no' in text
    assert 'attention=1' in text or 'attention' in text
    assert 'order-detail-open' in text
    assert '缺送达' not in text or '不得' in text


def test_must4_spec_drives_wizard_skip_errors_not_still_422() -> None:
    text = _must_read(_spec('ops-import-skip-errors-not-all-success'))
    assert '跳过错误行' in text
    assert '全部导入成功' in text
    assert 'failed_rows' in text or 'import-failed-rows' in text
    assert 'import-success-rows' in text
    assert 'import-error-report' in text
    assert 'import-not-payroll' in text
    assert 'openImportWizard' in text
    assert 'setInputFiles' in text
    assert 'skip-errors-half-success.csv' in text or 'assertSkipErrorsCsvExists' in text
    assert '仍 422' in text
    assert '把本席写成「仍 422」= FAIL' in text or '写成「仍 422」= FAIL' in text
    assert 'FILE_REQUIRED_422' not in text
    assert 'file 字段为必填项' not in text
    assert 'importCsv(' not in text.replace('禁止走 importCsv', '').replace('禁止改走 importCsv', '')
    lib = _must_read(CDP_LIB)
    assert 'assertHalfSuccessVisible' in lib
    assert 'SKIP_ERRORS_CSV_NAME' in lib


def test_must5_spec_does_not_assert_cycle13_chip_landing() -> None:
    text = _must_read(_spec('cdp-admin-day-drawer-not-daily-payslip'))
    assert '周期项不落日' in text
    assert '对账看条' in text
    assert '公式金额' in text
    assert '净额' in text
    assert 'calendar-period-chip' not in text
    assert 'calendar-view-period' not in text
    assert 'assertChipGoesToPayslip' not in text
    assert '/payroll?rider_id=' not in text
    assert '芯片' in text and '不验收' in text
    expected = _load('cdp-admin-day-drawer-not-daily-payslip')['expected']
    assert expected['assert_cycle13_chip_landing'] is False


def test_url_helper_contracts() -> None:
    assert is_due_row_landing('/rider-salary/period?id=141001', 141001)
    assert not is_due_row_landing('/rider-salary/period/141002/calculate', 141001)
    assert not is_due_row_landing('/rider-salary/period?id=141002', 141001)
    assert is_stale_row_landing('/rider-salary/period/141002/calculate', 141002)
    assert not is_stale_row_landing('/rider-salary/period?id=141002', 141002)
    assert is_order_list_only_landing('/rider-salary/order?site_id=13&date=2026-09-12')
    assert is_calendar_landing('/rider-salary/calendar?rider_id=9')
    assert is_import_gap_wizard_prefill(13, '2026-09-12', '2026-09-12', '2026-09-12')
    assert not is_import_gap_wizard_prefill(13, '2026-09-12', '2026-09-01', '2026-09-30')
    assert is_abnormal_row_landing('/rider-salary/order?id=141003', 141003, 'C14-ABN-001')
    assert is_abnormal_row_landing('/rider-salary/order?order_no=C14-ABN-001', 141003, 'C14-ABN-001')
    assert not is_abnormal_row_landing('/rider-salary/order?attention=1&month=2026-09', 141003, 'C14-ABN-001')
    assert is_abnormal_view_all(
        '/rider-salary/order?attention=1&site_id=13&date_from=2026-09-01&date_to=2026-09-30',
        13,
        '2026-09',
    )
    assert not is_abnormal_view_all('/rider-salary/order?status=abnormal&site_id=13', 13, '2026-09')
    assert is_day_drawer_not_daily_payslip('公式金额 只含逐单。周期项不落日，对账看条')
    assert not is_day_drawer_not_daily_payslip('公式金额 120.00 净额 120.00')


def test_must1_due_stale_hooks_fail_closed() -> None:
    expected = _load('ops-due-stale-row-level-label')['expected']
    attention = _must_read(_ui('views', 'dashboard', 'components', 'AttentionList.vue'))
    missing = [name for name in MUST1_IDS if name not in attention]
    assert not missing, f'Must 1 倒计时/需重算钩子缺失即失败，不得 skip：{missing}'
    assert expected['site_level_copy'] in attention
    assert expected['testid_due_row'] in attention
    assert expected['testid_stale_row'] in attention
    assert expected['row_period_id_attr'] in attention


def test_must2_gap_hooks_fail_closed() -> None:
    expected = _load('ops-import-gap-wizard-that-day')['expected']
    attention = _must_read(_ui('views', 'dashboard', 'components', 'AttentionList.vue'))
    dashboard = _must_read(_ui('views', 'dashboard', 'index.vue'))
    wizard = _must_read(_ui('views', 'order', 'components', 'ImportWizard.vue'))
    blob = '\n'.join([attention, dashboard, wizard])
    missing = [name for name in MUST2_IDS if name not in blob]
    assert not missing, f'Must 2 缺口行→向导钩子缺失即失败，不得 skip：{missing}'
    assert expected['testid_row'] in attention
    assert 'ImportWizard' in dashboard or 'ImportWizard' in attention or 'import-wizard' in attention
    gap_handler = ''
    if "block.key === 'import_gaps'" in attention:
        gap_handler = attention.split("block.key === 'import_gaps'")[-1][:900]
    elif "case 'import_gaps'" in attention:
        gap_handler = attention.split("case 'import_gaps'")[-1][:900]
    if gap_handler and '/rider-salary/order' in gap_handler and 'import-wizard' not in gap_handler:
        raise AssertionError('缺口行只进 /order 订单列表不够。Must 2 必须打开向导，不得 skip')


def test_must3_abnormal_hooks_fail_closed() -> None:
    expected = _load('ops-abnormal-order-deeplink')['expected']
    attention = _must_read(_ui('views', 'dashboard', 'components', 'AttentionList.vue'))
    order_page = _must_read(_ui('views', 'order', 'index.vue'))
    blob = '\n'.join([attention, order_page])
    missing = [name for name in MUST3_IDS if name not in blob]
    assert not missing, f'Must 3 异常单钩子缺失即失败，不得 skip：{missing}'
    assert expected['testid_row'] in attention
    assert any(name in order_page for name in MUST3_LANDING_IDS), (
        f'订单页须消费 id/order_no 并打开该单（{" / ".join(MUST3_LANDING_IDS)}），不得 skip'
    )
    assert "query.id" in order_page or "query['id']" in order_page or 'query.order_no' in order_page
    assert 'attention' in blob


def test_must4_wizard_hooks_fail_closed() -> None:
    expected = _load('ops-import-skip-errors-not-all-success')['expected']
    wizard = _must_read(_ui('views', 'order', 'components', 'ImportWizard.vue'))
    missing = [name for name in MUST4_IDS if name not in wizard]
    assert not missing, f'Must 4 向导半成功钩子缺失即失败，不得 skip：{missing}'
    assert expected['all_success_copy_is_fail'] in wizard or '跳过错误行' in wizard
    assert expected['result_copy'] in wizard
    assert expected['testid_skip'] in wizard
    assert expected['testid_failed'] in wizard
    assert expected['testid_report'] in wizard
    assert '导入流程已完成' not in wizard or expected['testid_failed'] in wizard.split('导入流程已完成')[0][-200:] + wizard.split(
        '导入流程已完成'
    )[-1]
    csv = FIXTURES / 'ops-import-skip-errors-not-all-success' / 'skip-errors-half-success.csv'
    body = _must_read(csv)
    assert 'NO_SUCH_JOB_C14' in body
    assert 'D5A001' in body


def test_must5_day_drawer_hooks_fail_closed() -> None:
    expected = _load('cdp-admin-day-drawer-not-daily-payslip')['expected']
    drawer = _must_read(_ui('views', 'calendar', 'components', 'DayDrawer.vue'))
    missing = [name for name in MUST5_IDS if name not in drawer]
    assert not missing, f'Must 5 日抽屉钩子缺失即失败，不得 skip：{missing}'
    assert expected['formula_amount_label'] in drawer
    assert expected['net_label'] in drawer
    assert '周期项不落日' in drawer or '对账看条' in drawer
    assert expected['testid_note'] in drawer
    assert expected['assert_cycle13_chip_landing'] is False
    assert 'calendar-period-chip' not in drawer or '不验收' in drawer


def test_cycle14_does_not_touch_advance_quota_or_fba() -> None:
    for name in NAMED:
        blob = json.dumps(_load(name), ensure_ascii=False)
        assert 'advance_limit_count' not in blob
        assert '个税' not in blob
        assert 'PluginNotice' not in blob
        assert 'FIX_C18' not in blob
    lib = _must_read(CDP_LIB)
    assert '不改 FBA' in lib
    assert '8200' in lib
