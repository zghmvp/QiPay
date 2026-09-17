"""Cycle 3 具名 CDP 夹具合同（DB-free）。#23 已落地：缺失即失败，禁止 skip。"""

from __future__ import annotations

import inspect
import json

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.api.v1.period import export_period, list_period_calc_riders
from backend.plugin.rider_salary.enums import TrialMode
from backend.plugin.rider_salary.schema.period import CalculatePeriodResult, GetPeriodWithPayrolls
from backend.plugin.rider_salary.schema.trial import TrialResult
from backend.plugin.rider_salary.service.calc_service import (
    persist_last_calc_success_ids,
    run_calc_pipeline,
    trial_rider_range,
)
from backend.plugin.rider_salary.service.export_service import ADJUSTMENT_HEADERS, SHEET_ADJUSTMENT, ExportService
from backend.plugin.rider_salary.service.period_service import calc_sync_limit, should_queue_calculate
from backend.plugin.rider_salary.service.plan_service import PlanService, build_trial_result
from backend.plugin.rider_salary.tests.test_adversarial_cycle2_backend import _c03_items, _input
from backend.plugin.rider_salary.tests.test_calc_pipeline import _order
from backend.plugin.rider_salary.utils.calc_riders import (
    TRUNCATED_HINT,
    UNSELECTED_MEANS_ALL,
    paginate_calc_riders,
)
from backend.plugin.rider_salary.utils.export_adjustment import (
    ATTENTION_ADJ_NOTE,
    classify_adjustments,
)
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.plan_threshold import (
    THRESHOLD_XOR_MSG,
    assert_threshold_price_period_items_xor,
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
UI_PERIOD = UI_PLUGIN / 'views' / 'period'
D = Decimal
START = date(2026, 9, 1)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name / 'expected.json').read_text(encoding='utf-8'))


def test_cycle3_named_cdp_fixture_hooks() -> None:
    split = _load('ops-calc-success-vs-existing')
    assert split['expected']['run_success_table_required'] is True
    assert split['expected']['cannot_replace_with_existing_tag'] is True
    assert split['expected']['failures_stay_in_section_2'] is True
    assert split['expected']['testid_run_success'] == 'period-calc-run-success'
    assert split['expected']['testid_existing'] == 'period-calc-payrolls'
    assert split['expected']['testid_this_run_tag'] == 'period-calc-payroll-this-run-tag'
    assert split['expected']['tag_alone_is_not_enough'] is True
    assert '代扣' in split['expected']['success_columns']
    assert '预支抵扣' in split['expected']['success_columns']
    assert split['expected']['skip_if_missing'] is False
    assert split['expected']['last_calc_success_ids_field'] == 'last_calc_success_ids'

    adj = _load('ops-export-adjustment-sheet')
    assert adj['sheet_name'] == SHEET_ADJUSTMENT == '奖惩记录'
    assert adj['expected']['default_exclude_adjustments'] is False
    assert adj['expected']['exclude_orders_still_exports_all_adjustments'] is True
    assert adj['expected']['does_not_change_gross_net'] is True
    assert adj['expected']['skip_if_missing'] is False
    assert adj['expected']['testid_adj_booked'] == 'period-export-adj-booked'
    assert adj['expected']['testid_adj_unbooked'] == 'period-export-adj-unbooked'
    assert adj['expected']['testid_adj_annotation'] == 'period-export-adj-annotation'
    assert adj['expected']['testid_adj_sync_toggle'] == 'period-export-adj-sync-toggle'
    assert adj['expected']['query_sync_exclude'] == 'exclude_attention_adjustments'
    assert adj['expected']['attention_same_rider_day_mark'] == ATTENTION_ADJ_NOTE

    trial = _load('trial-equals-calc')
    assert trial['expected']['binding_aware_trial_gross_equals_calculate_gross'] is True
    assert trial['expected']['no_numbers_is_fail'] is True
    assert trial['expected']['modal_must_not_submit'] is True
    assert trial['expected']['skip_if_missing'] is False
    assert TrialMode.binding_segments.value == trial['expected']['binding_mode']
    assert trial['expected']['matches_official_calculate'] is True
    assert trial['expected']['testid_matches_official'] == 'trial-matches-official-calculate'

    xor = _load('ops-plan-threshold-xor')
    assert xor['expected']['save_fails'] is True
    assert xor['expected']['activate_fails'] is True
    assert xor['expected']['cancel_must_not_save'] is True
    assert xor['expected']['C08_399_gross'] == '1995.00'
    assert xor['expected']['C08_400_gross'] == '2400.00'
    assert xor['expected']['C05B_1200_gross'] == '4200.00'
    assert xor['expected']['C11_gross'] == '4890.00'
    assert xor['expected']['skip_if_missing'] is False

    picker = _load('ops-calc-rider-picker-not-truncated')
    assert picker['expected']['unselected_means_all_copy'] == UNSELECTED_MEANS_ALL
    assert picker['expected']['unselected_posts_null'] is True
    assert picker['expected']['search_finds_rider_201'] is True
    assert picker['expected']['subset_posts_ids_not_null'] is True
    assert picker['expected']['skip_if_missing'] is False
    assert picker['expected']['testid_unselected_all'] == 'period-calc-riders-unselected-all'
    assert picker['expected']['testid_truncated'] == 'period-calc-riders-truncated'
    assert picker['expected']['calc_riders_path'] == '/api/v1/rider-salary/periods/{id}/calc-riders'
    assert calc_sync_limit() == 200
    assert should_queue_calculate(201) is True
    assert should_queue_calculate(200) is False


