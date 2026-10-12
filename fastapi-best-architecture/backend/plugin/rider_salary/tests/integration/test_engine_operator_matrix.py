"""公式运算符：补齐的条件可保存并求值，幂运算被拒。"""

import uuid

from factories import expect_error, expect_ok, subject_id
from runtime import ApiClient


def test_save_new_operators_and_reject_power(client: ApiClient, admin_token: dict[str, str]) -> None:
    """是否高温 ≠ 是、日期 ≥ 某日可写入方案项并求值；2 ** 10 保存被拒。"""
    operators = expect_ok(client.get('/rider-salary/engine/operators', headers=admin_token))
    assert operators['bool'] == ['=', '≠']
    assert '≥' in operators['date']
    assert operators['time'] == ['=', '≠', '在时段内']

    hot = {'字段': '是否高温', '运算符': '≠', '值': True}
    on_date = {'字段': '日期', '运算符': '≥', '值': '2026-09-01'}
    fixed = {'类型': '固定金额', '金额': 1}

    hot_eval = expect_ok(
        client.post(
            '/rider-salary/engine/evaluate-sample',
            headers=admin_token,
            json={'stage': 'per_order', 'condition_json': hot, 'formula_json': fixed, 'context': {'是否高温': False}},
        )
    )
    assert hot_eval['hit'] is True
    assert hot_eval['amount'] == 1
    hot_miss = expect_ok(
        client.post(
            '/rider-salary/engine/evaluate-sample',
            headers=admin_token,
            json={'stage': 'per_order', 'condition_json': hot, 'formula_json': fixed, 'context': {'是否高温': True}},
        )
    )
    assert hot_miss['hit'] is False

    date_hit = expect_ok(
        client.post(
            '/rider-salary/engine/evaluate-sample',
            headers=admin_token,
            json={
                'stage': 'per_order',
                'condition_json': on_date,
                'formula_json': fixed,
                'context': {'日期': '2026-09-01'},
            },
        )
    )
    assert date_hit['hit'] is True
    date_miss = expect_ok(
        client.post(
            '/rider-salary/engine/evaluate-sample',
            headers=admin_token,
            json={
                'stage': 'per_order',
                'condition_json': on_date,
                'formula_json': fixed,
                'context': {'日期': '2026-08-31'},
            },
        )
    )
    assert date_miss['hit'] is False

    code = f'OP{uuid.uuid4().hex[:6].upper()}'
    plan = expect_ok(
        client.post(
            '/rider-salary/plans',
            headers=admin_token,
            json={
                'code': code,
                'name': '运算符矩阵',
                'short_name': '运算',
                'color': '#1677ff',
                'description': '验证补齐后的条件可以保存',
                'status': 'enable',
            },
        )
    )
    version = expect_ok(
        client.post(
            '/rider-salary/plan-versions',
            headers=admin_token,
            json={'plan_id': plan['id'], 'mode_tag': 'per_order', 'remark': '运算符'},
        )
    )
    subject = subject_id(client, admin_token, 'BASE_UNIT_PRICE')
    saved = expect_ok(
        client.put(
            f'/rider-salary/plan-versions/{version["id"]}/items',
            headers=admin_token,
            json=[
                {
                    'subject_id': subject,
                    'name': '非高温补贴',
                    'stage': 'per_order',
                    'sort_order': 10,
                    'condition_json': hot,
                    'formula_json': fixed,
                    'enabled': True,
                },
                {
                    'subject_id': subject,
                    'name': '起始日补贴',
                    'stage': 'per_order',
                    'sort_order': 20,
                    'condition_json': on_date,
                    'formula_json': fixed,
                    'enabled': True,
                },
            ],
        )
    )
    exprs = {item['name']: item['condition_expr'] for item in saved['items']}
    assert exprs['非高温补贴'] == '是否高温 != True'
    assert exprs['起始日补贴'] == '日期 >= "2026-09-01"'

    message = expect_error(
        client.put(
            f'/rider-salary/plan-versions/{version["id"]}/items',
            headers=admin_token,
            json=[
                {
                    'subject_id': subject,
                    'name': '幂运算',
                    'stage': 'per_order',
                    'sort_order': 10,
                    'formula_json': {'类型': '表达式', '表达式': '2 ** 10'},
                    'enabled': True,
                }
            ],
        )
    )
    assert '**' in message
