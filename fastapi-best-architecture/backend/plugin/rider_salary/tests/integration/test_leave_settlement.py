"""P6-01：月中离职可单独结算并标记发薪；离职后可补录离职日及之前的奖惩。

采用 Q-05 推荐：需要独立的离职结算周期。H5 只读宽限期属于 P6-02，这里不做。
骑手级周期必须整段覆盖碰到的站点级周期，因此月结站点的周期结束日是月末，不是离职日。
"""

import uuid

from typing import Any

from factories import (
    activate_plan,
    bind_plan,
    calculate_period,
    create_c01_plan,
    create_rider,
    create_site,
    expect_error,
    expect_ok,
    generate_month,
    import_completed_orders,
    money,
    month_bounds,
    order_row,
    provision_c01_month,
    subject_id,
)
from runtime import ApiClient


def _leave(client: ApiClient, headers: dict[str, str], rider_id: int, day: str) -> None:
    expect_ok(
        client.put(
            f'/rider-salary/riders/{rider_id}/leave',
            headers=headers,
            json={'leave_date': day, 'reason': '个人原因'},
        )
    )


def _settlement(client: ApiClient, headers: dict[str, str], rider_id: int) -> Any:
    return client.post(f'/rider-salary/riders/{rider_id}/leave-settlement', headers=headers)


def _payrolls(client: ApiClient, headers: dict[str, str], *, period_id: int, rider_id: int) -> list[dict]:
    return expect_ok(
        client.get(
            '/rider-salary/payrolls',
            headers=headers,
            params={'period_id': period_id, 'rider_id': rider_id, 'page': 1, 'size': 20},
        )
    )['items']


def test_mid_month_leave_can_settle_and_record_penalty_before_leave(
    client: ApiClient,
    admin_token: dict[str, str],
) -> None:
    """10 月 15 日离职：骑手级周期盖住整月，可算薪、锁账、标记发薪；离职日奖惩可补，次日不行。"""
    site = create_site(client, admin_token, name='月中离职结算站点')
    leaver = create_rider(client, admin_token, site_id=site['id'], name='月中离职骑手', hire_date='2026-10-01')
    coworker = create_rider(client, admin_token, site_id=site['id'], name='在职同事', hire_date='2026-10-01')
    plan = create_c01_plan(client, admin_token)
    start, end = month_bounds('2026-10')
    activate_plan(
        client,
        admin_token,
        version_id=plan['version_id'],
        rider_id=leaver['id'],
        start_date=start,
        end_date=end,
    )
    bind_plan(client, admin_token, rider_id=leaver['id'], version_id=plan['version_id'], start_date=start)
    bind_plan(client, admin_token, rider_id=coworker['id'], version_id=plan['version_id'], start_date=start)
    for rider, day in ((leaver, '2026-10-08'), (coworker, '2026-10-09')):
        imported = import_completed_orders(
            client,
            admin_token,
            site_id=site['id'],
            site_code=site['code'],
            job_no=rider['job_no'],
            rows=[order_row(f'LV{uuid.uuid4().hex[:8]}', day)],
        )
        assert imported['success_rows'] == 1
    site_period = generate_month(client, admin_token, site_id=site['id'], month='2026-10')
    _leave(client, admin_token, leaver['id'], '2026-10-15')

    penalty = subject_id(client, admin_token, 'QUIT_PENALTY')
    recorded = expect_ok(
        client.post(
            '/rider-salary/adjustments',
            headers=admin_token,
            json={
                'rider_id': leaver['id'],
                'biz_date': '2026-10-15',
                'subject_id': penalty,
                'amount': '100.00',
                'remark': '急辞违约金',
            },
        )
    )
    assert recorded['biz_date'] == '2026-10-15'
    late = client.post(
        '/rider-salary/adjustments',
        headers=admin_token,
        json={
            'rider_id': leaver['id'],
            'biz_date': '2026-10-16',
            'subject_id': penalty,
            'amount': '100.00',
            'remark': '离职后的日期',
        },
    )
    assert '晚于离职日' in expect_error(late, 400)

    settled = expect_ok(_settlement(client, admin_token, leaver['id']))
    assert settled['created'] is True
    assert settled['rider_id'] == leaver['id']
    assert settled['start_date'] == '2026-10-01'
    assert settled['end_date'] == '2026-10-31'
    assert '计薪截至2026-10-15' in settled['hint']
    again = expect_ok(_settlement(client, admin_token, leaver['id']))
    assert again['created'] is False
    assert again['period_id'] == settled['period_id']

    calculated = calculate_period(client, admin_token, settled['period_id'])
    assert calculated['queued'] is False
    assert calculated['calculated'] == 1
    own = _payrolls(client, admin_token, period_id=settled['period_id'], rider_id=leaver['id'])
    assert len(own) == 1
    assert money(own[0]['per_order_total']) == money('5.00')
    assert money(own[0]['penalty_total']) == money('-100.00')

    site_calc = calculate_period(client, admin_token, site_period['id'])
    assert site_calc['calculated'] == 1
    assert _payrolls(client, admin_token, period_id=site_period['id'], rider_id=leaver['id']) == []
    assert len(_payrolls(client, admin_token, period_id=site_period['id'], rider_id=coworker['id'])) == 1

    expect_ok(
        client.post(
            f'/rider-salary/periods/{settled["period_id"]}/lock',
            headers=admin_token,
            json={'reason': '离职结算锁账', 'expected_status': 'open'},
        )
    )
    duplicate = client.post(
        f'/rider-salary/periods/{settled["period_id"]}/lock',
        headers=admin_token,
        json={'reason': '离职结算锁账', 'expected_status': 'open'},
    )
    assert expect_error(duplicate, 409)
    locked = expect_ok(client.get(f'/rider-salary/periods/{settled["period_id"]}', headers=admin_token))
    assert locked['status'] == 'locked'
    blocked = client.post(
        '/rider-salary/adjustments',
        headers=admin_token,
        json={
            'rider_id': leaver['id'],
            'biz_date': '2026-10-15',
            'subject_id': penalty,
            'amount': '20.00',
            'remark': '锁账后不能再补',
        },
    )
    assert expect_error(blocked, 403)

    expect_ok(
        client.post(
            f'/rider-salary/periods/{settled["period_id"]}/mark-paid',
            headers=admin_token,
            json={'reason': '离职结算发薪', 'expected_status': 'locked'},
        )
    )
    paid = expect_ok(client.get(f'/rider-salary/periods/{settled["period_id"]}', headers=admin_token))
    assert paid['status'] == 'paid'


