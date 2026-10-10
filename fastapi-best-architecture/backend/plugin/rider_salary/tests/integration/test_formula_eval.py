"""P0-17：除零告警、试算闸门、空公式拒绝、非草稿试算不落库。"""

import httpx

from factories import (
    activate_plan,
    bind_plan,
    calculate_period,
    create_c01_plan,
    create_plan,
    create_rider,
    create_site,
    expect_error,
    expect_ok,
    generate_month,
    get_period,
    import_completed_orders,
    money,
    month_bounds,
    order_row,
    subject_id,
)
from runtime import ApiClient

DIV_ZERO = {'类型': '表达式', '表达式': '1 / (订单金额 - 订单金额)'}
DAY_DIV_ZERO = {'类型': '表达式', '表达式': '1 / 日单量'}


def _trial(
    client: ApiClient,
    headers: dict[str, str],
    version_id: int,
    rider_id: int,
    start: str,
    end: str,
) -> httpx.Response:
    return client.post(
        f'/rider-salary/plan-versions/{version_id}/trial',
        headers=headers,
        json={'rider_id': rider_id, 'start_date': start, 'end_date': end},
    )


def test_div_zero_calc_warns_and_blocks_lock_and_trial(client: ApiClient, admin_token: dict[str, str]) -> None:
    """除零公式算薪产生告警并阻断锁账；带订单的试算不通过。"""
    site = create_site(client, admin_token, name='除零算薪站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='除零骑手', hire_date='2026-01-01')
    failing = create_plan(
        client,
        admin_token,
        name='除零逐单',
        short_name='除零',
        items=[
            {
                'subject_code': 'BASE_UNIT_PRICE',
                'name': '除零单价',
                'stage': 'per_order',
                'sort_order': 0,
                'formula_json': DIV_ZERO,
            }
        ],
    )
    imported = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[order_row('EV-1115', '2026-11-15', '20.00')],
    )
    assert imported['success_rows'] == 1
    trial = _trial(client, admin_token, failing['version_id'], rider['id'], '2026-11-15', '2026-11-15')
    body = expect_ok(trial)
    assert body['passed'] is False
    assert any('除零单价' in item and '公式求值失败' in item for item in body['warnings'])
    version = expect_ok(client.get(f'/rider-salary/plan-versions/{failing["version_id"]}', headers=admin_token))
    assert version['trial_passed'] is False
    blocked = client.post(f'/rider-salary/plan-versions/{failing["version_id"]}/activate', headers=admin_token)
    assert '试算' in expect_error(blocked)

    daily = create_plan(
        client,
        admin_token,
        name='除零按日',
        short_name='按日',
        items=[
            {
                'subject_code': 'BONUS_HOLIDAY',
                'name': '除零补贴',
                'stage': 'daily',
                'sort_order': 0,
                'formula_json': DAY_DIV_ZERO,
            }
        ],
    )
    activate_plan(
        client,
        admin_token,
        version_id=daily['version_id'],
        rider_id=rider['id'],
        start_date='2026-11-15',
        end_date='2026-11-15',
    )
    bind_plan(client, admin_token, rider_id=rider['id'], version_id=daily['version_id'], start_date='2026-11-01')
    period = generate_month(client, admin_token, site_id=site['id'], month='2026-11')
    calculated = calculate_period(client, admin_token, period['id'])
    assert any('除零补贴' in item and '公式求值失败' in item for item in calculated['warnings'])
    detail = get_period(client, admin_token, period['id'])
    assert any('除零补贴' in item and '公式求值失败' in item for item in detail['calc_warnings'])
    payrolls = [row for row in detail['payrolls'] if row['rider_id'] == rider['id']]
    assert payrolls
    assert any('除零补贴' in item and 'EV-1115' not in item for item in (payrolls[0]['warnings'] or []))
    locked = client.post(
        f'/rider-salary/periods/{period["id"]}/lock',
        headers=admin_token,
        json={'reason': '求值失败不应锁账'},
    )
    message = expect_error(locked)
    assert '公式求值失败' in message
    assert rider['name'] in message
    assert '除零补贴' in message


def test_empty_formula_cannot_be_saved(client: ApiClient, admin_token: dict[str, str]) -> None:
    """空表达式无法保存。"""
    plan = create_c01_plan(client, admin_token)
    message = expect_error(
        client.put(
            f'/rider-salary/plan-versions/{plan["version_id"]}/items',
            headers=admin_token,
            json=[
                {
                    'subject_id': subject_id(client, admin_token, 'BASE_UNIT_PRICE'),
                    'name': '空公式',
                    'stage': 'per_order',
                    'sort_order': 0,
                    'formula_json': {'类型': '表达式', '表达式': ''},
                    'enabled': True,
                }
            ],
        )
    )
    assert '表达式' in message or '公式' in message


def test_zero_order_trial_returns_400(client: ApiClient, admin_token: dict[str, str]) -> None:
    """0 单试算返回 400，且不记为试算通过。"""
    site = create_site(client, admin_token, name='零单试算站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='零单骑手', hire_date='2026-01-01')
    plan = create_c01_plan(client, admin_token)
    start, end = month_bounds('2026-11')
    message = expect_error(_trial(client, admin_token, plan['version_id'], rider['id'], start, end))
    assert '已完成订单' in message
    version = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert version['trial_passed'] is False


def test_active_trial_does_not_rewrite_snapshot(client: ApiClient, admin_token: dict[str, str]) -> None:
    """非草稿版本再试算不改 trial_snapshot。"""
    site = create_site(client, admin_token, name='试算快照站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='快照骑手', hire_date='2026-01-01')
    plan = create_c01_plan(client, admin_token)
    start, end = month_bounds('2026-11')
    first = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[order_row('EV-1102', '2026-11-02', '20.00')],
    )
    assert first['success_rows'] == 1
    activate_plan(
        client,
        admin_token,
        version_id=plan['version_id'],
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    before = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert before['status'] == 'active'
    snapshot = before['trial_snapshot']
    second = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[order_row('EV-1103', '2026-11-03', '20.00')],
    )
    assert second['success_rows'] == 1
    again = expect_ok(_trial(client, admin_token, plan['version_id'], rider['id'], start, end))
    assert money(again['summary']['per_order_total']) == money('10.00')
    after = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert after['trial_snapshot'] == snapshot
    assert money(after['trial_snapshot']['per_order_total']) == money('5.00')