def test_trial_equals_calculate_gross_same_pipeline() -> None:
    orders = [_order(i, f'TE-{i}', date(2026, 9, 1)) for i in range(650)]
    items = _c03_items(mode='全量落档')
    calc = run_calc_pipeline(_input(orders=orders, items=items))
    trial = build_trial_result(calc, 'hash', mode=TrialMode.binding_segments)
    assert trial.summary.gross == calc.gross == D('8200.00')
    assert trial.summary.advance_deduction == q2(D('0.00'))
    assert trial.matches_official_calculate is True
    assert 'persist=False' in inspect.getsource(trial_rider_range)


def test_binding_segments_trial_matches_official_calculate_flag() -> None:
    """binding_segments 必须打标 matches_official_calculate；full_version 不得冒充。"""
    orders = [_order(i, f'EQ-{i}', START) for i in range(399)]
    items = _c03_items(mode='全量落档')
    calc = run_calc_pipeline(_input(orders=orders, items=items))
    binding = build_trial_result(calc, None, mode=TrialMode.binding_segments)
    full = build_trial_result(calc, 'hash', mode=TrialMode.full_version)
    assert binding.matches_official_calculate is True
    assert binding.summary.gross == calc.gross
    assert full.matches_official_calculate is False
    dumped = TrialResult.model_validate(binding.model_dump())
    assert dumped.matches_official_calculate is True
    assert 'matches_official_calculate' in TrialResult.model_fields


def test_list_calculate_is_not_submit_modal() -> None:
    index_vue = UI_PERIOD / 'index.vue'
    modal_vue = UI_PERIOD / 'components' / 'CalculateModal.vue'
    index_src = index_vue.read_text(encoding='utf-8')
    modal_src = modal_vue.read_text(encoding='utf-8')
    assert 'path: `/rider-salary/period/${row.id}/calculate`' in index_src
    assert 'calcApi.open' not in index_src
    assert 'CalculateModal' not in index_src
    assert 'showConfirmButton: false' in modal_src
    assert 'calculatePeriodApi' not in modal_src
    assert '已计算' not in modal_src
    assert 'period-calc-modal-retired' in modal_src
    assert '不能在此弹窗完成计算' in modal_src