def test_leave_settlement_does_not_block_later_site_generate(
    client: ApiClient,
    admin_token: dict[str, str],
) -> None:
    """先生成离职结算，再生成当月站点级周期，整段覆盖所以不会被拒绝。"""
    site = create_site(client, admin_token, name='先结算后生成站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='先结算骑手', hire_date='2026-10-01')
    _leave(client, admin_token, rider['id'], '2026-10-15')
    settled = expect_ok(_settlement(client, admin_token, rider['id']))
    assert (settled['start_date'], settled['end_date']) == ('2026-10-01', '2026-10-31')

    site_period = generate_month(client, admin_token, site_id=site['id'], month='2026-10')
    assert (site_period['start_date'], site_period['end_date']) == ('2026-10-01', '2026-10-31')


def test_site_payroll_blocks_leave_settlement(client: ApiClient, admin_token: dict[str, str]) -> None:
    """站点级周期里已有该骑手薪资单时，不能再盖上一层离职结算周期。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-10',
        orders=[order_row(f'LVB{uuid.uuid4().hex[:8]}', '2026-10-08')],
        hire_date='2026-10-01',
        rider_name='已算薪后离职',
        site_name='已算薪离职站点',
    )
    calculate_period(client, admin_token, ready['period']['id'])
    _leave(client, admin_token, ready['rider']['id'], '2026-10-15')
    message = expect_error(_settlement(client, admin_token, ready['rider']['id']), 400)
    assert '薪资单' in message


def test_on_job_rider_cannot_create_leave_settlement(client: ApiClient, admin_token: dict[str, str]) -> None:
    """还没离职不能生成离职结算周期。"""
    site = create_site(client, admin_token, name='在职不能结算站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='仍在职', hire_date='2026-10-01')
    message = expect_error(_settlement(client, admin_token, rider['id']), 400)
    assert '请先办理离职' in message
