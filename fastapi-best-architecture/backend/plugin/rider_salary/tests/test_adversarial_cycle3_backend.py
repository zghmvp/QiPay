"""对抗循环 Cycle 3 后端：奖惩 sheet、试算=正式、门槛互斥金标、骑手搜索分页。"""

from __future__ import annotations

import inspect

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest

from openpyxl import load_workbook

from backend.common.exception import errors
from backend.plugin.rider_salary.api.v1.period import export_period, list_period_calc_riders
from backend.plugin.rider_salary.enums import CalcStage, TrialMode
from backend.plugin.rider_salary.schema.period import CalcPrecheckResult, CalculatePeriodResult, GetPeriodWithPayrolls
from backend.plugin.rider_salary.schema.trial import TrialResult
from backend.plugin.rider_salary.service.calc_service import (
    CalcInput,
    persist_last_calc_success_ids,
    run_calc_pipeline,
)
from backend.plugin.rider_salary.service.export_service import ADJUSTMENT_HEADERS, SHEET_ADJUSTMENT, SHEET_SUMMARY
from backend.plugin.rider_salary.service.plan_service import PlanService, build_trial_result
from backend.plugin.rider_salary.tests.test_calc_pipeline import Segment, _item, _order
from backend.plugin.rider_salary.utils.calc_riders import (
    TRUNCATED_HINT,
    UNSELECTED_MEANS_ALL,
    normalize_calc_rider_ids,
    paginate_calc_riders,
)
from backend.plugin.rider_salary.utils.excel import write_workbook
from backend.plugin.rider_salary.utils.export_adjustment import (
    ATTENTION_ADJ_NOTE,
    BOOKED_LABEL,
    UNBOOKED_LABEL,
    classify_adjustments,
    sheet_stats,
)
from backend.plugin.rider_salary.utils.plan_threshold import (
    THRESHOLD_XOR_MSG,
    assert_threshold_price_period_items_xor,
    conditions_can_both_be_true,
    is_threshold_price_item,
)

D = Decimal
START = date(2026, 9, 1)
END = date(2026, 9, 30)


def _input(
    *, orders: list, items: list, start: date = START, end: date = END, persist_advance: bool = False
) -> CalcInput:
    return CalcInput(
        rider_id=1,
        site_id=1,
        period_start=start,
        period_end=end,
        hire_date=start,
        leave_date=None,
        employ_type='full_time',
        segments=[Segment(plan_version_id=1, start_date=start, end_date=end, items=items)],
        orders=orders,
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates={start, end},
        site_order_dates={start},
        persist_advance=persist_advance,
        period_id=1,
    )


def _c08_items(*, low_op: str = '<', high_op: str = '≥') -> list:
    return [
        _item(
            pk=1,
            subject_id=1,
            name='提成-未满门槛',
            stage=CalcStage.period.value,
            sort_order=10,
            condition={'字段': '周期有效单量', '运算符': low_op, '值': 400},
            formula={'类型': '字段乘单价', '字段': '周期有效单量', '单价': 5, '起算值': 0},
        ),
        _item(
            pk=2,
            subject_id=1,
            name='提成-满门槛',
            stage=CalcStage.period.value,
            sort_order=20,
            condition={'字段': '周期有效单量', '运算符': high_op, '值': 400},
            formula={'类型': '字段乘单价', '字段': '周期有效单量', '单价': 6, '起算值': 0},
        ),
    ]


def _c05_items() -> list:
    return [
        _item(
            pk=1,
            subject_id=1,
            name='提成',
            stage=CalcStage.per_order.value,
            sort_order=10,
            condition={},
            formula={'类型': '固定金额', '金额': 3.5},
        ),
        _item(
            pk=2,
            subject_id=2,
            name='保底补足',
            stage=CalcStage.period.value,
            sort_order=90,
            condition={},
            formula={'类型': '表达式', '表达式': '最大值(0, 3500 - 本期已计金额)'},
        ),
    ]


def _c11_items() -> list:
    return [
        _item(
            pk=1,
            subject_id=1,
            name='基础单价',
            stage=CalcStage.per_order.value,
            sort_order=10,
            condition={},
            formula={'类型': '固定金额', '金额': 4},
        ),
        _item(
            pk=2,
            subject_id=2,
            name='冲单奖',
            stage=CalcStage.daily.value,
            sort_order=20,
            condition={'字段': '日有效单量', '运算符': '≥', '值': 30},
            formula={'类型': '固定金额', '金额': 50},
        ),
        _item(
            pk=3,
            subject_id=3,
            name='底薪',
            stage=CalcStage.period.value,
            sort_order=30,
            condition={},
            formula={'类型': '表达式', '表达式': '2000 * 方案生效天数 / 周期天数'},
        ),
    ]


