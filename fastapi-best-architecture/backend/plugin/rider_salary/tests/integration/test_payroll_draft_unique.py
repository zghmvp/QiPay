"""P0-14：同周期同骑手同类型只有一张草稿。

并发用例把准备数据提交后改走连接池，两笔算薪才能同时进行。
基座默认把一个用例绑在同一条连接上，第二笔会等到第一笔结束。
"""

import asyncio
import uuid

import runtime

from factories import calculate_period, order_row, period_payrolls, provision_c01_month
from runtime import ApiClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.rider_salary.enums import PayrollKind, PayrollStatus
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.service import calc_service
from backend.plugin.rider_salary.service.calc_job_service import wait_pending_calc_jobs
from backend.plugin.rider_salary.service.calc_service import PERIOD_CALCULATING_LOCK_MSG


def test_recalculate_updates_same_draft(client: ApiClient, admin_token: dict[str, str]) -> None:
    """连续算两次仍只有一张草稿，说明上一笔的计算锁已经放开。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-01',
        orders=[order_row(f'P014A-{uuid.uuid4().hex[:8]}', '2026-01-08')],
        hire_date='2026-01-01',
        rider_name='连续算薪骑手',
        site_name='连续算薪站点',
    )
    period_id = ready['period']['id']
    rider_id = ready['rider']['id']
    first = calculate_period(client, admin_token, period_id)
    second = calculate_period(client, admin_token, period_id)
    assert first['calculated'] == 1
    assert second['calculated'] == 1
    drafts = _drafts(period_payrolls(client, admin_token, period_id), rider_id)
    assert len(drafts) == 1
    assert int(drafts[0]['calc_version']) == 2


def test_concurrent_calculate_one_draft_other_busy(client: ApiClient, admin_token: dict[str, str]) -> None:
    """并发两次算同一骑手，只产生一张草稿，另一次返回 409。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-02',
        orders=[order_row(f'P014B-{uuid.uuid4().hex[:8]}', '2026-02-08')],
        hire_date='2026-02-01',
        rider_name='并发算薪骑手',
        site_name='并发算薪站点',
    )
    client.loop.run_until_complete(_race_same_rider(client, admin_token, ready))


def test_partial_unique_index_allows_only_one_live_draft(client: ApiClient) -> None:
    """部分唯一索引拒绝第二张草稿，放行补发草稿、已定稿和已软删草稿。"""
    client.loop.run_until_complete(_assert_partial_unique_index())


def _drafts(payrolls: list[dict[str, object]], rider_id: int) -> list[dict[str, object]]:
    return [
        row for row in payrolls if row['rider_id'] == rider_id and row['status'] == 'draft' and row['kind'] == 'normal'
    ]


async def _race_same_rider(client: ApiClient, headers: dict[str, str], ready: dict[str, dict[str, object]]) -> None:
    active = runtime.ACTIVE
    assert active is not None
    assert active._trans is not None
    assert active._maker is not None
    period_id = int(ready['period']['id'])
    rider_id = int(ready['rider']['id'])
    site_id = int(ready['site']['id'])
    plan_id = int(ready['plan']['plan_id'])
    version_id = int(ready['plan']['version_id'])
    site_code = str(ready['site']['code'])
    previous_maker = active._maker._makers['default']
    original = calc_service._acquire_calc_lock
    state = {'wins': 0}

    async def _hold_first(period: int, rider: int) -> object:
        held = await original(period, rider)
        state['wins'] += 1
        if state['wins'] == 1:
            await asyncio.sleep(1)
        return held

    committed = False
    calc_service._acquire_calc_lock = _hold_first  # type: ignore[assignment]
    try:
        await active._trans.commit()
        active._trans = None
        committed = True
        active._maker._makers['default'] = active._pool_maker
        responses = await asyncio.gather(
            client.raw.post(f'/rider-salary/periods/{period_id}/calculate', headers=headers, json={}),
            client.raw.post(f'/rider-salary/periods/{period_id}/calculate', headers=headers, json={}),
        )
        bodies = [item.json() for item in responses]
        statuses = sorted(item.status_code for item in responses)
        assert statuses == [200, 409], bodies
        conflict = next(body for item, body in zip(responses, bodies, strict=True) if item.status_code == 409)
        assert conflict['code'] == 409
        assert conflict['msg'] == PERIOD_CALCULATING_LOCK_MSG
        success = next(body for item, body in zip(responses, bodies, strict=True) if item.status_code == 200)
        assert success['code'] == 200
        assert success['data']['queued'] is True
        assert success['data']['job_id']
        await wait_pending_calc_jobs()
        detail = await client.raw.get(f'/rider-salary/periods/{period_id}', headers=headers)
        detail_body = detail.json()
        assert detail.status_code == 200 and detail_body['code'] == 200, detail_body
        drafts = _drafts(detail_body['data']['payrolls'], rider_id)
        assert len(drafts) == 1
        assert state['wins'] == 1
    finally:
        calc_service._acquire_calc_lock = original
        if committed and active._engine is not None:
            await _delete_provision(
                active._engine,
                site_id=site_id,
                rider_id=rider_id,
                plan_id=plan_id,
                version_id=version_id,
                site_code=site_code,
            )
        if active._maker is not None:
            active._maker._makers['default'] = previous_maker
        if committed and active._conn is not None and active._trans is None:
            active._trans = await active._conn.begin()


