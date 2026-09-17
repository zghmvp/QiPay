"""对抗循环 Cycle 4 后端合同：跨段固定额、分摊回归、金标三数不改。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from backend.plugin.rider_salary.engine.segments import Segment
from backend.plugin.rider_salary.enums import CalcStage, TrialMode
from backend.plugin.rider_salary.service.calc_service import CalcInput, run_calc_pipeline
from backend.plugin.rider_salary.service.plan_service import build_trial_result
from backend.plugin.rider_salary.tests.test_adversarial_cycle2_backend import _c03_items, _input
from backend.plugin.rider_salary.tests.test_calc_pipeline import _item, _order, _segment_a
from backend.plugin.rider_salary.utils.money import q2

D = Decimal
START = date(2026, 9, 1)
MID = date(2026, 9, 14)
NEXT = date(2026, 9, 15)
END = date(2026, 9, 30)


def _fixed_base_items() -> list:
    return [
        _item(
            pk=1,
            subject_id=94031,
            name='底薪',
            stage=CalcStage.period.value,
            sort_order=10,
            condition={},
            formula={'类型': '固定金额', '金额': 2000},
        ),
    ]


def _two_segment_input(items: list) -> CalcInput:
    orders = [_order(1, 'C4-FIX-1', START), _order(2, 'C4-FIX-2', NEXT)]
    return CalcInput(
        rider_id=1,
        site_id=1,
        period_start=START,
        period_end=END,
        hire_date=START,
        leave_date=None,
        employ_type='full_time',
        segments=[
            Segment(plan_version_id=21, start_date=START, end_date=MID, items=items),
            Segment(plan_version_id=22, start_date=NEXT, end_date=END, items=items),
        ],
        orders=orders,
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates={START, NEXT},
        site_order_dates={START, NEXT},
        persist_advance=False,
    )


def test_two_segment_fixed_base_counts_4000() -> None:
    """绑定感知 / 正式 calculate：两段固定 2000 → 底薪合计 4000，不得用整版一次 2000 冒充。"""
    items = _fixed_base_items()
    two = run_calc_pipeline(_two_segment_input(items))
    salary = [row for row in two.details if row.name == '底薪']
    assert len(salary) == 2
    assert sum((row.amount for row in salary), D('0.00')) == D('4000.00')
    assert two.period_total == D('4000.00')
    full = run_calc_pipeline(_input(orders=[_order(1, 'C4-FULL', START)], items=items))
    full_salary = [row for row in full.details if row.name == '底薪']
    assert len(full_salary) == 1
    assert full_salary[0].amount == D('2000.00')
    assert full.period_total == D('2000.00')
    binding = build_trial_result(two, None, mode=TrialMode.binding_segments)
    whole = build_trial_result(full, 'hash', mode=TrialMode.full_version)
    assert binding.matches_official_calculate is True
    assert binding.summary.gross == two.gross == D('4000.00')
    assert whole.matches_official_calculate is False
    assert whole.summary.gross == D('2000.00')
    assert whole.summary.gross != binding.summary.gross


def test_allocation_segment1_base_933_33_still_green() -> None:
    """正确分摊回归继续绿；不把 4629.33 / 预支 800 拉进金标。"""
    seg = _segment_a()
    data = CalcInput(
        rider_id=1,
        site_id=1,
        period_start=START,
        period_end=END,
        hire_date=START,
        leave_date=None,
        employ_type='full_time',
        segments=[seg],
        orders=[_order(1, 'C4-ALLOC', START)],
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates={START},
        site_order_dates={START},
        persist_advance=False,
        period_id=1,
    )
    result = run_calc_pipeline(data)
    salary = next(row for row in result.details if row.name == '底薪')
    assert salary.amount == D('933.33')
    assert salary.calc_trace['变量']['方案生效天数'] == 14
    assert salary.calc_trace['变量']['周期天数'] == 30
    assert result.gross != D('4629.33')
    assert result.advance_deduction == q2(D('0.00'))


def test_cycle4_locked_gold_8200_7800_3500_unchanged() -> None:
    orders = [_order(i, f'C4-G-{i}', START) for i in range(650)]
    c03 = run_calc_pipeline(_input(orders=orders, items=_c03_items(mode='全量落档')))
    c04 = run_calc_pipeline(_input(orders=orders, items=_c03_items(mode='分段累进')))
    assert c03.gross == D('8200.00')
    assert c04.gross == D('7800.00')
    c05_items = [
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
    c05_orders = [_order(i, f'C4-C05-{i}', START) for i in range(800)]
    c05 = run_calc_pipeline(_input(orders=c05_orders, items=c05_items))
    assert c05.gross == D('3500.00')


def test_full_month_single_segment_fixed_still_allowed() -> None:
    """不在保存时禁掉整月单段固定底薪。"""
    items = _fixed_base_items()
    result = run_calc_pipeline(_input(orders=[_order(1, 'C4-ONE', START)], items=items))
    assert result.period_total == D('2000.00')
    _ = SimpleNamespace(ok=True)
