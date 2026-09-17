"""方案项一句话说明单元测试。"""

from backend.plugin.rider_salary.schema.plan_item import GetPlanItemDetail
from backend.plugin.rider_salary.utils.item_summary import build_item_summary


def test_build_item_summary_prefers_remark() -> None:
    text = build_item_summary(
        remark='  夜间窗口加价  ',
        condition_expr='送达小时 >= 22',
        formula_expr='2',
    )
    assert text == '夜间窗口加价'


def test_build_item_summary_from_exprs() -> None:
    text = build_item_summary(
        condition_expr='配送距离 > 5',
        formula_expr='(配送距离 - 5) * 0.8',
    )
    assert text == '条件 配送距离 > 5；(配送距离 - 5) * 0.8'


def test_build_item_summary_skips_true_condition() -> None:
    text = build_item_summary(condition_expr='True', formula_expr='2')
    assert text == '2'


def test_build_item_summary_from_json_when_no_expr() -> None:
    text = build_item_summary(
        condition_json={'逻辑': '且', '条件': [{'字段': '周期有效单量', '运算符': '>=', '值': 300}]},
        formula_json={'类型': '固定金额', '金额': 200},
    )
    assert '周期有效单量 >= 300' in text
    assert '固定金额 200' in text


def test_build_item_summary_empty() -> None:
    assert build_item_summary() == '—'


def test_get_plan_item_detail_fills_summary() -> None:
    detail = GetPlanItemDetail(
        id=1,
        plan_version_id=2,
        subject_id=3,
        name='基础单量奖',
        stage='period',
        sort_order=1,
        condition_json=None,
        formula_json={'类型': '固定金额', '金额': 1.5},
        condition_expr='True',
        formula_expr='1.5',
        enabled=True,
        remark=None,
    )
    assert detail.summary == '1.5'