async def _delete_provision(
    engine: object,
    *,
    site_id: int,
    rider_id: int,
    plan_id: int,
    version_id: int,
    site_code: str,
) -> None:
    """删掉已提交的场景数据，避免后面的用例看见它。"""
    statements = (
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
        'delete from rs_calc_job where site_id = :site_id',
        'delete from rs_order where site_id = :site_id or rider_id = :rider_id',
        'delete from rs_adjustment where site_id = :site_id or rider_id = :rider_id',
        'delete from rs_import_batch where site_id = :site_id',
        'delete from rs_day_flag where site_id = :site_id',
        'delete from rs_rider_plan_binding where rider_id = :rider_id',
        'delete from rs_rider_employ_history where rider_id = :rider_id',
        'delete from rs_settle_period where site_id = :site_id',
        'delete from rs_site_manager where site_id = :site_id',
        'delete from rs_rider where id = :rider_id or site_id = :site_id',
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


async def _assert_partial_unique_index() -> None:
    active = runtime.ACTIVE
    assert active is not None
    engine = active._engine
    assert engine is not None
    async with engine.connect() as conn:
        trans = await conn.begin()
        defined = await conn.scalar(text("select indexdef from pg_indexes where indexname = 'uq_rs_payroll_one_draft'"))
        assert defined is not None
        folded = str(defined).lower()
        assert 'unique' in folded
        assert "status = 'draft'" in folded or "status::text = 'draft'" in folded or 'draft' in folded
        assert 'deleted = 0' in folded or 'deleted = 0::bigint' in folded
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode='create_savepoint')
        try:
            period_id = 770014001
            rider_id = 770014002
            first = RiderSalaryPayroll(period_id=period_id, rider_id=rider_id, kind=PayrollKind.normal.value)
            session.add(first)
            await session.flush()
            rejected = False
            try:
                async with session.begin_nested():
                    session.add(
                        RiderSalaryPayroll(period_id=period_id, rider_id=rider_id, kind=PayrollKind.normal.value)
                    )
                    await session.flush()
            except IntegrityError:
                rejected = True
            assert rejected
            session.add(RiderSalaryPayroll(period_id=period_id, rider_id=rider_id, kind=PayrollKind.supplement.value))
            session.add(
                RiderSalaryPayroll(
                    period_id=period_id,
                    rider_id=rider_id,
                    kind=PayrollKind.normal.value,
                    status=PayrollStatus.finalized.value,
                )
            )
            await session.flush()
            first.deleted = first.id
            await session.flush()
            session.add(RiderSalaryPayroll(period_id=period_id, rider_id=rider_id, kind=PayrollKind.normal.value))
            await session.flush()
        finally:
            await session.close()
            await trans.rollback()