def _c11_orders() -> list:
    orders = []
    oid = 0
    day = START
    while day <= END:
        per_day = 32 if (day - START).days < 5 else 20
        for _i in range(per_day):
            oid += 1
            orders.append(_order(oid, f'C11-{oid}', day))
        day += timedelta(days=1)
    return orders


def test_fix_c08_399_1995_and_400_2400() -> None:
    items = _c08_items()
    r399 = run_calc_pipeline(_input(orders=[_order(i, f'C08A-{i}', START) for i in range(399)], items=items))
    r400 = run_calc_pipeline(_input(orders=[_order(i, f'C08B-{i}', START) for i in range(400)], items=items))
    assert r399.valid_order_count == 399
    assert r399.gross == D('1995.00')
    assert r400.valid_order_count == 400
    assert r400.gross == D('2400.00')


def test_fix_c05b_1200_gross_4200_guarantee_zero() -> None:
    orders = [_order(i, f'C05B-{i}', START) for i in range(1200)]
    result = run_calc_pipeline(_input(orders=orders, items=_c05_items()))
    guarantee = next(row for row in result.details if row.name == '保底补足')
    assert guarantee.amount == D('0.00')
    assert result.gross == D('4200.00')
    assert result.gross != D('3500.00')


def test_fix_c11_gross_4890_daily_250() -> None:
    orders = _c11_orders()
    assert len(orders) == 5 * 32 + 25 * 20
    result = run_calc_pipeline(_input(orders=orders, items=_c11_items()))
    assert result.valid_order_count == 660
    assert result.per_order_total == D('2640.00')
    assert result.daily_total == D('250.00')
    assert result.period_total == D('2000.00')
    assert result.gross == D('4890.00')


def test_threshold_xor_overlap_hard_fail() -> None:
    overlap = [
        {
            'name': '提成-未满',
            'stage': 'period',
            'sort_order': 10,
            'enabled': True,
            'condition_json': {'字段': '周期有效单量', '运算符': '≤', '值': 400},
            'formula_json': {'类型': '字段乘单价', '字段': '周期有效单量', '单价': 5},
        },
        {
            'name': '提成-满',
            'stage': 'period',
            'sort_order': 20,
            'enabled': True,
            'condition_json': {'字段': '周期有效单量', '运算符': '≥', '值': 400},
            'formula_json': {'类型': '字段乘单价', '字段': '周期有效单量', '单价': 6},
        },
    ]
    with pytest.raises(errors.RequestError, match='须互斥') as exc:
        assert_threshold_price_period_items_xor(overlap)
    assert '双计' in exc.value.msg
    assert exc.value.msg == THRESHOLD_XOR_MSG


def test_threshold_xor_c08_exclusive_ok() -> None:
    items = [
        {
            'name': '提成-未满门槛',
            'stage': 'period',
            'sort_order': 10,
            'enabled': True,
            'condition_json': {'字段': '周期有效单量', '运算符': '<', '值': 400},
            'formula_json': {'类型': '字段乘单价', '字段': '周期有效单量', '单价': 5},
        },
        {
            'name': '提成-满门槛',
            'stage': 'period',
            'sort_order': 20,
            'enabled': True,
            'condition_json': {'字段': '周期有效单量', '运算符': '≥', '值': 400},
            'formula_json': {'类型': '字段乘单价', '字段': '周期有效单量', '单价': 6},
        },
    ]
    assert_threshold_price_period_items_xor(items)
    assert conditions_can_both_be_true(
        {'字段': '周期有效单量', '运算符': '≤', '值': 400},
        {'字段': '周期有效单量', '运算符': '≥', '值': 400},
        field='周期有效单量',
    )
    assert not conditions_can_both_be_true(
        {'字段': '周期有效单量', '运算符': '<', '值': 400},
        {'字段': '周期有效单量', '运算符': '≥', '值': 400},
        field='周期有效单量',
    )


def test_threshold_empty_conditions_overlap() -> None:
    items = [
        {
            'name': '门槛低',
            'stage': 'period',
            'enabled': True,
            'condition_json': {},
            'formula_json': {'类型': '字段乘单价', '字段': '周期有效单量', '单价': 5},
        },
        {
            'name': '门槛高',
            'stage': 'period',
            'enabled': True,
            'condition_json': {},
            'formula_json': {'类型': '字段乘单价', '字段': '周期有效单量', '单价': 6},
        },
    ]
    with pytest.raises(errors.RequestError, match='双计'):
        assert_threshold_price_period_items_xor(items)


