"""离职计薪：9/10 离职按在职天数分摊，离职次月无订单则不进算薪名单。"""

import uuid

from factories import (
    activate_plan,
    bind_plan,
    calculate_period,
    create_c01_plan,
    create_rider,
    create_site,
    expect_ok,
    generate_month,
    import_completed_orders,
    money,
    subject_id,
)
from runtime import ApiClient


def _create_daily_base_plan(client: ApiClient, headers: dict[str, str]) -> dict[str, int]:
    """按日固定 10 元，底薪 3000 × 方案生效天数 / 周期天数。"""
    plan = expect_ok(
        client.post(
            '/rider-salary/plans',
            headers=headers,
            json={
                'code': f'LV{uuid.uuid4().hex[:6].upper()}',
                'name': '离职分摊方案',
                'short_name': '离职',
                'color': '#1677ff',
                'description': '按日补贴加按在职天数分摊的底薪。',
                'status': 'enable',
            },
        )
    )
    version = expect_ok(
        client.post(
            '/rider-salary/plan-versions',
            headers=headers,
            json={'plan_id': plan['id'], 'mode_tag': 'base_plus_commission', 'remark': '离职分摊'},
        )
    )
    expect_ok(
        client.put(
            f'/rider-salary/plan-versions/{version["id"]}/items',
            headers=headers,
            json=[
                {
                    'subject_id': subject_id(client, headers, 'BONUS_HOLIDAY'),
                    'name': '按日补贴',
                    'stage': 'daily',
                    'sort_order': 10,
                    'formula_json': {'类型': '固定金额', '金额': 10},
                    'enabled': True,
                },
                {
                    'subject_id': subject_id(client, headers, 'BASE_SALARY'),
                    'name': '底薪',
                    'stage': 'period',
                    'sort_order': 30,
                    'formula_json': {'类型': '表达式', '表达式': '3000 * 方案生效天数 / 周期天数'},
                    'enabled': True,
                },
            ],
        )
    )
    return {'plan_id': int(plan['id']), 'version_id': int(version['id'])}


def _leave(client: ApiClient, headers: dict[str, str], rider_id: int, leave_date: str) -> None:
    expect_ok(
        client.put(
            f'/rider-salary/riders/{rider_id}/leave',
            headers=headers,
            json={'leave_date': leave_date, 'reason': '个人原因'},
        )
    )


def _payrolls(client: ApiClient, headers: dict[str, str], period_id: int, rider_id: int) -> list[dict]:
    data = expect_ok(
        client.get(
            '/rider-salary/payrolls',
            headers=headers,
            params={'period_id': period_id, 'rider_id': rider_id, 'page': 1, 'size': 20},
        )
    )
    return list(data['items'])


def test_leave_on_sep_10_prorates_and_next_month_omits_rider(client: ApiClient, admin_token: dict[str, str]) -> None:
    """9/10 离职：按日 10 天 × 10 元，底薪 3000 × 10/30；10 月没有订单和奖惩，不进算薪名单。"""
    site = create_site(client, admin_token, name='离职分摊站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='九月离职骑手', hire_date='2026-01-01')
    plan = _create_daily_base_plan(client, admin_token)
    activate_plan(
        client,
        admin_token,
        version_id=plan['version_id'],
        rider_id=rider['id'],
        start_date='2026-09-01',
        end_date='2026-09-30',
    )
    bind_plan(
        client,
        admin_token,
        rider_id=rider['id'],
        version_id=plan['version_id'],
        start_date='2026-09-01',
    )
    _leave(client, admin_token, rider['id'], '2026-09-10')

    september = generate_month(client, admin_token, site_id=site['id'], month='2026-09')
    calculated = calculate_period(client, admin_token, september['id'])
    assert calculated['queued'] is False
    assert calculated['calculated'] == 1

    rows = _payrolls(client, admin_token, september['id'], rider['id'])
    assert len(rows) == 1
    assert money(rows[0]['daily_total']) == money('100.00')
    assert money(rows[0]['period_total']) == money('1000.00')
    detail = expect_ok(client.get(f'/rider-salary/payrolls/{rows[0]["id"]}', headers=admin_token))
    daily_dates = [item['biz_date'] for item in detail['details']['daily']]
    assert daily_dates[0] == '2026-09-01'
    assert daily_dates[-1] == '2026-09-10'
    assert len(daily_dates) == 10
    salary = detail['details']['period'][0]
    assert money(salary['amount']) == money('1000.00')
    assert int(salary['calc_trace']['变量']['方案生效天数']) == 10
    assert int(salary['calc_trace']['变量']['周期天数']) == 30

    october = generate_month(client, admin_token, site_id=site['id'], month='2026-10')
    next_month = calculate_period(client, admin_token, october['id'])
    assert next_month['queued'] is False
    assert next_month['calculated'] == 0
    assert _payrolls(client, admin_token, october['id'], rider['id']) == []


def test_resigned_rider_with_next_month_order_stays_on_roster(client: ApiClient, admin_token: dict[str, str]) -> None:
    """离职日早于 10 月，但 10 月已有订单：仍进入算薪名单，离职日之后的订单不计薪。"""
    site = create_site(client, admin_token, name='离职仍有订单站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='十月有单骑手', hire_date='2026-01-01')
    plan = create_c01_plan(client, admin_token)
    imported = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[('LV-1005', '2026-10-05 12:00:00', '2026-10-05 12:20:00', '20.00')],
    )
    assert imported['success_rows'] == 1
    activate_plan(
        client,
        admin_token,
        version_id=plan['version_id'],
        rider_id=rider['id'],
        start_date='2026-10-01',
        end_date='2026-10-31',
    )
    bind_plan(
        client,
        admin_token,
        rider_id=rider['id'],
        version_id=plan['version_id'],
        start_date='2026-09-01',
    )
    _leave(client, admin_token, rider['id'], '2026-09-10')

    october = generate_month(client, admin_token, site_id=site['id'], month='2026-10')
    calculated = calculate_period(client, admin_token, october['id'])
    assert calculated['calculated'] == 1
    assert any('离职' in warning for warning in calculated['warnings'])
    rows = _payrolls(client, admin_token, october['id'], rider['id'])
    assert len(rows) == 1
    assert money(rows[0]['per_order_total']) == money('0.00')
    assert money(rows[0]['daily_total']) == money('0.00')
