"""P2-10：字段乘单价语义与单价精度、底薪模板占位符。"""

from decimal import Decimal

import pytest

from backend.common.exception.errors import RequestError
from backend.plugin.rider_salary.engine.compiler import FORMULA_TEMPLATES, CompileError, compile_formula, validate_item
from backend.plugin.rider_salary.engine.evaluator import evaluate_amount
from backend.plugin.rider_salary.enums import CalcStage

PER_ORDER = CalcStage.per_order.value
PERIOD = CalcStage.period.value


def _rate(rate: object, start: object = 5) -> dict:
    return {'类型': '字段乘单价', '字段': '配送距离', '单价': rate, '起算值': start}


def test_field_rate_clamps_excess_before_multiplying() -> None:
    """实现口径：先对超出起算值的部分取 0，再乘单价。负单价结果可为负。"""
    expr = compile_formula(_rate(0.8), PER_ORDER)
    assert expr == '最大值(0, (配送距离 - 5)) * 0.8'
    assert evaluate_amount(expr, {'配送距离': 7.2}) == Decimal('1.76')
    assert evaluate_amount(expr, {'配送距离': 3}) == Decimal('0.00')

    negative = compile_formula(_rate(-1), PER_ORDER)
    assert negative == '最大值(0, (配送距离 - 5)) * -1'
    assert evaluate_amount(negative, {'配送距离': 8}) == Decimal('-3.00')


def test_field_rate_accepts_up_to_four_decimals() -> None:
    assert compile_formula(_rate(Decimal('1.2300'), 0), PER_ORDER) == '最大值(0, (配送距离 - 0)) * 1.2300'
    assert compile_formula(_rate(0.0001, 0), PER_ORDER) == '最大值(0, (配送距离 - 0)) * 0.0001'
    assert compile_formula(_rate(8, 0), PER_ORDER) == '最大值(0, (配送距离 - 0)) * 8'
    assert validate_item(PER_ORDER, {}, _rate('0.123400', 0)).ok is True


def test_field_rate_rejects_more_than_four_decimals() -> None:
    raw = _rate('1.23456', 0)
    with pytest.raises(CompileError, match='单价最多保留 4 位小数'):
        compile_formula(raw, PER_ORDER)
    result = validate_item(PER_ORDER, {}, raw)
    assert result.ok is False
    assert result.errors == ['单价最多保留 4 位小数']
    # 保存方案项时 plan_service 把这些错误包成 RequestError，默认 HTTP 400
    err = RequestError(msg='；'.join(result.errors))
    assert err.code == 400
    assert err.msg == '单价最多保留 4 位小数'

    five = validate_item(PER_ORDER, {}, _rate('0.123450', 0))
    assert five.ok is False
    assert five.errors == ['单价最多保留 4 位小数']


def test_base_salary_placeholder_must_be_replaced_before_compile() -> None:
    template = next(item for item in FORMULA_TEMPLATES if item['type'] == '底薪分摊')
    assert template['placeholders'][0]['token'] == '{底薪金额}'
    assert template['placeholders'][0]['label'] == '底薪金额'

    skeleton = template['skeleton']
    with pytest.raises(CompileError, match='请先替换占位符「底薪金额」'):
        compile_formula(skeleton, PERIOD)
    blocked = validate_item(PERIOD, {}, skeleton)
    assert blocked.ok is False
    assert blocked.errors == ['请先替换占位符「底薪金额」']
    assert all('未注册字段' not in msg and '语法' not in msg for msg in blocked.errors)

    bare = validate_item(PERIOD, {}, {'类型': '表达式', '表达式': '底薪金额 × 方案生效天数 / 周期天数'})
    assert bare.errors == ['请先替换占位符「底薪金额」']

    weird = validate_item(PERIOD, {}, {'类型': '表达式', '表达式': '底薪金额额'})
    assert any('未注册字段' in msg for msg in weird.errors)
    assert all('占位符' not in msg for msg in weird.errors)

    replaced = str(skeleton['表达式']).replace('{底薪金额}', '2000')
    expr = compile_formula({'类型': '表达式', '表达式': replaced}, PERIOD)
    assert expr == '2000 * 方案生效天数 / 周期天数'
    assert evaluate_amount(expr, {'方案生效天数': 10, '周期天数': 30}) == Decimal('666.67')

    save_err = RequestError(msg='；'.join(blocked.errors))
    assert save_err.code == 400
    assert save_err.msg == '请先替换占位符「底薪金额」'


def test_builtin_templates_without_placeholders_still_compile() -> None:
    stages = {
        '固定金额': None,
        '字段乘单价': PER_ORDER,
        '阶梯': PERIOD,
        '表达式': PERIOD,
    }
    compiled = 0
    for template in FORMULA_TEMPLATES:
        if template['type'] not in stages:
            continue
        compile_formula(template['skeleton'], stages[template['type']])
        compiled += 1
    assert compiled == 4


def test_guarantee_expression_is_not_a_base_salary_placeholder() -> None:
    result = validate_item(PERIOD, {}, {'类型': '表达式', '表达式': '最大值(0, 3000 - 本期已计金额)'})
    assert result.ok is True
    assert result.formula_expr == '最大值(0, 3000 - 本期已计金额)'