def test_cycle3_frontend_hooks_from_pr24_must_not_skip() -> None:
    """#24 钩子写进 Vue；缺失即失败，禁止把 Tag 当成 ②。"""
    calc_src = (UI_PERIOD / 'calculate.vue').read_text(encoding='utf-8')
    export_src = (UI_PERIOD / 'components' / 'ExportConfirmModal.vue').read_text(encoding='utf-8')
    picker_src = (UI_PERIOD / 'components' / 'CalcRiderPicker.vue').read_text(encoding='utf-8')
    trial_src = (UI_PLUGIN / 'views' / 'plan' / 'components' / 'TrialPanel.vue').read_text(encoding='utf-8')
    api_src = (UI_PLUGIN / 'api' / 'period.ts').read_text(encoding='utf-8')
    calc_run_src = (UI_PERIOD / 'calc-run.ts').read_text(encoding='utf-8')
    assert 'data-testid="period-calc-run-success"' in calc_src
    assert 'data-testid="period-calc-payrolls"' in calc_src
    assert 'data-testid="period-calc-payroll-this-run-tag"' in calc_src
    assert calc_src.index('period-calc-run-success') < calc_src.index('period-calc-payrolls')
    assert '本次成功' in calc_src
    assert '周期内已有薪资' in calc_src
    assert '不是本轮刚算全员' in calc_src
    assert 'last_calc_success_ids' in calc_run_src
    assert 'calculated_rider_ids' in calc_run_src
    assert 'data-testid="period-export-adj-booked"' in export_src
    assert 'data-testid="period-export-adj-unbooked"' in export_src
    assert 'data-testid="period-export-adj-annotation"' in export_src
    assert '该骑手该日存在需关注订单' in export_src
    assert 'data-testid="period-export-adj-sync-toggle"' in export_src
    assert 'data-testid="period-export-adj-sync-drop-count"' in export_src
    assert 'data-testid="period-export-adj-admit"' in export_src
    assert 'excludeAttentionAdjustments = ref(false)' in export_src
    assert 'data-testid="period-calc-riders-unselected-all"' in picker_src
    assert '未选 = 计算本周期全部骑手' in picker_src
    assert 'data-testid="period-calc-riders-truncated"' in picker_src
    assert 'getPeriodCalcRidersApi' in picker_src
    assert '/calc-riders' in api_src
    assert 'exclude_attention_adjustments' in api_src
    assert 'data-testid="trial-matches-official-calculate"' in trial_src
    assert 'matches_official_calculate' in trial_src


def test_export_adjustment_sheet_contract() -> None:
    assert SHEET_ADJUSTMENT == '奖惩记录'
    assert '工号' in ADJUSTMENT_HEADERS
    assert '入账状态' in ADJUSTMENT_HEADERS
    assert '需关注同日同骑手' in ADJUSTMENT_HEADERS
    params = inspect.signature(export_period).parameters
    assert 'exclude_attention' in params
    query = _load('ops-export-adjustment-sheet')['expected']['query_sync_exclude']
    assert query == 'exclude_attention_adjustments'
    assert query in params, 'exclude_attention_adjustments 缺失即失败，不得 skip'
    assert bool(params[query].default) is False
    service_params = inspect.signature(ExportService.export_period).parameters
    assert service_params['exclude_attention_adjustments'].default is False
    classify_params = inspect.signature(classify_adjustments).parameters
    assert classify_params['exclude_attention_adjustments'].default is False
    dirty = SimpleNamespace(
        id=3,
        rider_id=1,
        biz_date=START,
        subject_id=10,
        amount=D('50.00'),
        signed_amount=D('-50.00'),
        remark='惩',
        is_locked=False,
        period_id=7,
    )
    default_rows = classify_adjustments(
        [dirty],
        period_id=7,
        manual_keys=set(),
        attention_keys={(1, START)},
    )
    assert default_rows[0].dropped is False
    assert default_rows[0].attention_note == ATTENTION_ADJ_NOTE
    export_src = inspect.getsource(ExportService.export_period)
    assert 'SHEET_ADJUSTMENT' in export_src
    assert 'exclude_attention_adjustments' in inspect.getsource(export_period)
    assert 'X-QiPay-Adjustment-Booked' in inspect.getsource(export_period)


def test_threshold_xor_guard_must_not_skip() -> None:
    """保存/启用硬拦：#23 已接线，ImportError / 保存成功 = FAIL。"""
    expected = _load('ops-plan-threshold-xor')
    assert expected['expected']['skip_if_missing'] is False
    src = inspect.getsource(PlanService.replace_items) + inspect.getsource(PlanService.activate)
    assert 'assert_threshold_price_period_items_xor' in src
    overlap = [
        {
            'name': '门槛低于400',
            'stage': 'period',
            'sort_order': 10,
            'enabled': True,
            'condition_json': {'逻辑': '且', '条件': [{'字段': '周期有效单量', '运算符': '≤', '值': 400}]},
            'formula_json': {'类型': '字段乘单价', '字段': '周期有效单量', '单价': 5},
        },
        {
            'name': '门槛满400',
            'stage': 'period',
            'sort_order': 20,
            'enabled': True,
            'condition_json': {'逻辑': '且', '条件': [{'字段': '周期有效单量', '运算符': '≥', '值': 400}]},
            'formula_json': {'类型': '字段乘单价', '字段': '周期有效单量', '单价': 6},
        },
    ]
    with pytest.raises(errors.RequestError, match='须互斥') as exc:
        assert_threshold_price_period_items_xor(overlap)
    assert '双计' in exc.value.msg
    assert exc.value.msg == THRESHOLD_XOR_MSG
    exclusive = [
        {
            'name': '门槛低于400',
            'stage': 'period',
            'enabled': True,
            'condition_json': {'字段': '周期有效单量', '运算符': '<', '值': 400},
            'formula_json': {'类型': '字段乘单价', '字段': '周期有效单量', '单价': 5},
        },
        {
            'name': '门槛满400',
            'stage': 'period',
            'enabled': True,
            'condition_json': {'字段': '周期有效单量', '运算符': '≥', '值': 400},
            'formula_json': {'类型': '字段乘单价', '字段': '周期有效单量', '单价': 6},
        },
    ]
    assert_threshold_price_period_items_xor(exclusive)
    assert expected['expected']['save_fails'] is True
    assert expected['expected']['C08_399_gross'] == '1995.00'


