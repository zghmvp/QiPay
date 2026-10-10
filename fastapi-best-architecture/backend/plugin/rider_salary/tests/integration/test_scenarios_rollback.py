"""E8、E12：回退归还预支，以及整期反冲后未受影响骑手不被双发。"""

from factories import (
    activate_plan,
    bind_plan,
    calculate_period,
    create_plan,
    create_rider,
    create_site,
    effective_payroll,
    expect_ok,
    generate_month,
    import_completed_orders,
    live_net,
    lock_period,
    money,
    month_bounds,
    open_rider_account,
    order_row,
    period_payrolls,
    use_shared_db_session,
)
from runtime import ApiClient

_PER_ORDER_20 = {'类型': '固定金额', '金额': 20}
_BASE_3000 = {'类型': '固定金额', '金额': 3000}


def _paid_advance(client: ApiClient, admin_token: dict[str, str], rider_headers: dict[str, str], amount: str) -> dict:
    created = expect_ok(
        client.post(
            '/rider-salary/me/advances',
            headers=rider_headers,
            json={'amount': amount, 'reason': '周转'},
        )
    )
    expect_ok(
        client.post(
            f'/rider-salary/advances/{created["id"]}/approve',
            headers=admin_token,
            json={'remark': '同意'},
        )
    )
    expect_ok(
        client.post(
            f'/rider-salary/advances/{created["id"]}/mark-paid',
            headers=admin_token,
            json={'remark': '已发放'},
        )
    )
    return expect_ok(client.get(f'/rider-salary/advances/{created["id"]}', headers=admin_token))


def test_e8_rollback_restores_deducted_advance(client: ApiClient, admin_token: dict[str, str]) -> None:
    """E8 / P0-06：草稿抵扣 3000 后回退该版本，预支剩余恢复为 3000，抵扣状态回到未抵扣。"""
    with use_shared_db_session():
        _assert_e8_rollback_restores_deducted_advance(client, admin_token)


