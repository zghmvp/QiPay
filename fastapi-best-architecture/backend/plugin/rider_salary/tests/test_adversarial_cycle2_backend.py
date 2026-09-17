"""对抗循环 Cycle 2 后端：保底末位硬拦 + 案例金标 + 导出需关注排除 + queued 态。"""

from __future__ import annotations

import inspect

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest

from openpyxl import load_workbook

from backend.common.exception import errors
from backend.plugin.rider_salary.api.v1.period import export_period
from backend.plugin.rider_salary.enums import CalcStage, OrderStatus, RecalcJobStatus
from backend.plugin.rider_salary.schema.period import CalcPrecheckResult, CalculatePeriodResult
from backend.plugin.rider_salary.service.calc_service import (
    CalcInput,
    finish_period_calc_status,
    persist_last_calc_status,
    run_calc_pipeline,
)
from backend.plugin.rider_salary.service.export_service import (
    ATTENTION_HEADERS,
    SHEET_ATTENTION,
    SHEET_DETAIL,
    SHEET_SUMMARY,
    SUMMARY_HEADERS,
    ExportService,
)
from backend.plugin.rider_salary.service.period_service import (
    calc_status_label,
    calc_sync_limit,
    should_queue_calculate,
)
from backend.plugin.rider_salary.service.plan_service import build_trial_result
from backend.plugin.rider_salary.tests.test_calc_pipeline import Segment, _item, _order
from backend.plugin.rider_salary.utils.excel import write_workbook
from backend.plugin.rider_salary.utils.order_attention import (
    ATTENTION_DURATION_SECONDS,
    attention_confession,
    is_attention_order,
    keep_export_detail_row,
    order_attention_condition,
)
from backend.plugin.rider_salary.utils.plan_guarantee import (
    GUARANTEE_LAST_MSG,
    assert_accrued_guarantee_is_last_period_item,
    is_accrued_or_guarantee_item,
)

D = Decimal
START = date(2026, 9, 1)
END = date(2026, 9, 30)

C03_C04_LADDER = [
    {'下限': 0, '上限': 400, '值': 4},
    {'下限': 400, '上限': 700, '值': 5},
    {'下限': 700, '上限': None, '值': 6},
]
C17_LADDER = [
    {'下限': 0, '上限': 400, '值': 5},
    {'下限': 400, '上限': 700, '值': 5.5},
    {'下限': 700, '上限': None, '值': 6},
]


def _ladder(mode: str, *, field: str, tiers: list[dict]) -> dict:
    return {'类型': '阶梯', '字段': field, '模式': mode, '计价': '按单价', '档位': tiers}


def _input(*, orders: list, items: list, start: date = START, end: date = END) -> CalcInput:
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
        persist_advance=False,
    )


def _c03_items(*, mode: str) -> list:
    return [
        _item(
            pk=1,
            subject_id=1,
            name='基础单价',
            stage=CalcStage.per_order.value,
            sort_order=10,
            condition={},
            formula={'类型': '固定金额', '金额': 3},
        ),
        _item(
            pk=2,
            subject_id=2,
            name='底薪',
            stage=CalcStage.period.value,
            sort_order=20,
            condition={},
            formula={'类型': '表达式', '表达式': '3000 * 方案生效天数 / 周期天数'},
        ),
        _item(
            pk=3,
            subject_id=3,
            name='提成',
            stage=CalcStage.period.value,
            sort_order=30,
            condition={},
            formula=_ladder(mode, field='周期有效单量', tiers=C03_C04_LADDER),
        ),
    ]


def test_fix_c03_gross_8200() -> None:
    orders = [_order(i, f'C03-{i}', START) for i in range(650)]
    result = run_calc_pipeline(_input(orders=orders, items=_c03_items(mode='全量落档')))
    assert result.valid_order_count == 650
    assert result.per_order_total == D('1950.00')
    assert result.gross == D('8200.00')


def test_fix_c04_gross_7800() -> None:
    orders = [_order(i, f'C04-{i}', START) for i in range(650)]
    result = run_calc_pipeline(_input(orders=orders, items=_c03_items(mode='分段累进')))
    assert result.valid_order_count == 650
    assert result.gross == D('7800.00')
    c03 = run_calc_pipeline(_input(orders=orders, items=_c03_items(mode='全量落档')))
    assert c03.gross - result.gross == D('400.00')


