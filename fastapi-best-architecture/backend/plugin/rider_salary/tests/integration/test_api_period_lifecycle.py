"""周期全生命周期：生成、导入、算薪、锁账、标记发薪。"""

from factories import (
    activate_plan,
    bind_plan,
    calculate_period,
    create_c01_plan,
    create_rider,
    create_site,
    expect_ok,
    generate_month,
    get_period,
    import_completed_orders,
    lock_period,
    mark_paid,
    money,
)
from runtime import ApiClient


def test_four_role_tokens(
    client: ApiClient,
    admin_token: dict[str, str],
    salary_admin_token: dict[str, str],
    site_owner_token: dict[str, str],
    rider_token: dict[str, str],
) -> None:
    """四种预置角色都能登录，站点负责人和骑手只落到自己的种子数据。"""
    admin_sites = expect_ok(client.get('/rider-salary/sites', headers=admin_token, params={'page': 1, 'size': 50}))
    assert any(item['code'] == 'FXBASE' for item in admin_sites['items'])

    salary_sites = expect_ok(
        client.get('/rider-salary/sites', headers=salary_admin_token, params={'page': 1, 'size': 50})
    )
    assert any(item['code'] == 'FXBASE' for item in salary_sites['items'])

    owner_sites = expect_ok(client.get('/rider-salary/sites', headers=site_owner_token, params={'page': 1, 'size': 50}))
    assert [item['code'] for item in owner_sites['items']] == ['FXBASE']

    profile = expect_ok(client.get('/rider-salary/me/profile', headers=rider_token))
    assert profile['job_no'] == 'FXBASE001'


def test_period_full_lifecycle(client: ApiClient, admin_token: dict[str, str]) -> None:
    """生成周期、导入订单、算薪、锁账、标记发薪。两笔已完成订单按 C01 计 10 元。"""
    site = create_site(client, admin_token, name='生命周期站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='生命周期骑手', hire_date='2026-09-01')
    plan = create_c01_plan(client, admin_token)
    period = generate_month(client, admin_token, site_id=site['id'], month='2026-09')
    imported = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[
            ('LC-0901', '2026-09-10 12:00:00', '2026-09-10 12:20:00', '20.00'),
            ('LC-0902', '2026-09-11 13:00:00', '2026-09-11 13:20:00', '30.00'),
        ],
    )
    assert imported['success_rows'] == 2
    assert imported['failed_rows'] == 0

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
    calculated = calculate_period(client, admin_token, period['id'])
    assert calculated['queued'] is False
    assert calculated['calculated'] == 1, calculated

    lock_period(client, admin_token, period['id'], '集成测试锁账')
    mark_paid(client, admin_token, period['id'], '集成测试标记发薪')
    detail = get_period(client, admin_token, period['id'])
    assert detail['status'] == 'paid'
    assert detail['payroll_count'] >= 1
    assert money(detail['gross_total']) == money('10.00')
