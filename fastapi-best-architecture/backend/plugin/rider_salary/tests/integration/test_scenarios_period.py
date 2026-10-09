"""E1、E2、E3：第二轮反冲、应算未算锁账、补发不全不得再锁。"""

from factories import (
    bind_plan,
    calculate_period,
    carry_forward_period,
    create_rider,
    effective_payroll,
    expect_error,
    expect_ok,
    import_completed_orders,
    live_net,
    lock_period,
    money,
    month_bounds,
    order_row,
    period_payrolls,
    provision_c01_month,
    reverse_period,
)
from runtime import ApiClient


def test_e1_second_reversal_can_recalculate(client: ApiClient, admin_token: dict[str, str]) -> None:
    """E1 / P0-07：锁账、反冲、重算、再锁、再反冲、再重算都成功，有效实发仍是 5 元。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-08',
        orders=[order_row('E1-0801', '2026-08-01')],
        hire_date='2026-08-01',
        rider_name='第二轮反冲骑手',
        site_name='第二轮反冲站点',
    )
    period_id = ready['period']['id']
    rider_id = ready['rider']['id']
    original = money('5.00')

    calculate_period(client, admin_token, period_id)
    lock_period(client, admin_token, period_id, '第一轮锁账')
    reverse_period(client, admin_token, period_id, '第一轮反冲')
    first = calculate_period(client, admin_token, period_id)
    assert first['calculated'] == 1
    lock_period(client, admin_token, period_id, '补发后锁账')

    reverse_period(client, admin_token, period_id, '第二轮反冲')
    second = calculate_period(client, admin_token, period_id)
    assert second['calculated'] == 1, second
    lock_period(client, admin_token, period_id, '第二轮补发后锁账')

    payrolls = period_payrolls(client, admin_token, period_id)
    effective = effective_payroll(payrolls, rider_id)
    assert effective is not None
    assert effective['kind'] == 'supplement'
    assert money(effective['net']) == original
    assert live_net(payrolls, rider_id) == original


def test_e2_lock_rejects_rider_without_payroll(client: ApiClient, admin_token: dict[str, str]) -> None:
    """E2 / P0-01：有订单没算薪不能锁账；全员算完可以锁；回退作废草稿后再锁仍拒绝。"""
    site_ready = provision_c01_month(
        client,
        admin_token,
        month='2026-09',
        orders=[order_row(f'E2A-{day}', f'2026-09-{day}') for day in ('01', '02', '03', '04', '05')],
        hire_date='2026-09-01',
        rider_name='已算薪骑手',
        site_name='应算未算站点',
    )
    site = site_ready['site']
    rider_a = site_ready['rider']
    period_id = site_ready['period']['id']
    rider_b = create_rider(
        client,
        admin_token,
        site_id=site['id'],
        name='未算薪骑手',
        hire_date='2026-09-01',
    )
    imported = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider_b['job_no'],
        rows=[order_row(f'E2B-{day}', f'2026-09-{day}') for day in ('06', '07', '08', '09', '10')],
    )
    assert imported['success_rows'] == 5
    start, _end = month_bounds('2026-09')
    bind_plan(
        client,
        admin_token,
        rider_id=rider_b['id'],
        version_id=site_ready['plan']['version_id'],
        start_date=start,
    )

    only_a = expect_ok(
        client.post(
            f'/rider-salary/periods/{period_id}/calculate',
            headers=admin_token,
            json={'rider_ids': [rider_a['id']]},
        )
    )
    assert only_a['calculated'] == 1
    blocked = client.post(
        f'/rider-salary/periods/{period_id}/lock',
        headers=admin_token,
        json={'reason': '漏算也锁'},
    )
    message = expect_error(blocked)
    assert rider_b['job_no'] in message
    assert '未算薪' in message

    everyone = calculate_period(client, admin_token, period_id)
    assert everyone['calculated'] == 2
    lock_period(client, admin_token, period_id, '全员算完后锁账')

    fresh = provision_c01_month(
        client,
        admin_token,
        month='2026-10',
        orders=[order_row('E2C-1001', '2026-10-01')],
        hire_date='2026-10-01',
        rider_name='回退作废骑手',
        site_name='回退作废站点',
    )
    calculate_period(client, admin_token, fresh['period']['id'])
    expect_ok(
        client.post(
            f'/rider-salary/plan-versions/{fresh["plan"]["version_id"]}/rollback',
            headers=admin_token,
            json={'reason': '作废草稿', 'confirm_text': ''},
        )
    )
    voided_lock = client.post(
        f'/rider-salary/periods/{fresh["period"]["id"]}/lock',
        headers=admin_token,
        json={'reason': '草稿没了也锁'},
    )
    voided_message = expect_error(voided_lock)
    assert fresh['rider']['job_no'] in voided_message
    assert rider_a['job_no'] not in voided_message


def test_e3_reopened_period_needs_supplement(client: ApiClient, admin_token: dict[str, str]) -> None:
    """E3 / P0-02：反冲后不补算不能再锁；补算或沿用原单后，周期净额等于原单。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-09',
        orders=[order_row('E3-0901', '2026-09-02')],
        hire_date='2026-09-01',
        rider_name='补发骑手',
        site_name='补发站点',
    )
    period_id = ready['period']['id']
    rider_id = ready['rider']['id']
    original = money('5.00')

    calculate_period(client, admin_token, period_id)
    lock_period(client, admin_token, period_id, '补发前锁账')
    reverse_period(client, admin_token, period_id, '先反冲')
    blocked = client.post(
        f'/rider-salary/periods/{period_id}/lock',
        headers=admin_token,
        json={'reason': '不补算直接锁'},
    )
    message = expect_error(blocked)
    assert ready['rider']['job_no'] in message
    assert '补发' in message

    calculate_period(client, admin_token, period_id)
    slips = period_payrolls(client, admin_token, period_id)
    supplement = effective_payroll(slips, rider_id)
    assert supplement is not None
    assert supplement['kind'] == 'supplement'
    assert money(supplement['net']) == original
    lock_period(client, admin_token, period_id, '补算后锁账')
    assert live_net(period_payrolls(client, admin_token, period_id), rider_id) == original

    reused = provision_c01_month(
        client,
        admin_token,
        month='2026-11',
        orders=[order_row('E3-1101', '2026-11-03')],
        hire_date='2026-11-01',
        rider_name='沿用原单骑手',
        site_name='沿用原单站点',
    )
    reused_id = reused['period']['id']
    calculate_period(client, admin_token, reused_id)
    lock_period(client, admin_token, reused_id, '沿用前锁账')
    reverse_period(client, admin_token, reused_id, '沿用前反冲')
    carried = carry_forward_period(client, admin_token, reused_id)
    assert money(carried['net_total']) == original
    lock_period(client, admin_token, reused_id, '沿用后锁账')
    assert live_net(period_payrolls(client, admin_token, reused_id), reused['rider']['id']) == original