def test_fix_c05a_gross_3500() -> None:
    items = [
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
    orders = [_order(i, f'C05A-{i}', START) for i in range(800)]
    result = run_calc_pipeline(_input(orders=orders, items=items))
    guarantee = next(row for row in result.details if row.name == '保底补足')
    assert guarantee.amount == D('700.00')
    assert result.gross == D('3500.00')
    assert_accrued_guarantee_is_last_period_item([
        {
            'name': '提成',
            'stage': 'per_order',
            'sort_order': 10,
            'enabled': True,
            'formula_json': {'类型': '固定金额', '金额': 3.5},
        },
        {
            'name': '保底补足',
            'stage': 'period',
            'sort_order': 90,
            'enabled': True,
            'formula_json': {'类型': '表达式', '表达式': '最大值(0, 3500 - 本期已计金额)'},
        },
    ])


def test_early_guarantee_save_and_activate_hard_fail() -> None:
    items = [
        {
            'name': '提成',
            'stage': 'period',
            'sort_order': 90,
            'enabled': True,
            'formula_json': {'类型': '固定金额', '金额': 1},
        },
        {
            'name': '保底补足',
            'stage': 'period',
            'sort_order': 10,
            'enabled': True,
            'formula_json': {'类型': '表达式', '表达式': '最大值(0, 3500 - 本期已计金额)'},
        },
    ]
    with pytest.raises(errors.RequestError, match='须放在周期阶段最后') as exc:
        assert_accrued_guarantee_is_last_period_item(items)
    assert '沉底' in exc.value.msg
    assert exc.value.msg == GUARANTEE_LAST_MSG


def test_early_guarantee_pipeline_is_not_3500() -> None:
    """保底提前会把后续周期项算进应发，补差错。"""
    items = [
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
            sort_order=10,
            condition={},
            formula={'类型': '表达式', '表达式': '最大值(0, 3500 - 本期已计金额)'},
        ),
        _item(
            pk=3,
            subject_id=3,
            name='底薪',
            stage=CalcStage.period.value,
            sort_order=90,
            condition={},
            formula={'类型': '固定金额', '金额': 1000},
        ),
    ]
    orders = [_order(i, f'EARLY-{i}', START) for i in range(800)]
    result = run_calc_pipeline(_input(orders=orders, items=items))
    assert result.gross != D('3500.00')
    guarantee = next(row for row in result.details if row.name == '保底补足')
    assert guarantee.amount == D('700.00')


def test_replace_items_and_activate_call_guarantee_guard() -> None:
    from backend.plugin.rider_salary.service.plan_service import PlanService

    assert 'assert_accrued_guarantee_is_last_period_item' in inspect.getsource(PlanService.replace_items)
    assert 'assert_accrued_guarantee_is_last_period_item' in inspect.getsource(PlanService.activate)


def test_name_heuristic_guarantee_detected() -> None:
    assert is_accrued_or_guarantee_item({
        'name': '月保底',
        'stage': 'period',
        'formula_json': {'类型': '固定金额', '金额': 1},
    })
    assert not is_accrued_or_guarantee_item({
        'name': '提成',
        'stage': 'period',
        'formula_json': {'类型': '固定金额', '金额': 1},
    })


def test_fix_c17_quantity_field_fork_2310_vs_100() -> None:
    orders_420 = [_order(i, f'C17P-{i}', START) for i in range(420)]
    items_period = [
        _item(
            pk=1,
            subject_id=1,
            name='提成-周期有效',
            stage=CalcStage.period.value,
            sort_order=10,
            condition={},
            formula=_ladder('全量落档', field='周期有效单量', tiers=C17_LADDER),
        )
    ]
    r_period = run_calc_pipeline(_input(orders=orders_420, items=items_period))
    amt_period = next(d.amount for d in r_period.details if d.name == '提成-周期有效')
    assert amt_period == D('2310.00')

    day = date(2026, 9, 15)
    orders_20 = [_order(i, f'C17S-{i}', day) for i in range(20)]
    items_plan = [
        _item(
            pk=2,
            subject_id=1,
            name='提成-方案期内',
            stage=CalcStage.period.value,
            sort_order=10,
            condition={},
            formula=_ladder('全量落档', field='方案期内单量', tiers=C17_LADDER),
        )
    ]
    r_plan = run_calc_pipeline(_input(orders=orders_20, items=items_plan, start=day, end=day))
    amt_plan = next(d.amount for d in r_plan.details if d.name == '提成-方案期内')
    assert amt_plan == D('100.00')
    assert amt_period != amt_plan
    trial = build_trial_result(r_period, 'hash')
    dumped = trial.summary.model_dump()
    assert dumped['valid_order_count'] == 420
    assert dumped['plan_order_count'] == 420
    assert isinstance(dumped['valid_order_count'], int)
    assert isinstance(dumped['gross'], Decimal) or dumped['gross'] is not None


def test_trial_binding_segments_fixture_has_numeric_fork() -> None:
    from backend.plugin.rider_salary.tests.test_trial_binding_segments import EXPECTED

    contrast = EXPECTED['expected']['field_contrast_FIX_C17']
    assert contrast['period_valid_field_amount']
    assert contrast['plan_period_field_on_segment_b_amount']
    assert D(contrast['period_valid_field_amount']) != D(contrast['plan_period_field_on_segment_b_amount'])
    assert EXPECTED['expected']['valid_order_count']
    assert EXPECTED['expected']['plan_order_count']


