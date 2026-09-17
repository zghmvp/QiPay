"""对抗循环 Cycle 5 后端：周期公式不得再加本期手工奖/惩；手工 200 只入账一次。"""

from __future__ import annotations

import inspect

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.api.v1.rider import get_rider, get_riders_paginated
from backend.plugin.rider_salary.engine.fields import FIELD_MAP
from backend.plugin.rider_salary.enums import CalcStage, DetailSource, SubjectDirection
from backend.plugin.rider_salary.service.calc_service import CalcInput, run_calc_pipeline
from backend.plugin.rider_salary.service.plan_service import PlanService
from backend.plugin.rider_salary.tests.test_adversarial_cycle2_backend import (
    test_fix_c03_gross_8200,
    test_fix_c04_gross_7800,
    test_fix_c05a_gross_3500,
)
from backend.plugin.rider_salary.tests.test_calc_pipeline import Segment, _item, _order
from backend.plugin.rider_salary.utils.plan_manual import (
    MANUAL_ADDEND_MSG,
    assert_period_formula_not_manual_addend,
    formula_adds_manual_period_field,
    is_period_manual_addend_item,
)

D = Decimal
START = date(2026, 9, 1)
END = date(2026, 9, 30)
GUARANTEE_SUBTRACT = '最大值(0, 3500 − 本期已计金额 − 本期手工奖)'


def _input(*, orders: list, items: list, adjustments: list | None = None) -> CalcInput:
    return CalcInput(
        rider_id=1,
        site_id=1,
        period_start=START,
        period_end=END,
        hire_date=START,
        leave_date=None,
        employ_type='full_time',
        segments=[Segment(plan_version_id=1, start_date=START, end_date=END, items=items)],
        orders=orders,
        employ_history=[],
        adjustments=adjustments or [],
        advances=[],
        covered_dates={START, END},
        site_order_dates={START},
        persist_advance=False,
        period_id=1,
    )


def _period_item(formula: dict, *, condition: dict | None = None, name: str = '周期项') -> dict:
    return {
        'name': name,
        'stage': 'period',
        'sort_order': 90,
        'enabled': True,
        'condition_json': condition or {},
        'formula_json': formula,
    }


def _bonus_200() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        subject_id=94017,
        amount=D('200.00'),
        signed_amount=D('200.00'),
        include_in_gross=True,
        direction=SubjectDirection.bonus.value,
        biz_date=START,
        subject=SimpleNamespace(name='全勤奖', direction='bonus', include_in_gross=True),
    )


def _c05a_items(*, guarantee_expr: str = '最大值(0, 3500 - 本期已计金额)') -> list:
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
            formula={'类型': '表达式', '表达式': guarantee_expr},
        ),
    ]


def test_gold_8200_7800_3500_unchanged() -> None:
    test_fix_c03_gross_8200()
    test_fix_c04_gross_7800()
    test_fix_c05a_gross_3500()


def test_manual_expression_addend_hard_fail() -> None:
    items = [_period_item({'类型': '表达式', '表达式': '本期手工奖'})]
    with pytest.raises(errors.RequestError, match='手工明细已入账') as exc:
        assert_period_formula_not_manual_addend(items)
    assert '再加会双计' in exc.value.msg
    assert exc.value.msg == MANUAL_ADDEND_MSG


def test_manual_penalty_addend_hard_fail() -> None:
    items = [_period_item({'类型': '表达式', '表达式': '本期手工惩 + 本期已计金额'})]
    with pytest.raises(errors.RequestError, match='再加会双计'):
        assert_period_formula_not_manual_addend(items)


def test_manual_field_rate_addend_hard_fail() -> None:
    items = [_period_item({'类型': '字段乘单价', '字段': '本期手工奖', '单价': 1, '起算值': 0})]
    with pytest.raises(errors.RequestError, match='手工明细已入账'):
        assert_period_formula_not_manual_addend(items)


def test_manual_fixed_wrap_addend_hard_fail() -> None:
    items = [_period_item({'类型': '固定金额', '金额': '本期手工奖'})]
    with pytest.raises(errors.RequestError, match='双计'):
        assert_period_formula_not_manual_addend(items)


def test_manual_subtract_guarantee_is_legal() -> None:
    items = [_period_item({'类型': '表达式', '表达式': GUARANTEE_SUBTRACT}, name='保底补足')]
    assert_period_formula_not_manual_addend(items)
    ascii_subtract = '最大值(0, 3500 - 本期已计金额 - 本期手工奖)'
    assert formula_adds_manual_period_field({'类型': '表达式', '表达式': GUARANTEE_SUBTRACT}) is False
    assert formula_adds_manual_period_field({'类型': '表达式', '表达式': ascii_subtract}) is False