def test_calc_riders_search_past_200() -> None:
    """GET /periods/{id}/calc-riders 必须存在；keyword 能搜到第 201 人。"""
    route_src = inspect.getsource(list_period_calc_riders)
    assert '/{pk}/calc-riders' in route_src
    params = inspect.signature(list_period_calc_riders).parameters
    assert 'keyword' in params
    assert 'page' in params
    assert 'size' in params
    riders = [SimpleNamespace(id=i, job_no=f'D{i:04d}', name=f'骑手{i}') for i in range(1, 202)]
    page = paginate_calc_riders(riders, page=1, size=200)
    assert page.total == 201
    assert page.listed_count == 200
    assert page.truncated is True
    assert page.truncated_hint == TRUNCATED_HINT.format(n=200)
    assert page.unselected_means_all == UNSELECTED_MEANS_ALL
    found = paginate_calc_riders(riders, keyword='D0201', page=1, size=200)
    assert found.total == 1
    assert found.items[0].id == 201
    assert found.truncated is False
    named = paginate_calc_riders(riders, keyword='FIX_C3_R201', page=1, size=200)
    assert named.total == 0
    job_hit = paginate_calc_riders(
        [SimpleNamespace(id=9201, job_no='FIX_C3_R201', name='选人夹具201'), *riders],
        keyword='FIX_C3_R201',
        page=1,
        size=200,
    )
    assert job_hit.total == 1
    assert job_hit.items[0].id == 9201
    page2 = paginate_calc_riders(riders, page=2, size=200)
    assert [row.id for row in page2.items] == [201]


def test_last_calc_success_ids_schema_and_persist() -> None:
    """GET 周期必须带 last_calc_success_ids；算薪成功 ID 落库，禁止只靠 toast。"""
    assert 'last_calc_success_ids' in GetPeriodWithPayrolls.model_fields
    assert 'calculated_rider_ids' in CalculatePeriodResult.model_fields
    payload = GetPeriodWithPayrolls.model_validate({
        'id': 1,
        'site_id': 1,
        'rider_id': 0,
        'cycle_type': 'month',
        'start_date': START,
        'end_date': date(2026, 9, 30),
        'status': 'open',
        'created_time': '2026-09-01T00:00:00+08:00',
        'last_calc_success_ids': [41, 8],
    })
    assert payload.last_calc_success_ids == [41, 8]
    period = SimpleNamespace(last_calc_success_ids=None)
    persist_last_calc_success_ids(period, [3, 5])  # type: ignore[arg-type]
    assert period.last_calc_success_ids == [3, 5]
    persist_last_calc_success_ids(period, [])  # type: ignore[arg-type]
    assert period.last_calc_success_ids == []
    calc = CalculatePeriodResult(calculated=2, failed=[], calculated_rider_ids=[3, 5], target_rider_count=2)
    assert calc.calculated_rider_ids == [3, 5]
    assert calc.failed_count == 0
    src = inspect.getsource(persist_last_calc_success_ids)
    assert 'last_calc_success_ids' in src


def test_cycle3_fixture_json_is_valid_ast_safe() -> None:
    for name in (
        'ops-calc-success-vs-existing',
        'ops-export-adjustment-sheet',
        'trial-equals-calc',
        'ops-plan-threshold-xor',
        'ops-calc-rider-picker-not-truncated',
    ):
        payload = _load(name)
        assert payload['expected']['skip_if_missing'] is False
        assert json.loads(json.dumps(payload)) == payload
