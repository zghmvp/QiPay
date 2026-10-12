"""即时预览求值失败时返回中文 400，不按 0 元吞掉。"""

from factories import expect_error
from runtime import ApiClient


def test_sample_formula_div_zero_is_chinese_400(client: ApiClient, admin_token: dict[str, str]) -> None:
    """除零的公式样例求值返回 400，并指出计薪项。"""
    response = client.post(
        '/rider-salary/engine/evaluate-sample',
        headers=admin_token,
        json={
            'stage': 'per_order',
            'formula_json': {
                '类型': '表达式',
                '表达式': '1 / (订单金额 - 订单金额)',
                '名称': '除零单价',
            },
            'context': {'订单金额': 10},
        },
    )
    assert response.status_code == 400
    message = expect_error(response)
    assert message == '计薪项「除零单价」公式求值失败：除零'


def test_sample_condition_missing_variable_is_chinese_400(client: ApiClient, admin_token: dict[str, str]) -> None:
    """条件求值失败同样返回 400，不按未命中的 0 元处理。"""
    response = client.post(
        '/rider-salary/engine/evaluate-sample',
        headers=admin_token,
        json={
            'stage': 'per_order',
            'condition_json': {'字段': '订单金额', '运算符': '>', '值': 0},
            'formula_json': {'类型': '固定金额', '金额': 1, '名称': '底薪'},
            'context': {},
        },
    )
    assert response.status_code == 400
    message = expect_error(response)
    assert message == '计薪项「底薪」条件求值失败：变量「订单金额」未提供'