def test_manual_condition_reference_is_legal() -> None:
    items = [
        _period_item(
            {'类型': '固定金额', '金额': 100},
            condition={'字段': '本期手工奖', '运算符': '>', '值': 0},
            name='有奖再补',
        )
    ]
    assert_period_formula_not_manual_addend(items)
    assert is_period_manual_addend_item(items[0]) is False


def test_disabled_manual_addend_is_ignored() -> None:
    items = [_period_item({'类型': '表达式', '表达式': '本期手工奖'})]
    items[0]['enabled'] = False
    assert_period_formula_not_manual_addend(items)


def test_fix_c05a_subtract_manual_still_3500() -> None:
    orders = [_order(i, f'C05A-{i}', START) for i in range(800)]
    result = run_calc_pipeline(_input(orders=orders, items=_c05a_items(guarantee_expr=GUARANTEE_SUBTRACT)))
    guarantee = next(row for row in result.details if row.name == '保底补足')
    assert guarantee.amount == D('700.00')
    assert result.gross == D('3500.00')
    assert_period_formula_not_manual_addend([
        {
            'name': '提成',
            'stage': 'per_order',
            'enabled': True,
            'formula_json': {'类型': '固定金额', '金额': 3.5},
        },
        {
            'name': '保底补足',
            'stage': 'period',
            'enabled': True,
            'formula_json': {'类型': '表达式', '表达式': GUARANTEE_SUBTRACT},
        },
    ])


def test_manual_bonus_200_booked_once() -> None:
    items = [
        _item(
            pk=1,
            subject_id=1,
            name='基础单价',
            stage=CalcStage.per_order.value,
            sort_order=10,
            condition={},
            formula={'类型': '固定金额', '金额': 4},
        )
    ]
    result = run_calc_pipeline(_input(orders=[], items=items, adjustments=[_bonus_200()]))
    manuals = [row for row in result.details if row.source == DetailSource.manual.value]
    assert len(manuals) == 1
    assert manuals[0].amount == D('200.00')
    assert result.bonus_total == D('200.00')
    assert result.gross == D('200.00')
    assert result.gross != D('400.00')
    assert_period_formula_not_manual_addend([
        {
            'name': '基础单价',
            'stage': 'per_order',
            'enabled': True,
            'formula_json': {'类型': '固定金额', '金额': 4},
        }
    ])


def test_illegal_manual_addend_would_book_400_if_saved() -> None:
    """闸门存在的原因：公式加项 + 明细会把 200 写成 400。不得写出该版本。"""
    items = [
        _item(
            pk=1,
            subject_id=1,
            name='抄手工奖',
            stage=CalcStage.period.value,
            sort_order=10,
            condition={},
            formula={'类型': '表达式', '表达式': '本期手工奖'},
        )
    ]
    result = run_calc_pipeline(_input(orders=[], items=items, adjustments=[_bonus_200()]))
    manuals = [row for row in result.details if row.source == DetailSource.manual.value]
    formulas = [row for row in result.details if row.source == DetailSource.formula.value and row.name == '抄手工奖']
    assert len(manuals) == 1
    assert len(formulas) == 1
    assert manuals[0].amount + formulas[0].amount == D('400.00')
    assert result.gross == D('400.00')
    with pytest.raises(errors.RequestError, match='再加会双计'):
        assert_period_formula_not_manual_addend([
            {
                'name': '抄手工奖',
                'stage': 'period',
                'enabled': True,
                'formula_json': {'类型': '表达式', '表达式': '本期手工奖'},
            }
        ])


def test_replace_items_and_activate_call_manual_addend_gate() -> None:
    replace_src = inspect.getsource(PlanService.replace_items)
    activate_src = inspect.getsource(PlanService.activate)
    assert 'assert_period_formula_not_manual_addend' in replace_src
    assert 'assert_period_formula_not_manual_addend' in activate_src
    gate = 'assert_period_formula_not_manual_addend'
    assert replace_src.index(gate) < replace_src.index('logical_delete_by_version')
    assert activate_src.index(gate) < activate_src.index('PlanVersionStatus.active')


def test_engine_field_catalog_warns_double_count() -> None:
    bonus = FIELD_MAP['本期手工奖']
    penalty = FIELD_MAP['本期手工惩']
    assert '可作条件' in bonus.description
    assert '手工明细已入账' in bonus.description
    assert '双计' in bonus.description
    assert '可作条件' in penalty.description
    assert '双计' in penalty.description


def test_rider_list_detail_do_not_need_tab_query() -> None:
    """tab=binding 是档案路由 query，前端已消费；本切片不改 #9 live 谓词。"""
    assert 'tab' not in inspect.signature(get_riders_paginated).parameters
    assert 'tab' not in inspect.signature(get_rider).parameters
