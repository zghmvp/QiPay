"""Cycle 3 案例金标（DB-free）：C05B=4200 / C08 1995·2400 / C11=4890；重叠门槛双计。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from backend.plugin.rider_salary.engine.operators import OP_GE, OP_LE, OP_LT
from backend.plugin.rider_salary.enums import CalcStage
from backend.plugin.rider_salary.service.calc_service import run_calc_pipeline
from backend.plugin.rider_salary.tests.test_adversarial_cycle2_backend import _input
from backend.plugin.rider_salary.tests.test_calc_pipeline import _item, _order

D = Decimal
START = date(2026, 9, 1)


def _orders(count: int) -> list:
    return [_order(i, f'C3-{i}', START + timedelta(days=i % 30)) for i in range(count)]


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


def _c08_items(*, overlap: bool) -> list:
    low_op = OP_LE if overlap else OP_LT
    return [
        _item(
            pk=1,
            subject_id=3,
            name='门槛低于400',
            stage=CalcStage.period.value,
            sort_order=10,
            condition={'逻辑': '且', '条件': [{'字段': '周期有效单量', '运算符': low_op, '值': 400}]},
            formula={'类型': '字段乘单价', '字段': '周期有效单量', '单价': 5, '起算值': 0},
        ),
        _item(
            pk=2,
            subject_id=3,
            name='门槛满400',
            stage=CalcStage.period.value,
            sort_order=20,
            condition={'逻辑': '且', '条件': [{'字段': '周期有效单量', '运算符': OP_GE, '值': 400}]},
            formula={'类型': '字段乘单价', '字段': '周期有效单量', '单价': 6, '起算值': 0},
        ),
    ]


def _c08_empty_overlap() -> list:
    return [
        _item(
            pk=1,
            subject_id=3,
            name='门槛低于400',
            stage=CalcStage.period.value,
            sort_order=10,
            condition={},
            formula={'类型': '字段乘单价', '字段': '周期有效单量', '单价': 5, '起算值': 0},
        ),
        _item(
            pk=2,
            subject_id=3,
            name='门槛满400',
            stage=CalcStage.period.value,
            sort_order=20,
            condition={},
            formula={'类型': '字段乘单价', '字段': '周期有效单量', '单价': 6, '起算值': 0},
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
            condition={'逻辑': '且', '条件': [{'字段': '日有效单量', '运算符': OP_GE, '值': 30}]},
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
    rows: list = []
    oid = 1
    for offset in range(30):
        day = START + timedelta(days=offset)
        n = 32 if offset < 5 else 20
        for _ in range(n):
            rows.append(_order(oid, f'C11-{oid}', day))
            oid += 1
    return rows


def test_fix_c05b_gross_4200() -> None:
    result = run_calc_pipeline(_input(orders=_orders(1200), items=_c05_items()))
    topup = next(row for row in result.details if row.name == '保底补足')
    assert result.valid_order_count == 1200
    assert result.per_order_total == D('4200.00')
    assert topup.amount == D('0.00')
    assert result.gross == D('4200.00')
    assert result.gross != D('3500.00')


def test_fix_c08_399_1995_and_400_2400() -> None:
    items = _c08_items(overlap=False)
    r399 = run_calc_pipeline(_input(orders=_orders(399), items=items))
    r400 = run_calc_pipeline(_input(orders=_orders(400), items=items))
    assert r399.gross == D('1995.00')
    assert r400.gross == D('2400.00')
    assert r399.gross != D('4389.00')


def test_fix_c08_overlap_400_double_counts() -> None:
    """≤400 与 ≥400 在 400 单同时真 → 双计；保存层必须硬拦，本条只证引擎危险形态。"""
    items = _c08_items(overlap=True)
    result = run_calc_pipeline(_input(orders=_orders(400), items=items))
    assert result.gross == D('4400.00')
    exclusive = run_calc_pipeline(_input(orders=_orders(400), items=_c08_items(overlap=False)))
    assert exclusive.gross == D('2400.00')
    assert result.gross != exclusive.gross


def test_fix_c08_empty_conditions_399_double_counts() -> None:
    result = run_calc_pipeline(_input(orders=_orders(399), items=_c08_empty_overlap()))
    assert result.gross == D('4389.00')
    assert result.gross != D('1995.00')


def test_fix_c11_gross_4890() -> None:
    orders = _c11_orders()
    assert len(orders) == 660
    covered = {START + timedelta(days=i) for i in range(30)}
    data = _input(orders=orders, items=_c11_items())
    data.covered_dates = covered
    data.site_order_dates = covered
    result = run_calc_pipeline(data)
    assert result.valid_order_count == 660
    assert result.per_order_total == D('2640.00')
    assert result.daily_total == D('250.00')
    salary = next(row for row in result.details if row.name == '底薪')
    assert salary.amount == D('2000.00')
    assert result.gross == D('4890.00')