def _assert_e8_rollback_restores_deducted_advance(client: ApiClient, admin_token: dict[str, str]) -> None:
    site = create_site(client, admin_token, name='预支归还站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='预支归还骑手', hire_date='2026-10-01')
    rider_headers = open_rider_account(client, admin_token, rider_id=rider['id'], job_no=rider['job_no'])
    advance = _paid_advance(client, admin_token, rider_headers, '3000.00')
    plan = create_plan(
        client,
        admin_token,
        name='底薪三千',
        short_name='三千',
        items=[
            {
                'subject_code': 'BASE_SALARY',
                'name': '底薪',
                'stage': 'period',
                'sort_order': 0,
                'formula_json': _BASE_3000,
            }
        ],
    )
    period = generate_month(client, admin_token, site_id=site['id'], month='2026-10')
    imported = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[order_row('E8-1001', '2026-10-02')],
    )
    assert imported['success_rows'] == 1
    start, end = month_bounds('2026-10')
    activate_plan(
        client,
        admin_token,
        version_id=plan['version_id'],
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    bind_plan(client, admin_token, rider_id=rider['id'], version_id=plan['version_id'], start_date=start)
    calculate_period(client, admin_token, period['id'])

    deducted = expect_ok(client.get(f'/rider-salary/advances/{advance["id"]}', headers=admin_token))
    assert money(deducted['deducted_amount']) == money('3000.00')
    assert money(deducted['remaining_amount']) == money('0.00')
    assert deducted['deduct_status'] == 'done'

    copied = expect_ok(
        client.post(
            f'/rider-salary/plan-versions/{plan["version_id"]}/rollback',
            headers=admin_token,
            json={'reason': '方案回退归还预支', 'confirm_text': ''},
        )
    )
    assert isinstance(copied['id'], int)
    assert copied['id'] != plan['version_id']
    assert isinstance(copied['version_no'], int)
    assert copied['version_no'] >= 2
    restored = expect_ok(client.get(f'/rider-salary/advances/{advance["id"]}', headers=admin_token))
    assert money(restored['remaining_amount']) == money('3000.00')
    assert money(restored['deducted_amount']) == money('0.00')
    assert restored['deduct_status'] == 'none'
    slips = period_payrolls(client, admin_token, period['id'])
    assert all(
        row['status'] == 'voided' or row['kind'] == 'reversal' for row in slips if row['rider_id'] == rider['id']
    )
    assert effective_payroll(slips, rider['id']) is None


def test_e12_unaffected_rider_is_not_paid_twice(client: ApiClient, admin_token: dict[str, str]) -> None:
    """E12 / P0-05：回退方案甲后重算全员，方案乙骑手有效实发仍是 20，不会变成 40。"""
    site = create_site(client, admin_token, name='双发站点')
    rider_a = create_rider(client, admin_token, site_id=site['id'], name='方案甲骑手', hire_date='2026-11-01')
    rider_b = create_rider(client, admin_token, site_id=site['id'], name='方案乙骑手', hire_date='2026-11-01')
    plan_a = create_plan(
        client,
        admin_token,
        name='方案甲',
        short_name='甲',
        items=[
            {
                'subject_code': 'BASE_UNIT_PRICE',
                'name': '基础单价',
                'stage': 'per_order',
                'sort_order': 0,
                'formula_json': _PER_ORDER_20,
            }
        ],
    )
    plan_b = create_plan(
        client,
        admin_token,
        name='方案乙',
        short_name='乙',
        items=[
            {
                'subject_code': 'BASE_UNIT_PRICE',
                'name': '基础单价',
                'stage': 'per_order',
                'sort_order': 0,
                'formula_json': _PER_ORDER_20,
            }
        ],
    )
    period = generate_month(client, admin_token, site_id=site['id'], month='2026-11')
    for rider, order_no in ((rider_a, 'E12-A'), (rider_b, 'E12-B')):
        imported = import_completed_orders(
            client,
            admin_token,
            site_id=site['id'],
            site_code=site['code'],
            job_no=rider['job_no'],
            rows=[order_row(order_no, '2026-11-04')],
        )
        assert imported['success_rows'] == 1
    start, end = month_bounds('2026-11')
    activate_plan(
        client,
        admin_token,
        version_id=plan_a['version_id'],
        rider_id=rider_a['id'],
        start_date=start,
        end_date=end,
    )
    activate_plan(
        client,
        admin_token,
        version_id=plan_b['version_id'],
        rider_id=rider_b['id'],
        start_date=start,
        end_date=end,
    )
    bind_plan(client, admin_token, rider_id=rider_a['id'], version_id=plan_a['version_id'], start_date=start)
    bind_plan(client, admin_token, rider_id=rider_b['id'], version_id=plan_b['version_id'], start_date=start)
    calculate_period(client, admin_token, period['id'])
    lock_period(client, admin_token, period['id'], '回退前锁账')

    expect_ok(
        client.post(
            f'/rider-salary/plan-versions/{plan_a["version_id"]}/rollback',
            headers=admin_token,
            json={'reason': '回退方案甲', 'confirm_text': ''},
        )
    )
    calculate_period(client, admin_token, period['id'])
    payrolls = period_payrolls(client, admin_token, period['id'])
    original = money('20.00')
    untouched = effective_payroll(payrolls, rider_b['id'])
    affected = effective_payroll(payrolls, rider_a['id'])
    assert untouched is not None
    assert untouched['kind'] == 'supplement'
    assert money(untouched['net']) == original
    assert live_net(payrolls, rider_b['id']) == original
    assert live_net(payrolls, rider_b['id']) != money('40.00')
    assert affected is not None
    assert live_net(payrolls, rider_a['id']) == money(affected['net'])
    assert live_net(payrolls, rider_a['id']) != money('40.00')
    lock_period(client, admin_token, period['id'], '重算后锁账')