def test_replace_items_and_activate_call_threshold_xor() -> None:
    assert 'assert_threshold_price_period_items_xor' in inspect.getsource(PlanService.replace_items)
    assert 'assert_threshold_price_period_items_xor' in inspect.getsource(PlanService.activate)


def test_threshold_item_heuristic() -> None:
    assert is_threshold_price_item({
        'name': '提成',
        'stage': 'period',
        'enabled': True,
        'formula_json': {'类型': '字段乘单价', '字段': '周期有效单量', '单价': 5},
    })
    assert not is_threshold_price_item({
        'name': '提成',
        'stage': 'per_order',
        'enabled': True,
        'formula_json': {'类型': '字段乘单价', '字段': '配送距离', '单价': 0.8},
    })


def test_trial_gross_equals_official_calculate() -> None:
    items = _c08_items()
    orders = [_order(i, f'EQ-{i}', START) for i in range(399)]
    trial = run_calc_pipeline(_input(orders=orders, items=items, persist_advance=False))
    official = run_calc_pipeline(_input(orders=orders, items=items, persist_advance=True))
    assert trial.gross == official.gross == D('1995.00')
    assert trial.advance_deduction == D('0.00')
    built = build_trial_result(trial, None, mode=TrialMode.binding_segments)
    assert built.matches_official_calculate is True
    assert built.summary.gross == official.gross
    full = build_trial_result(trial, 'hash', mode=TrialMode.full_version)
    assert full.matches_official_calculate is False


def test_c17_binding_trial_equals_calculate_gross() -> None:
    from backend.plugin.rider_salary.tests.test_trial_binding_segments import _build_rebind_input

    data = _build_rebind_input()
    trial = run_calc_pipeline(CalcInput(**{**data.__dict__, 'persist_advance': False}))
    official = run_calc_pipeline(CalcInput(**{**data.__dict__, 'persist_advance': True}))
    assert trial.gross == official.gross
    built = build_trial_result(trial, None, mode=TrialMode.binding_segments)
    assert built.summary.gross == official.gross
    assert built.matches_official_calculate is True


def test_calculate_result_always_keeps_failed() -> None:
    payload = CalculatePeriodResult(calculated=3, failed=[], target_rider_count=3)
    dumped = payload.model_dump()
    assert 'failed' in dumped
    assert dumped['failed'] == []
    assert dumped['failed_count'] == 0
    assert dumped['unselected_means_all'] == UNSELECTED_MEANS_ALL
    failed = CalculatePeriodResult(
        calculated=2,
        failed=[{'rider_id': 9, 'job_no': 'D201', 'errors': ['缺送达']}],
        calculated_rider_ids=[1, 2],
        target_rider_count=3,
    )
    assert failed.failed_count == 1
    assert failed.model_dump()['failed'][0]['job_no'] == 'D201'


def test_persist_last_calc_success_ids() -> None:
    period = SimpleNamespace(last_calc_success_ids=None)
    persist_last_calc_success_ids(period, [3, 5])  # type: ignore[arg-type]
    assert period.last_calc_success_ids == [3, 5]
    persist_last_calc_success_ids(period, [])  # type: ignore[arg-type]
    assert period.last_calc_success_ids == []


def test_period_detail_exposes_adjustment_counts_and_success_ids() -> None:
    payload = GetPeriodWithPayrolls.model_validate({
        'id': 1,
        'site_id': 1,
        'rider_id': 0,
        'cycle_type': 'month',
        'start_date': START,
        'end_date': END,
        'status': 'open',
        'created_time': '2026-09-01T00:00:00+08:00',
        'booked_adjustment_count': 1,
        'unbooked_adjustment_count': 1,
        'attention_adjustment_count': 1,
        'last_calc_success_ids': [8, 9],
    })
    assert payload.booked_adjustment_count == 1
    assert payload.unbooked_adjustment_count == 1
    assert payload.attention_adjustment_count == 1
    assert payload.last_calc_success_ids == [8, 9]


def test_calc_precheck_unselected_means_all() -> None:
    precheck = CalcPrecheckResult(
        period_id=1,
        can_run=True,
        blockers=[],
        warnings=[],
        eligible_rider_count=201,
    )
    assert precheck.unselected_means_all == UNSELECTED_MEANS_ALL
    assert precheck.eligible_rider_count == 201