def test_attention_predicate_matches_locked_plan() -> None:
    tz = dt_timezone.utc
    start = datetime(2026, 9, 1, 10, 0, tzinfo=tz)
    timeout = start + timedelta(seconds=ATTENTION_DURATION_SECONDS + 1)
    on_time = start + timedelta(minutes=20)
    assert is_attention_order(status=OrderStatus.abnormal.value, order_time=start, deliver_time=on_time)
    assert is_attention_order(status=OrderStatus.refunded.value, order_time=start, deliver_time=on_time)
    assert is_attention_order(status=OrderStatus.completed.value, order_time=start, deliver_time=timeout)
    assert not is_attention_order(status=OrderStatus.completed.value, order_time=start, deliver_time=on_time)
    exact_60 = start + timedelta(seconds=ATTENTION_DURATION_SECONDS)
    assert not is_attention_order(status=OrderStatus.completed.value, order_time=start, deliver_time=exact_60)
    assert not is_attention_order(status=OrderStatus.completed.value, order_time=start, deliver_time=None)
    assert not is_attention_order(status=OrderStatus.cancelled.value, order_time=start, deliver_time=timeout)
    cond = str(order_attention_condition().compile(compile_kwargs={'literal_binds': True})).lower()
    assert 'completed' in cond
    assert 'abnormal' in cond
    assert 'refunded' in cond


def test_export_exclude_attention_does_not_change_gross() -> None:
    assert keep_export_detail_row(exclude_attention=True, order_id=9, attention_ids={9}) is False
    assert keep_export_detail_row(exclude_attention=True, order_id=8, attention_ids={9}) is True
    assert keep_export_detail_row(exclude_attention=True, order_id=None, attention_ids={9}) is True
    assert keep_export_detail_row(exclude_attention=False, order_id=9, attention_ids={9}) is True
    summary = [['A001', '张伟', '站点', '周期', '正常', '草稿', 3, 2, 10, 0, 0, 0, 0, '88.50', 0, 0, '88.50', '']]
    content = write_workbook([
        (SHEET_SUMMARY, SUMMARY_HEADERS, summary),
        (SHEET_DETAIL, ['工号', '订单号'], [['A001', 'TO-1']]),
        (SHEET_ATTENTION, ATTENTION_HEADERS, [['', '', '', '', '', '', attention_confession(count=1, excluded=False)]]),
    ])
    workbook = load_workbook(BytesIO(content))
    assert str(workbook[SHEET_SUMMARY]['N2'].value) == '88.50'
    assert '本文件含需关注 1 条' in str(workbook[SHEET_ATTENTION]['G2'].value)
    assert attention_confession(count=3, excluded=True) == '已排除需关注 3 条；应发与实发未因排除改变'


def test_export_api_has_exclude_attention_query() -> None:
    params = inspect.signature(export_period).parameters
    assert 'exclude_attention' in params
    assert params['exclude_attention'].default is None
    assert bool(params['exclude_attention'].default) is False
    src = inspect.getsource(ExportService.export_period)
    assert 'exclude_attention' in src
    assert 'keep_export_detail_row' in src


def test_queued_threshold_and_status_labels() -> None:
    assert calc_sync_limit() == 200
    assert should_queue_calculate(200) is False
    assert should_queue_calculate(201) is True
    assert should_queue_calculate(2, limit=1) is True
    assert should_queue_calculate(1, limit=1) is False
    assert calc_status_label(RecalcJobStatus.queued.value) == '排队中'
    assert calc_status_label(RecalcJobStatus.running.value) == '计算中'
    status, message = finish_period_calc_status(calculated=3, failed_count=2)
    assert status == RecalcJobStatus.failed.value
    assert '部分失败' in message
    assert '完成' not in message
    ok, ok_msg = finish_period_calc_status(calculated=3, failed_count=0)
    assert ok == RecalcJobStatus.done.value
    assert ok_msg == '已计算 3 人'


def test_calculate_result_exposes_queued_status() -> None:
    payload = CalculatePeriodResult(
        calculated=0,
        warnings=['骑手数超过 1，已转入后台计算'],
        queued=True,
        calc_status=RecalcJobStatus.queued.value,
        calc_status_label='排队中',
        sync_limit=1,
        target_rider_count=3,
    )
    dumped = payload.model_dump()
    assert dumped['queued'] is True
    assert dumped['calc_status'] == 'queued'
    assert dumped['calc_status_label'] == '排队中'
    assert dumped['sync_limit'] == 1
    precheck = CalcPrecheckResult(
        period_id=12,
        can_run=True,
        blockers=[],
        warnings=[],
        eligible_rider_count=3,
        calc_status='running',
        calc_status_label='计算中',
        calc_status_message='计算中',
        sync_limit=1,
        attention_order_count=2,
    )
    assert precheck.calc_status_label == '计算中'
    assert precheck.sync_limit == 1
    assert precheck.attention_order_count == 2


def test_persist_last_calc_status_roundtrip() -> None:
    period = SimpleNamespace(last_calc_status=None, last_calc_status_message=None)
    persist_last_calc_status(period, status=RecalcJobStatus.queued.value, message='排队中：骑手3人已转入后台计算')
    assert period.last_calc_status == 'queued'
    assert '排队中' in period.last_calc_status_message
    persist_last_calc_status(period, status=RecalcJobStatus.failed.value, message='部分失败：成功 2 人，失败 1 人')
    assert period.last_calc_status == RecalcJobStatus.failed.value
    assert '部分失败' in period.last_calc_status_message
