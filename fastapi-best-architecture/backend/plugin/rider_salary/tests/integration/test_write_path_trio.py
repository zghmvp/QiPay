"""P0-20：创建骑手补锁账，算薪不再回写奖惩带符号金额。"""

from typing import Any

import runtime

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
    lock_period,
    money,
    month_bounds,
    order_row,
    subject_id,
)
from runtime import ApiClient
from sqlalchemy import text

_LOCK_MSG = '该日期所属结算周期已锁账'


def _execute(statement: str, params: dict[str, Any]) -> None:
    """在当前用例的外层事务里执行写语句。"""
    active = runtime.ACTIVE
    assert active is not None and active._conn is not None and active.client is not None

    async def _run() -> None:
        await active._conn.execute(text(statement), params)

    active.client.loop.run_until_complete(_run())


def _rows(statement: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """在当前用例的外层事务里查库，能看见尚未提交的接口写入。"""
    active = runtime.ACTIVE
    assert active is not None and active._conn is not None and active.client is not None

    async def _run() -> list[dict[str, Any]]:
        result = await active._conn.execute(text(statement), params)
        return [dict(row) for row in result.mappings().all()]

    return active.client.loop.run_until_complete(_run())


def _adjustment(client: ApiClient, headers: dict[str, str], adjustment_id: int) -> dict[str, Any]:
    return expect_ok(client.get(f'/rider-salary/adjustments/{adjustment_id}', headers=headers))


def _payroll(client: ApiClient, headers: dict[str, str], period_id: int, rider_id: int) -> dict[str, Any]:
    items = expect_ok(
        client.get(
            '/rider-salary/payrolls',
            headers=headers,
            params={'period_id': period_id, 'rider_id': rider_id, 'page': 1, 'size': 20},
        )
    )['items']
    assert len(items) == 1
    return items[0]


def test_hire_date_in_locked_period_rejects_create(client: ApiClient, admin_token: dict[str, str]) -> None:
    """入职日落在已锁账周期时创建骑手返回 403，未锁月份仍可创建。"""
    site = create_site(client, admin_token, name='入职锁账站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='已在职骑手', hire_date='2026-08-01')
    plan = create_c01_plan(client, admin_token)
    start, end = month_bounds('2026-09')
    period = generate_month(client, admin_token, site_id=site['id'], month='2026-09')
    import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[order_row('HIRE-0901', '2026-09-10')],
    )
    activate_plan(
        client,
        admin_token,
        version_id=plan['version_id'],
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    bind_plan(client, admin_token, rider_id=rider['id'], version_id=plan['version_id'], start_date='2026-08-01')
    calculate_period(client, admin_token, period['id'])
    lock_period(client, admin_token, period['id'], '入职日锁账')

    blocked = client.post(
        '/rider-salary/riders',
        headers=admin_token,
        json={
            'job_no': 'HIRELOCKED1',
            'name': '不该入职',
            'site_id': site['id'],
            'employ_type': 'part_time',
            'hire_date': '2026-09-15',
            'status': 'on_job',
        },
    )
    assert _LOCK_MSG in expect_error(blocked, 403)
    missing = expect_ok(
        client.get(
            '/rider-salary/riders',
            headers=admin_token,
            params={'site_id': site['id'], 'keyword': 'HIRELOCKED1', 'page': 1, 'size': 20},
        )
    )
    assert all(item['job_no'] != 'HIRELOCKED1' for item in missing['items'])

    created = create_rider(
        client,
        admin_token,
        site_id=site['id'],
        job_no='HIREOPEN01',
        name='十月入职',
        hire_date='2026-10-01',
    )
    assert created['hire_date'] == '2026-10-01'
    histories = expect_ok(client.get(f'/rider-salary/riders/{created["id"]}/employ-history', headers=admin_token))
    assert any(item['start_date'] == '2026-10-01' and item['end_date'] is None for item in histories)


def test_calc_derives_signed_amount_without_writing_back(client: ApiClient, admin_token: dict[str, str]) -> None:
    """奖惩带符号金额为空时，算薪用科目方向在内存推导，不回写 rs_adjustment。"""
    site = create_site(client, admin_token, name='奖惩不回写站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='奖惩骑手', hire_date='2026-09-01')
    plan = create_c01_plan(client, admin_token)
    start, end = month_bounds('2026-09')
    period = generate_month(client, admin_token, site_id=site['id'], month='2026-09')
    import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[order_row('ADJ-0901', '2026-09-10')],
    )
    activate_plan(
        client,
        admin_token,
        version_id=plan['version_id'],
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    bind_plan(client, admin_token, rider_id=rider['id'], version_id=plan['version_id'], start_date='2026-09-01')
    bonus = expect_ok(
        client.post(
            '/rider-salary/adjustments',
            headers=admin_token,
            json={
                'rider_id': rider['id'],
                'biz_date': '2026-09-10',
                'subject_id': subject_id(client, admin_token, 'BONUS_GOOD_REVIEW'),
                'amount': '80.00',
                'remark': '好评奖空符号回填前',
            },
        )
    )
    penalty = expect_ok(
        client.post(
            '/rider-salary/adjustments',
            headers=admin_token,
            json={
                'rider_id': rider['id'],
                'biz_date': '2026-09-10',
                'subject_id': subject_id(client, admin_token, 'COMPLAINT'),
                'amount': '30.00',
                'remark': '客诉空符号回填前',
            },
        )
    )
    ids = [int(bonus['id']), int(penalty['id'])]
    for adjustment_id in ids:
        _execute('update rs_adjustment set signed_amount = null where id = :id', {'id': adjustment_id})
        assert _adjustment(client, admin_token, adjustment_id)['signed_amount'] is None

    calculated = calculate_period(client, admin_token, period['id'])
    assert calculated['calculated'] == 1, calculated

    stored = [
        _rows('select signed_amount from rs_adjustment where id = :id', {'id': adjustment_id})[0]
        for adjustment_id in ids
    ]
    assert [row['signed_amount'] for row in stored] == [None, None]
    payroll = _payroll(client, admin_token, period['id'], rider['id'])
    assert money(payroll['bonus_total']) == money('80.00')
    assert money(payroll['penalty_total']) == money('-30.00')
    for adjustment_id in ids:
        assert _adjustment(client, admin_token, adjustment_id)['signed_amount'] is None
