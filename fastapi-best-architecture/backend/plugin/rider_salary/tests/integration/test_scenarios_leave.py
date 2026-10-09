"""离线-2：9 月 10 日离职按在职闭区间计薪，离职次月无订单和奖惩时不进算薪名单。"""

from factories import (
    activate_plan,
    bind_plan,
    calculate_period,
    create_plan,
    create_rider,
    create_site,
    expect_ok,
    generate_month,
    money,
    month_bounds,
)
from runtime import ApiClient


def test_offline2_leave_prorates_and_drops_next_month(client: ApiClient, admin_token: dict[str, str]) -> None:
    """离线-2 / P0-03：离职日当天计薪。按日 10 天 × 10 = 100.00，底薪 3000 × 10/30 = 1000.00。"""
    site = create_site(client, admin_token, name='离职计薪站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='离职骑手', hire_date='2026-01-01')
    plan = create_plan(
        client,
        admin_token,
        name='餐补加底薪',
        short_name='餐补',
        items=[
            {
                'subject_code': 'BONUS_HIGH_TEMP',
                'name': '餐补',
                'stage': 'daily',
                'sort_order': 0,
                'formula_json': {'类型': '固定金额', '金额': 10},
            },
            {
                'subject_code': 'BASE_SALARY',
                'name': '底薪',
                'stage': 'period',
                'sort_order': 1,
                'formula_json': {'类型': '表达式', '表达式': '3000 * 方案生效天数 / 周期天数'},
            },
        ],
    )
    start, end = month_bounds('2026-09')
    activate_plan(
        client,
        admin_token,
        version_id=plan['version_id'],
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    bind_plan(client, admin_token, rider_id=rider['id'], version_id=plan['version_id'], start_date=start)
    expect_ok(
        client.put(
            f'/rider-salary/riders/{rider["id"]}/leave',
            headers=admin_token,
            json={'leave_date': '2026-09-10', 'reason': '个人原因'},
        )
    )

    september = generate_month(client, admin_token, site_id=site['id'], month='2026-09')
    calculated = calculate_period(client, admin_token, september['id'])
    assert calculated['queued'] is False
    assert calculated['calculated'] == 1
    own = expect_ok(
        client.get(
            '/rider-salary/payrolls',
            headers=admin_token,
            params={'period_id': september['id'], 'rider_id': rider['id'], 'page': 1, 'size': 20},
        )
    )['items']
    assert len(own) == 1
    assert money(own[0]['daily_total']) == money('100.00')
    assert money(own[0]['period_total']) == money('1000.00')
    detail = expect_ok(client.get(f'/rider-salary/payrolls/{own[0]["id"]}', headers=admin_token))
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
    later = expect_ok(
        client.get(
            '/rider-salary/payrolls',
            headers=admin_token,
            params={'period_id': october['id'], 'rider_id': rider['id'], 'page': 1, 'size': 20},
        )
    )
    assert later['items'] == []