def _adj(**kwargs: object) -> SimpleNamespace:
    defaults = {
        'id': 1,
        'rider_id': 1,
        'biz_date': START,
        'subject_id': 10,
        'amount': D('50.00'),
        'signed_amount': D('-50.00'),
        'remark': '惩',
        'is_locked': False,
        'period_id': None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_adjustment_sheet_booked_unbooked_and_attention_annotation() -> None:
    booked = _adj(id=1, period_id=7, rider_id=1, biz_date=START)
    unbooked = _adj(id=2, period_id=None, rider_id=2, biz_date=START + timedelta(days=1))
    dirty = _adj(id=3, period_id=7, rider_id=1, biz_date=START)
    attention_keys = {(1, START)}
    rows = classify_adjustments(
        [booked, unbooked, dirty],
        period_id=7,
        manual_keys=set(),
        attention_keys=attention_keys,
        exclude_attention_adjustments=False,
    )
    stats = sheet_stats(rows)
    assert stats.booked_count == 2
    assert stats.unbooked_count == 1
    assert stats.attention_count == 2
    assert stats.excluded_count == 0
    labels = {row.adjustment.id: row.booked_label for row in rows}
    assert labels[1] == BOOKED_LABEL
    assert labels[2] == UNBOOKED_LABEL
    dirty_row = next(row for row in rows if row.adjustment.id == 3)
    assert dirty_row.attention_note == ATTENTION_ADJ_NOTE
    kept = [row for row in rows if not row.dropped]
    assert len(kept) == 3


def test_adjustment_sync_drop_default_off() -> None:
    dirty = _adj(id=3, period_id=7, rider_id=1, biz_date=START)
    kept = classify_adjustments(
        [dirty],
        period_id=7,
        manual_keys=set(),
        attention_keys={(1, START)},
        exclude_attention_adjustments=False,
    )
    dropped = classify_adjustments(
        [dirty],
        period_id=7,
        manual_keys=set(),
        attention_keys={(1, START)},
        exclude_attention_adjustments=True,
    )
    assert kept[0].dropped is False
    assert dropped[0].dropped is True
    assert sheet_stats(dropped).excluded_count == 1
    assert sheet_stats(dropped).attention_count == 0


def test_adjustment_sheet_headers_and_annotation_export() -> None:
    assert '入账状态' in ADJUSTMENT_HEADERS
    assert '需关注同日同骑手' in ADJUSTMENT_HEADERS
    content = write_workbook([
        (SHEET_SUMMARY, ['工号', '应发'], [['A001', '100']]),
        (
            SHEET_ADJUSTMENT,
            ADJUSTMENT_HEADERS,
            [['A001', '张', START.isoformat(), '惩', -50, -50, '', '否', BOOKED_LABEL, '是', ATTENTION_ADJ_NOTE]],
        ),
    ])
    workbook = load_workbook(BytesIO(content))
    sheet = workbook[SHEET_ADJUSTMENT]
    assert sheet['I1'].value == '入账状态'
    assert sheet['I2'].value == BOOKED_LABEL
    assert ATTENTION_ADJ_NOTE in str(sheet['K2'].value)


def test_export_api_adjustment_query_default_off() -> None:
    params = inspect.signature(export_period).parameters
    assert params['exclude_attention_adjustments'].default is None
    assert bool(params['exclude_attention_adjustments'].default) is False
    src = inspect.getsource(export_period)
    assert 'exclude_attention_adjustments' in src
    assert 'X-QiPay-Adjustment-Booked' in src


def test_normalize_unselected_means_all() -> None:
    assert normalize_calc_rider_ids(None) is None
    assert normalize_calc_rider_ids([]) is None
    assert normalize_calc_rider_ids([201]) == [201]
    assert normalize_calc_rider_ids([1, 1, 2]) == [1, 2]


def test_rider_picker_search_page_201() -> None:
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
    page2 = paginate_calc_riders(riders, page=2, size=200)
    assert [row.id for row in page2.items] == [201]


def test_calc_riders_api_exists() -> None:
    params = inspect.signature(list_period_calc_riders).parameters
    assert 'keyword' in params
    assert 'page' in params
    assert 'size' in params


def test_trial_result_schema_binding_flag() -> None:
    result = TrialResult.model_validate({
        'passed': True,
        'mode': 'binding_segments',
        'mode_label': '按绑定分段试算',
        'matches_official_calculate': True,
        'summary': {
            'order_count': 1,
            'gross': '10.00',
            'deduction_total': '0.00',
            'net': '10.00',
            'per_order_total': '10.00',
            'daily_total': '0.00',
            'period_total': '0.00',
            'manual_bonus': '0.00',
            'manual_penalty': '0.00',
        },
    })
    assert result.matches_official_calculate is True
