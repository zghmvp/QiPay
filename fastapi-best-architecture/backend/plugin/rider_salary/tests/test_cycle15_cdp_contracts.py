"""Cycle 15 具名 CDP 夹具合同。钩子缺失即失败，不得 skip。

Must 2 必须走订单抽屉纠错或补录；API 绿替抽屉 = FAIL。
Must 3 必须走反冲确认框 + 成功后该期算薪页；只断言文案 = FAIL。
Must 4 必须走批量模态 + 半填行；写成整批 422 = FAIL。
Must 5 不验收 Cycle 13 芯片 / 查看周期；不验收 Cycle 14 已算日「周期项不落日 / 对账看条」。
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
PLUGIN = Path(__file__).resolve().parents[1]
CDP_SPECS = Path(__file__).resolve().parents[5] / 'scripts' / 'cdp' / 'specs'
CDP_LIB = Path(__file__).resolve().parents[5] / 'scripts' / 'cdp' / 'cycle15-lib.mjs'
CDP_HARNESS = Path(__file__).resolve().parents[5] / 'scripts' / 'cdp' / 'harness.mjs'

NAMED = (
    'ops-resigned-order-deeplink',
    'ops-order-fix-shows-stale',
    'ops-reverse-confirm-then-calc',
    'ops-adj-batch-skip-incomplete-not-all-success',
    'cdp-admin-day-uncalculated-not-zero',
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
    'ops-due-stale-row-level-label',
    'ops-import-gap-wizard-that-day',
    'ops-abnormal-order-deeplink',
    'ops-import-skip-errors-not-all-success',
    'cdp-admin-day-drawer-not-daily-payslip',
}

MUST1_IDS = (
    'ops-resigned-order-deeplink',
    'dashboard-resigned-row',
    'dashboard-resigned-view-all',
)
MUST1_LANDING_IDS = ('rider-profile-open', 'order-rider-month-scope', 'rider-row-active')
MUST2_IDS = (
    'ops-order-fix-shows-stale',
    'order-form-drawer',
    'order-fix-stale-copy',
    'order-fix-goto-calc',
)
MUST3_IDS = (
    'ops-reverse-confirm-then-calc',
    'period-reverse-confirm',
    'period-reverse-count',
    'period-reverse-rider-count',
)
MUST3_LANDING_IDS = ('period-calc-title',)
MUST4_IDS = (
    'ops-adj-batch-skip-incomplete-not-all-success',
    'adj-batch-modal',
    'adj-batch-incomplete-row',
    'adj-batch-created-count',
    'adj-batch-skipped-count',
)
MUST5_IDS = (
    'cdp-admin-day-uncalculated-not-zero',
    'day-drawer-formula-amount',
    'day-drawer-net',
    'day-drawer-uncalculated',
    'day-drawer-order-not-in-calc',
)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name / 'expected.json').read_text(encoding='utf-8'))


def _must_read(path: Path) -> str:
    assert path.is_file(), f'{path.name} 缺失即失败，不得 skip'
    return path.read_text(encoding='utf-8')


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


def is_resigned_row_landing(raw: str, rider_id: int | str, month: str | None = None) -> bool:
    path = _path(raw)
    query = _query(raw)
    profile = re.search(r'/rider-salary/rider/(\d+)(?:/|$)', path)
    if profile and profile.group(1) == str(rider_id):
        return True
    if '/rider-salary/order' in path and (query.get('rider_id') or [''])[0] == str(rider_id):
        if not month:
            return True
        from_ = (query.get('date_from') or query.get('month') or [''])[0]
        return from_.startswith(month) or (query.get('month') or [''])[0] == month
    return False


def is_resigned_list_without_this_rider(raw: str, rider_id: int | str) -> bool:
    path = _path(raw)
    query = _query(raw)
    if not path.rstrip('/').endswith('/rider-salary/rider'):
        return False
    if (query.get('status') or [''])[0] != 'resigned':
        return False
    opened = (query.get('rider_id') or query.get('id') or query.get('edit_id') or [''])[0]
    return opened != str(rider_id)


def is_resigned_view_all(raw: str, site_id: int | str | None, month: str) -> bool:
    path = _path(raw)
    query = _query(raw)
    if not path.rstrip('/').endswith('/rider-salary/rider'):
        return False
    if (query.get('status') or [''])[0] != 'resigned':
        return False
    if site_id is not None and (query.get('site_id') or [''])[0] != str(site_id):
        return False
    return (query.get('month') or [''])[0] == month


def is_covering_calc_landing(raw: str, period_id: int | str) -> bool:
    path = _path(raw)
    return landing_period_id(raw) == str(period_id) and bool(
        re.search(r'/rider-salary/period/\d+/calculate', path)
    )


def is_period_list_with_month(raw: str, site_id: int | str | None, month: str) -> bool:
    path = _path(raw)
    query = _query(raw)
    if not path.rstrip('/').endswith('/rider-salary/period'):
        return False
    if '/calculate' in path:
        return False
    if site_id is not None and (query.get('site_id') or [''])[0] != str(site_id):
        return False
    return (query.get('month') or [''])[0] == month


def is_stale_fix_copy(text: str) -> bool:
    return bool(re.search(r'需重算|未出账', text or ''))


def is_uncalculated_empty_amount(text: str) -> bool:
    blob = text or ''
    return bool(re.search(r'未算薪|尚未算薪|—|－', blob))


def test_cycle15_named_cdp_fixture_hooks() -> None:
    resigned = _load('ops-resigned-order-deeplink')['expected']
    assert resigned['skip_if_missing'] is False
    assert resigned['row_must_carry_rider_id'] is True
    assert resigned['resigned_list_without_this_rider_is_fail'] is True
    assert resigned['merge_attention_1_is_fail'] is True

    fix = _load('ops-order-fix-shows-stale')['expected']
    assert fix['must_drive_order_drawer'] is True
    assert fix['api_green_instead_of_drawer_is_fail'] is True
    assert fix['q15_1_toast_only_not_enough'] is True
    assert '需重算' in fix['stale_copy']

    reverse = _load('ops-reverse-confirm-then-calc')['expected']
    assert reverse['must_drive_reverse_confirm'] is True
    assert reverse['must_land_this_period_calc_after_confirm'] is True
    assert reverse['copy_only_without_landing_is_fail'] is True
    assert reverse['q14_2_copy_only_not_enough'] is True

    batch = _load('ops-adj-batch-skip-incomplete-not-all-success')['expected']
    assert batch['must_drive_batch_modal'] is True
    assert batch['must_drive_incomplete_row'] is True
    assert batch['all_success_copy_is_fail'] == '批量录入成功'
    assert batch['raise_whole_batch_422_is_fail'] is True

    drawer = _load('cdp-admin-day-uncalculated-not-zero')['expected']
    assert drawer['assert_cycle13_chip_landing'] is False
    assert drawer['assert_cycle14_calculated_day_copy'] is False
    assert '未算薪' in drawer['uncalculated_copy']
    assert drawer['do_not_assert_period_item_not_daily'] is True


def test_cycle15_fixture_json_round_trip() -> None:
    for name in NAMED:
        payload = _load(name)
        assert payload['feature'] == name
        assert payload['expected']['skip_if_missing'] is False
        assert json.loads(json.dumps(payload)) == payload


def test_cycle15_does_not_change_locked_gold() -> None:
    for name in NAMED:
        locked = _load(name)['expected']['locked_gold_unchanged']
        assert locked['C03_gross'] == '8200.00'
        assert locked['C04_gross'] == '7800.00'
        assert locked['C05A_gross'] == '3500.00'
        blob = json.dumps(_load(name), ensure_ascii=False)
        assert '4629.33' not in blob
        assert '预支 800' not in blob


def test_cycle15_does_not_change_trial_case_gold_product_sentences() -> None:
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


def test_cycle15_does_not_invent_old_must_names() -> None:
    for name in NAMED:
        assert name not in EXISTING_MUST_NAMES
        assert _load(name)['feature'] == name
    harness = _must_read(CDP_HARNESS)
    for name in NAMED:
        assert name in harness
    assert harness.count('export const name') == 0


def test_cycle15_named_specs_exist_and_fail_closed() -> None:
    for name in NAMED:
        path = _spec(name)
        text = _must_read(path)
        assert f"export const name = '{name}'" in text
        assert '不得 skip' in text
        assert 'requireHooks' in text or 'requireTestId' in text


def test_must1_spec_deeplinks_this_resigned_rider() -> None:
    text = _must_read(_spec('ops-resigned-order-deeplink'))
    assert '离职仍有本月订单' in text
    assert 'dashboard-resigned-row' in text
    assert 'data-rider-id' in text
    assert 'status=resigned' in text or 'status' in text
    assert 'rider-profile-open' in text
    assert 'requireHooks' in text
    lib = _must_read(CDP_LIB)
    assert 'isResignedRowLanding' in lib
    assert 'isResignedViewAll' in lib


def test_must2_spec_drives_order_drawer_not_api_green() -> None:
    text = _must_read(_spec('ops-order-fix-shows-stale'))
    assert 'order-form-drawer' in text
    assert '纠错' in text
    assert '需重算' in text
    assert 'order-fix-goto-calc' in text
    assert 'MUST2_DRAWER_HOOKS' in text or 'order-form-drawer' in text
    assert 'updateOrderApi(' not in text
    assert 'createOrderApi(' not in text
    assert 'importCsv(' not in text.replace('禁止走 importCsv', '').replace('禁止 API importCsv', '')
    assert '仍 422' in text
    assert '跳过错误行' in text
    assert '自动 calculate' in text or '不得自动 calculate' in text
    lib = _must_read(CDP_LIB)
    assert 'assertNoOrderApiGreen' in lib
    assert 'isCoveringCalcLanding' in lib
    assert 'assertFixShowsStale' in lib


def test_must3_spec_drives_reverse_confirm_then_calc() -> None:
    text = _must_read(_spec('ops-reverse-confirm-then-calc'))
    assert '反冲补发' in text
    assert 'period-reverse-confirm' in text
    assert 'period-reverse-count' in text
    assert 'period-reverse-rider-count' in text
    assert 'fetchReversePreflight' in text
    assert '/calculate' in text
    assert 'period-calc-title' in text
    assert '待补发' in text
    assert '只改确认文案' in text or '只断言文案' in text
    lib = _must_read(CDP_LIB)
    assert 'assertReverseConfirmThenCalc' in lib
    assert 'reverse_preflight' in lib or 'reverse-preflight' in lib


def test_must4_spec_drives_batch_modal_and_incomplete_row() -> None:
    text = _must_read(_spec('ops-adj-batch-skip-incomplete-not-all-success'))
    assert '批量录入奖惩' in text
    assert 'adj-batch-modal' in text
    assert 'adj-batch-incomplete-row' in text
    assert 'adj-batch-created-count' in text
    assert 'adj-batch-skipped-count' in text
    assert '批量录入成功' in text
    assert '整批 422' in text
    assert 'openBatchModal' in text or '批量录入' in text
    assert '半填' in text
    lib = _must_read(CDP_LIB)
    assert 'assertBatchSkipIncomplete' in lib
    assert 'BATCH_ALL_SUCCESS_COPY' in lib


def test_must5_spec_does_not_assert_cycle13_chips_or_cycle14_calculated_day() -> None:
    text = _must_read(_spec('cdp-admin-day-uncalculated-not-zero'))
    assert '未算薪' in text
    assert '公式金额' in text
    assert '净额' in text
    assert 'calendar-period-chip' not in text
    assert 'calendar-view-period' not in text
    assert 'day-drawer-period-not-daily' not in text
    assert 'assertDayDrawerNotPayslip' not in text
    assert '/payroll?rider_id=' not in text
    assert '芯片' in text and '不验收' in text
    assert '周期项不落日' in text and '不验收' in text
    expected = _load('cdp-admin-day-uncalculated-not-zero')['expected']
    assert expected['assert_cycle13_chip_landing'] is False
    assert expected['assert_cycle14_calculated_day_copy'] is False


def test_url_helper_contracts() -> None:
    assert is_resigned_row_landing('/rider-salary/rider/151001', 151001)
    assert is_resigned_row_landing(
        '/rider-salary/order?rider_id=151001&month=2026-09',
        151001,
        '2026-09',
    )
    assert not is_resigned_row_landing('/rider-salary/rider?status=resigned', 151001)
    assert is_resigned_list_without_this_rider('/rider-salary/rider?status=resigned', 151001)
    assert is_resigned_view_all(
        '/rider-salary/rider?status=resigned&site_id=13&month=2026-09',
        13,
        '2026-09',
    )
    assert not is_resigned_view_all('/rider-salary/rider?status=resigned', 13, '2026-09')
    assert is_covering_calc_landing('/rider-salary/period/151003/calculate', 151003)
    assert not is_covering_calc_landing('/rider-salary/period?id=151003', 151003)
    assert is_period_list_with_month('/rider-salary/period?site_id=13&month=2026-09', 13, '2026-09')
    assert not is_period_list_with_month('/rider-salary/period/151003/calculate', 13, '2026-09')
    assert is_stale_fix_copy('已纠错订单，需重算后才会出账')
    assert not is_stale_fix_copy('已纠错订单')
    assert is_uncalculated_empty_amount('公式金额 — 未算薪')
    assert not is_uncalculated_empty_amount('公式金额 0.00 净额 0.00')


def test_must1_resigned_hooks_fail_closed() -> None:
    expected = _load('ops-resigned-order-deeplink')['expected']
    attention = _must_read(_ui('views', 'dashboard', 'components', 'AttentionList.vue'))
    rider_page = _must_read(_ui('views', 'rider', 'index.vue'))
    rider_detail = _must_read(_ui('views', 'rider', 'detail.vue'))
    order_page = _must_read(_ui('views', 'order', 'index.vue'))
    blob = '\n'.join([attention, rider_page, rider_detail, order_page])
    missing = [name for name in MUST1_IDS if name not in blob]
    assert not missing, f'Must 1 离职行钩子缺失即失败，不得 skip：{missing}'
    assert expected['testid_row'] in attention
    assert expected['row_id_attr'] in attention
    assert any(name in blob for name in MUST1_LANDING_IDS), (
        f'落地须打开该骑手档案或该骑手本月订单（{" / ".join(MUST1_LANDING_IDS)}），不得 skip'
    )
    handler = ''
    if "case 'resigned_with_orders'" in attention:
        handler = attention.split("case 'resigned_with_orders'")[-1][:900]
    if handler and '/rider-salary/rider?status=resigned' in handler and 'rider_id' not in handler:
        raise AssertionError('离职行只进离职总名单不够。Must 1 必须落到该 rider_id，不得 skip')


def test_must2_order_drawer_hooks_fail_closed() -> None:
    expected = _load('ops-order-fix-shows-stale')['expected']
    form = _must_read(_ui('views', 'order', 'components', 'OrderForm.vue'))
    missing = [name for name in MUST2_IDS if name not in form]
    assert not missing, f'Must 2 订单抽屉钩子缺失即失败，不得 skip：{missing}'
    assert expected['testid_drawer'] in form
    assert expected['testid_stale'] in form
    assert expected['testid_goto'] in form
    assert '需重算' in form or '未出账' in form
    if "message.success('已纠错订单')" in form and '需重算' not in form:
        raise AssertionError('只 toast「已纠错订单」且无「需重算」= FAIL，不得 skip')


def test_must3_reverse_hooks_fail_closed() -> None:
    expected = _load('ops-reverse-confirm-then-calc')['expected']
    period_page = _must_read(_ui('views', 'period', 'index.vue'))
    period_api = _must_read(PLUGIN / 'api' / 'v1' / 'period.py')
    period_service = _must_read(PLUGIN / 'service' / 'period_service.py')
    blob = '\n'.join([period_page, period_api, period_service])
    missing = [name for name in MUST3_IDS if name not in period_page]
    assert not missing, f'Must 3 反冲确认钩子缺失即失败，不得 skip：{missing}'
    assert expected['be_preflight_helper'] in blob
    assert 'reverse-preflight' in period_api or 'reverse_preflight' in period_service
    assert expected['testid_count'] in period_page
    assert expected['testid_rider_count'] in period_page
    assert any(name in blob for name in MUST3_LANDING_IDS) or '/calculate' in period_page, (
        '确认后须进该期算薪页，不得 skip'
    )
    if '将为已定稿/已发薪的薪资单生成反冲单' in period_page and 'period-reverse-count' not in period_page:
        raise AssertionError('只有套话且无单数/人数 = FAIL，不得 skip')


def test_must4_batch_hooks_fail_closed() -> None:
    expected = _load('ops-adj-batch-skip-incomplete-not-all-success')['expected']
    modal = _must_read(_ui('views', 'adjustment', 'components', 'BatchModal.vue'))
    missing = [name for name in MUST4_IDS if name not in modal]
    assert not missing, f'Must 4 批量模态钩子缺失即失败，不得 skip：{missing}'
    assert expected['testid_modal'] in modal
    assert expected['testid_incomplete'] in modal
    assert expected['testid_skipped'] in modal
    if expected['all_success_copy_is_fail'] in modal and expected['testid_skipped'] not in modal:
        raise AssertionError('存在半填行仍只 toast「批量录入成功」= FAIL，不得 skip')


def test_must5_day_drawer_hooks_fail_closed() -> None:
    expected = _load('cdp-admin-day-uncalculated-not-zero')['expected']
    drawer = _must_read(_ui('views', 'calendar', 'components', 'DayDrawer.vue'))
    missing = [name for name in MUST5_IDS if name not in drawer]
    assert not missing, f'Must 5 未算薪日钩子缺失即失败，不得 skip：{missing}'
    assert expected['formula_amount_label'] in drawer
    assert expected['net_label'] in drawer
    assert '未算薪' in drawer or '尚未算薪' in drawer
    assert expected['testid_note'] in drawer
    assert expected['assert_cycle13_chip_landing'] is False
    assert expected['assert_cycle14_calculated_day_copy'] is False
    assert 'calendar-period-chip' not in expected['testid_block']


def test_cycle15_does_not_touch_advance_quota_or_fba() -> None:
    for name in NAMED:
        blob = json.dumps(_load(name), ensure_ascii=False)
        assert 'advance_limit_count' not in blob
        assert '个税' not in blob
        assert 'PluginNotice' not in blob
        assert 'FIX_C18' not in blob
    lib = _must_read(CDP_LIB)
    assert '不改 FBA' in lib
    assert '8200' in lib
    harness = _must_read(CDP_HARNESS)
    assert '不得扩第六句' in harness
