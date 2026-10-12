"""一名骑手失败时，其他人的结果留下，作业记为部分成功，并且提交后仍能查到。"""

import runtime

from factories import (
    bind_plan,
    create_rider,
    month_bounds,
    order_row,
    provision_c01_month,
)
from runtime import ApiClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.rider_salary.service import calc_service
from backend.plugin.rider_salary.service.calc_job_service import wait_pending_calc_jobs


def test_one_rider_failure_persists_others_and_job(client: ApiClient, admin_token: dict[str, str]) -> None:
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-08',
        orders=[order_row('PJ-0801', '2026-08-06')],
        hire_date='2026-08-01',
        rider_name='部分成功骑手甲',
        site_name='部分成功站点',
    )
    start, _end = month_bounds('2026-08')
    second = create_rider(
        client,
        admin_token,
        site_id=int(ready['site']['id']),
        name='部分成功骑手乙',
        hire_date='2026-08-01',
    )
    bind_plan(
        client,
        admin_token,
        rider_id=int(second['id']),
        version_id=int(ready['plan']['version_id']),
        start_date=start,
    )
    client.loop.run_until_complete(_fail_one_and_requery(client, admin_token, ready, int(second['id'])))


async def _fail_one_and_requery(
    client: ApiClient,
    headers: dict[str, str],
    ready: dict[str, dict[str, object]],
    fail_rider_id: int,
) -> None:
    active = runtime.ACTIVE
    assert active is not None
    assert active._trans is not None
    assert active._maker is not None
    assert active._engine is not None
    period_id = int(ready['period']['id'])
    keep_rider_id = int(ready['rider']['id'])
    site_id = int(ready['site']['id'])
    original = calc_service.calculate_rider_period
    previous_maker = active._maker._makers['default']

    async def _maybe(db: AsyncSession, **kwargs: object) -> object:
        if kwargs.get('rider_id') == fail_rider_id:
            raise RuntimeError('模拟失败')
        return await original(db, **kwargs)  # type: ignore[arg-type]

    committed = False
    calc_service.calculate_rider_period = _maybe  # type: ignore[assignment]
    try:
        await active._trans.commit()
        active._trans = None
        committed = True
        active._maker._makers['default'] = active._pool_maker
        response = await client.raw.post(
            f'/rider-salary/periods/{period_id}/calculate',
            headers=headers,
            json={},
        )
        body = response.json()
        assert response.status_code == 200 and body['code'] == 200, body
        assert body['data']['queued'] is True
        job_id = int(body['data']['job_id'])
        await wait_pending_calc_jobs()

        detail = await client.raw.get(f'/rider-salary/periods/{period_id}', headers=headers)
        detail_body = detail.json()
        assert detail.status_code == 200 and detail_body['code'] == 200, detail_body
        payrolls = period_payrolls_from(detail_body['data']['payrolls'])
        assert any(row['rider_id'] == keep_rider_id and row['status'] == 'draft' for row in payrolls)
        assert all(row['rider_id'] != fail_rider_id for row in payrolls)

        job_response = await client.raw.get(f'/rider-salary/periods/calc-jobs/{job_id}', headers=headers)
        job_body = job_response.json()
        assert job_response.status_code == 200 and job_body['code'] == 200, job_body
        assert job_body['data']['status'] == 'partial'
        assert job_body['data']['success_count'] == 1
        assert job_body['data']['failed_count'] == 1
        assert any('模拟失败' in item['reason'] for item in job_body['data']['failures'])

        async with active._engine.connect() as conn:
            status = await conn.scalar(text('select status from rs_calc_job where id = :id'), {'id': job_id})
        assert status == 'partial'
    finally:
        calc_service.calculate_rider_period = original
        if committed and active._engine is not None:
            await _delete_provision(
                active._engine,
                site_id=site_id,
                rider_id=keep_rider_id,
                plan_id=int(ready['plan']['plan_id']),
                version_id=int(ready['plan']['version_id']),
                site_code=str(ready['site']['code']),
            )
        if active._maker is not None:
            active._maker._makers['default'] = previous_maker
        if committed and active._conn is not None and active._trans is None:
            active._trans = await active._conn.begin()


def period_payrolls_from(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return list(rows)


async def _delete_provision(
    engine: object,
    *,
    site_id: int,
    rider_id: int,
    plan_id: int,
    version_id: int,
    site_code: str,
) -> None:
    statements = (
        'delete from rs_calc_job where site_id = :site_id',
        """
        delete from rs_payroll_detail
        where payroll_id in (
            select id from rs_payroll
            where period_id in (select id from rs_settle_period where site_id = :site_id)
        )
        """,
        """
        delete from rs_payroll_daily
        where period_id in (select id from rs_settle_period where site_id = :site_id)
           or rider_id = :rider_id
        """,
        """
        delete from rs_payroll
        where period_id in (select id from rs_settle_period where site_id = :site_id)
           or rider_id = :rider_id
        """,
        'delete from rs_order where site_id = :site_id or rider_id = :rider_id',
        'delete from rs_adjustment where site_id = :site_id or rider_id = :rider_id',
        'delete from rs_import_batch where site_id = :site_id',
        'delete from rs_day_flag where site_id = :site_id',
        """
        delete from rs_rider_plan_binding
        where rider_id = :rider_id
           or rider_id in (select id from rs_rider where site_id = :site_id)
        """,
        """
        delete from rs_rider_employ_history
        where rider_id = :rider_id
           or rider_id in (select id from rs_rider where site_id = :site_id)
        """,
        'delete from rs_settle_period where site_id = :site_id',
        'delete from rs_site_manager where site_id = :site_id',
        'delete from rs_rider where site_id = :site_id',
        'delete from rs_plan_item where plan_version_id = :version_id',
        'delete from rs_plan_version where id = :version_id or plan_id = :plan_id',
        'delete from rs_plan where id = :plan_id',
        'delete from rs_site where id = :site_id',
        """
        delete from rs_audit_log
        where description like :code_like or target_label like :code_like
        """,
    )
    params = {
        'site_id': site_id,
        'rider_id': rider_id,
        'plan_id': plan_id,
        'version_id': version_id,
        'code_like': f'%{site_code}%',
    }
    async with engine.begin() as conn:  # type: ignore[attr-defined]
        for statement in statements:
            await conn.execute(text(statement), params)
