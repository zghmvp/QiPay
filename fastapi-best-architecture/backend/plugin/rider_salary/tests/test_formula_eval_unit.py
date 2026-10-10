"""公式求值失败要抛出并留下告警，空公式在编译期拒绝。"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.plugin.rider_salary.engine.compiler import CompileError, compile_formula, validate_item
from backend.plugin.rider_salary.engine.evaluator import EvalError, evaluate_amount, evaluate_condition
from backend.plugin.rider_salary.engine.segments import PlanItemView, Segment
from backend.plugin.rider_salary.enums import CalcStage, OrderStatus, SubjectDirection
from backend.plugin.rider_salary.service.calc_service import CalcInput, CalcResult, run_calc_pipeline
from backend.utils.timezone import timezone

DAY = date(2026, 11, 15)
TZ = timezone.tz_info
DIV_ZERO = {'类型': '表达式', '表达式': '1 / (订单金额 - 订单金额)'}


def test_empty_amount_raises_instead_of_one_yuan() -> None:
    """空公式不再按 1 元计。"""
    with pytest.raises(EvalError, match='公式不能为空'):
        evaluate_amount('', {})
    with pytest.raises(EvalError, match='公式不能为空'):
        evaluate_amount('   ', {})
    assert evaluate_amount('2 + 3', {}) == Decimal('5.00')


def test_division_by_zero_raises() -> None:
    """除零不再静默变成 0 或假。"""
    with pytest.raises(EvalError):
        evaluate_amount('1 / (订单金额 - 订单金额)', {'订单金额': 20})
    with pytest.raises(EvalError):
        evaluate_condition('1 / (日单量 - 日单量)', {'日单量': 3})


def test_empty_formula_rejected_at_compile() -> None:
    """空表达式和空公式都不能编译通过。"""
    with pytest.raises(CompileError, match='请填写'):
        compile_formula(None)
    with pytest.raises(CompileError, match='请填写表达式'):
        compile_formula({'类型': '表达式', '表达式': '   '}, CalcStage.per_order.value)
    result = validate_item(CalcStage.per_order.value, None, {'类型': '表达式', '表达式': ''})
    assert result.ok is False
    assert any('表达式' in item or '公式' in item for item in result.errors)


def _item(name: str, formula: dict | None, *, formula_expr: str | None = None) -> PlanItemView:
    expr = formula_expr if formula_expr is not None else compile_formula(formula, CalcStage.per_order.value)
    return PlanItemView(
        id=1,
        subject_id=1,
        name=name,
        stage=CalcStage.per_order.value,
        sort_order=0,
        condition_json=None,
        formula_json=formula,
        condition_expr='True',
        formula_expr=expr,
        enabled=True,
        direction=SubjectDirection.bonus.value,
        include_in_gross=True,
    )


def _order(oid: int, order_no: str) -> SimpleNamespace:
    moment = datetime(DAY.year, DAY.month, DAY.day, 10, 0, tzinfo=TZ)
    return SimpleNamespace(
        id=oid,
        order_no=order_no,
        site_id=1,
        rider_id=7,
        biz_date=DAY,
        distance_km=Decimal('1.20'),
        weight_jin=Decimal('2.00'),
        order_time=moment,
        deliver_time=moment.replace(minute=20),
        status=OrderStatus.completed.value,
        amount=Decimal('20.00'),
    )


def _run(orders: list[SimpleNamespace], item: PlanItemView) -> CalcResult:
    return run_calc_pipeline(
        CalcInput(
            rider_id=7,
            site_id=1,
            period_start=DAY,
            period_end=DAY,
            hire_date=date(2026, 1, 1),
            leave_date=None,
            employ_type='part_time',
            segments=[Segment(plan_version_id=1, start_date=DAY, end_date=DAY, items=[item])],
            orders=orders,
            day_flags={},
            employ_history=[],
            adjustments=[],
            advances=[],
            covered_dates={DAY},
            site_order_dates={DAY},
            rider_job_no='IT0007',
            rider_name='周试算',
        )
    )


def test_div_zero_warns_per_order_and_dedups() -> None:
    """同一项按订单号去重；不同订单各留一条，金额仍按 0。"""
    item = _item('除零单价', DIV_ZERO)
    distinct = _run([_order(1, 'A001'), _order(2, 'A002')], item)
    warnings = [item for item in distinct.warnings if '公式求值失败' in item]
    assert len(warnings) == 2
    assert any('A001' in item and '除零单价' in item for item in warnings)
    assert any('A002' in item and '周试算' in item for item in warnings)
    assert distinct.per_order_total == Decimal('0.00')

    duplicated = _run([_order(1, 'A001'), _order(2, 'A001')], item)
    duplicated_warnings = [item for item in duplicated.warnings if '公式求值失败' in item]
    assert len(duplicated_warnings) == 1


def test_blank_formula_expr_warns_and_is_not_one_yuan() -> None:
    """库里残留的空公式按 0 计并告警，不再变成 1 元。"""
    result = _run([_order(1, 'A009')], _item('空单价', None, formula_expr=''))
    assert result.per_order_total == Decimal('0.00')
    assert any('空单价' in item and '公式求值失败' in item for item in result.warnings)
