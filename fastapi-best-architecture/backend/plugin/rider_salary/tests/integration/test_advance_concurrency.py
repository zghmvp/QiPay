"""P0-16：在途预支唯一、审核抢占、两周期只抵扣一次。

并发用例把准备数据提交后改走连接池，两笔请求才能同时进行。
基座默认把一个用例绑在同一条连接上，第二笔会等到第一笔结束。
"""

import asyncio
import uuid

from decimal import Decimal

import runtime

from factories import (
    expect_ok,
    generate_month,
    import_completed_orders,
    money,
    open_rider_account,
    order_row,
    provision_c01_month,
    use_shared_db_session,
)
from runtime import ApiClient, RoleAccount
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.rider_salary.crud.advance import advance_dao
from backend.plugin.rider_salary.enums import AdvanceStatus
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.service.advance_service import (
    IN_FLIGHT_CONFLICT_MSG,
    STATUS_CHANGED_MSG,
    advance_service,
)
from backend.plugin.rider_salary.service.payroll_service import payroll_service

_HOLD_SECONDS = 0.8


def test_partial_unique_index_one_in_flight(client: ApiClient) -> None:
    """部分唯一索引拒绝第二笔在途预支，放行已发放和已软删。"""
    client.loop.run_until_complete(_assert_partial_unique_index())


def test_concurrent_submit_one_in_flight(client: ApiClient, admin_token: dict[str, str]) -> None:
    """并发两次申请，一笔成功，另一笔 409，库里只有一笔在途预支。"""
    with use_shared_db_session():
        ready = provision_c01_month(
            client,
            admin_token,
            month='2026-03',
            orders=[order_row(f'P016S-{uuid.uuid4().hex[:8]}', '2026-03-08')],
            hire_date='2026-03-01',
            rider_name='并发申请骑手',
            site_name='并发申请站点',
        )
        rider_headers = open_rider_account(
            client,
            admin_token,
            rider_id=int(ready['rider']['id']),
            job_no=str(ready['rider']['job_no']),
        )
    client.loop.run_until_complete(_race_submit(client, admin_token, rider_headers, ready))


def test_concurrent_approve_one_succeeds(
    client: ApiClient,
    admin_token: dict[str, str],
    role_accounts: dict[str, RoleAccount],
) -> None:
    """两名负责人同时审核同一笔待审核预支，只有一人成功。"""
    with use_shared_db_session():
        ready = provision_c01_month(
            client,
            admin_token,
            month='2026-04',
            orders=[order_row(f'P016A-{uuid.uuid4().hex[:8]}', '2026-04-08')],
            hire_date='2026-04-01',
            rider_name='并发审核骑手',
            site_name='并发审核站点',
        )
        rider_headers = open_rider_account(
            client,
            admin_token,
            rider_id=int(ready['rider']['id']),
            job_no=str(ready['rider']['job_no']),
        )
        created = expect_ok(
            client.post(
                '/rider-salary/me/advances',
                headers=rider_headers,
                json={'amount': '10.00', 'reason': '并发审核'},
            )
        )
        expect_ok(
            client.put(
                f'/rider-salary/sites/{ready["site"]["id"]}/managers',
                headers=admin_token,
                json=[
                    {'user_id': role_accounts['site_owner'].user_id, 'role': 'owner'},
                    {'user_id': role_accounts['site_deputy'].user_id, 'role': 'deputy'},
                ],
            )
        )
    client.loop.run_until_complete(
        _race_approve(
            client,
            ready,
            int(created['id']),
            role_accounts['site_owner'].headers,
            role_accounts['site_deputy'].headers,
        )
    )


def test_concurrent_calc_deducts_advance_once(client: ApiClient, admin_token: dict[str, str]) -> None:
    """两个周期同时算薪，同一笔已发放预支只被抵扣一次。"""
    token = uuid.uuid4().hex[:8]
    with use_shared_db_session():
        ready = provision_c01_month(
            client,
            admin_token,
            month='2026-05',
            orders=[
                order_row(f'P016C-{token}-1', '2026-05-08'),
                order_row(f'P016C-{token}-2', '2026-05-09'),
            ],
            hire_date='2026-05-01',
            rider_name='并发抵扣骑手',
            site_name='并发抵扣站点',
        )
        later = generate_month(client, admin_token, site_id=int(ready['site']['id']), month='2026-06')
        imported = import_completed_orders(
            client,
            admin_token,
            site_id=int(ready['site']['id']),
            site_code=str(ready['site']['code']),
            job_no=str(ready['rider']['job_no']),
            rows=[
                order_row(f'P016C-{token}-3', '2026-06-08'),
                order_row(f'P016C-{token}-4', '2026-06-09'),
            ],
        )
        assert imported['success_rows'] == 2
        rider_headers = open_rider_account(
            client,
            admin_token,
            rider_id=int(ready['rider']['id']),
            job_no=str(ready['rider']['job_no']),
        )
        created = expect_ok(
            client.post(
                '/rider-salary/me/advances',
                headers=rider_headers,
                json={'amount': '10.00', 'reason': '两周期抵扣'},
            )
        )
        advance_id = int(created['id'])
        expect_ok(
            client.post(
                f'/rider-salary/advances/{advance_id}/approve',
                headers=admin_token,
                json={'remark': '同意'},
            )
        )
        expect_ok(
            client.post(
                f'/rider-salary/advances/{advance_id}/mark-paid',
                headers=admin_token,
                json={'remark': '已发放'},
            )
        )
    client.loop.run_until_complete(
        _race_calc(
            client,
            admin_token,
            ready,
            int(later['id']),
            advance_id,
        )
    )


async def _assert_partial_unique_index() -> None:
    active = runtime.ACTIVE
    assert active is not None
    engine = active._engine
    assert engine is not None
    async with engine.connect() as conn:
        trans = await conn.begin()
        defined = await conn.scalar(
            text("select indexdef from pg_indexes where indexname = 'uq_rs_advance_one_in_flight'")
        )
        assert defined is not None
        folded = str(defined).lower()
        assert 'unique' in folded
        assert 'pending' in folded and 'to_pay' in folded
        assert 'deleted' in folded
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode='create_savepoint')
        rider_id = 770016101
        site_id = 770016100
        try:
            first = _advance(rider_id, site_id, AdvanceStatus.pending.value)
            session.add(first)
            await session.flush()
            assert await _rejected_extra(session, rider_id, site_id, AdvanceStatus.pending.value)
            first.status = AdvanceStatus.paid.value
            await session.flush()
            second = _advance(rider_id, site_id, AdvanceStatus.pending.value)
            session.add(second)
            await session.flush()
            assert await _rejected_extra(session, rider_id, site_id, AdvanceStatus.to_pay.value)
            second.deleted = second.id
            await session.flush()
            session.add(_advance(rider_id, site_id, AdvanceStatus.pending.value))
            await session.flush()
        finally:
            await session.close()
            await trans.rollback()


def _advance(rider_id: int, site_id: int, status: str) -> RiderSalaryAdvance:
    return RiderSalaryAdvance(
        rider_id=rider_id,
        site_id=site_id,
        amount=Decimal('10.00'),
        reason='在途索引',
        status=status,
    )


async def _rejected_extra(session: AsyncSession, rider_id: int, site_id: int, status: str) -> bool:
    rejected = False
    try:
        async with session.begin_nested():
            session.add(_advance(rider_id, site_id, status))
            await session.flush()
    except IntegrityError:
        rejected = True
    return rejected


async def _race_submit(
    client: ApiClient,
    admin_token: dict[str, str],
    rider_headers: dict[str, str],
    ready: dict[str, dict[str, object]],
) -> None:
    pool = _PoolSwitch()
    original = advance_dao.create
    state = {'calls': 0}

    async def _slow_first(db: object, obj: object, *, rider_id: int, site_id: int) -> object:
        state['calls'] += 1
        if state['calls'] == 1:
            await asyncio.sleep(_HOLD_SECONDS)
        return await original(db, obj, rider_id=rider_id, site_id=site_id)

    advance_dao.create = _slow_first  # type: ignore[method-assign]
    try:
        await pool.open()
        responses = await asyncio.gather(
            client.raw.post(
                '/rider-salary/me/advances',
                headers=rider_headers,
                json={'amount': '10.00', 'reason': '并发甲'},
            ),
            client.raw.post(
                '/rider-salary/me/advances',
                headers=rider_headers,
                json={'amount': '10.00', 'reason': '并发乙'},
            ),
        )
        bodies = [item.json() for item in responses]
        statuses = sorted(item.status_code for item in responses)
        assert statuses == [200, 409], bodies
        conflict = next(body for item, body in zip(responses, bodies, strict=True) if item.status_code == 409)
        assert conflict['code'] == 409
        assert conflict['msg'] == IN_FLIGHT_CONFLICT_MSG
        listed = await client.raw.get(
            '/rider-salary/advances',
            headers=admin_token,
            params={'rider_id': int(ready['rider']['id']), 'page': 1, 'size': 20},
        )
        listed_body = listed.json()
        assert listed.status_code == 200 and listed_body['code'] == 200, listed_body
        in_flight = [
            row for row in listed_body['data']['items'] if row['status'] in {AdvanceStatus.pending.value, 'to_pay'}
        ]
        assert len(in_flight) == 1
        assert state['calls'] == 2
    finally:
        advance_dao.create = original  # type: ignore[method-assign]
        await pool.close(ready)


async def _race_approve(
    client: ApiClient,
    ready: dict[str, dict[str, object]],
    advance_id: int,
    owner_headers: dict[str, str],
    deputy_headers: dict[str, str],
) -> None:
    pool = _PoolSwitch()
    original = advance_service.transition_if_status
    state = {'calls': 0}

    async def _hold_first(db: object, advance: object, target: str, operator: object, reason: str | None) -> None:
        state['calls'] += 1
        if state['calls'] == 1:
            await asyncio.sleep(_HOLD_SECONDS)
        await original(db, advance, target, operator, reason)

    advance_service.transition_if_status = _hold_first  # type: ignore[method-assign]
    try:
        await pool.open()
        responses = await asyncio.gather(
            client.raw.post(
                f'/rider-salary/advances/{advance_id}/approve',
                headers=owner_headers,
                json={'remark': '负责人通过'},
            ),
            client.raw.post(
                f'/rider-salary/advances/{advance_id}/approve',
                headers=deputy_headers,
                json={'remark': '副负责人通过'},
            ),
        )
        bodies = [item.json() for item in responses]
        statuses = sorted(item.status_code for item in responses)
        assert statuses == [200, 409], bodies
        conflict = next(body for item, body in zip(responses, bodies, strict=True) if item.status_code == 409)
        assert conflict['code'] == 409
        assert conflict['msg'] == STATUS_CHANGED_MSG
        detail = await client.raw.get(f'/rider-salary/advances/{advance_id}', headers=owner_headers)
        detail_body = detail.json()
        assert detail.status_code == 200 and detail_body['code'] == 200, detail_body
        assert detail_body['data']['status'] == AdvanceStatus.to_pay.value
        assert state['calls'] == 2
    finally:
        advance_service.transition_if_status = original  # type: ignore[method-assign]
        await pool.close(ready)


async def _race_calc(
    client: ApiClient,
    admin_token: dict[str, str],
    ready: dict[str, dict[str, object]],
    second_period_id: int,
    advance_id: int,
) -> None:
    pool = _PoolSwitch()
    original = payroll_service.load_paid_advances
    state = {'calls': 0}
    first_period_id = int(ready['period']['id'])
    rider_id = int(ready['rider']['id'])

    async def _hold_first(db: object, rider: int, *, for_update: bool = False) -> list[object]:
        rows = await original(db, rider, for_update=for_update)
        state['calls'] += 1
        if state['calls'] == 1:
            await asyncio.sleep(_HOLD_SECONDS)
        return rows

    payroll_service.load_paid_advances = _hold_first  # type: ignore[method-assign]
    try:
        await pool.open()
        responses = await asyncio.gather(
            client.raw.post(f'/rider-salary/periods/{first_period_id}/calculate', headers=admin_token, json={}),
            client.raw.post(f'/rider-salary/periods/{second_period_id}/calculate', headers=admin_token, json={}),
        )
        bodies = [item.json() for item in responses]
        statuses = sorted(item.status_code for item in responses)
        assert statuses == [200, 200], bodies
        assert all(body['data']['queued'] is True and body['data']['job_id'] for body in bodies)
        from backend.plugin.rider_salary.service.calc_job_service import wait_pending_calc_jobs

        await wait_pending_calc_jobs()
        deducted = Decimal('0.00')
        for period_id in (first_period_id, second_period_id):
            detail = await client.raw.get(f'/rider-salary/periods/{period_id}', headers=admin_token)
            detail_body = detail.json()
            assert detail.status_code == 200 and detail_body['code'] == 200, detail_body
            for row in detail_body['data']['payrolls']:
                if row['rider_id'] != rider_id or row['kind'] == 'reversal' or row['status'] == 'voided':
                    continue
                deducted += money(row['advance_deduction'])
        assert money(deducted) == money('10.00')
        advance = await client.raw.get(f'/rider-salary/advances/{advance_id}', headers=admin_token)
        advance_body = advance.json()
        assert advance.status_code == 200 and advance_body['code'] == 200, advance_body
        assert money(advance_body['data']['deducted_amount']) == money('10.00')
        assert money(advance_body['data']['remaining_amount']) == money('0.00')
        assert state['calls'] == 2
    finally:
        payroll_service.load_paid_advances = original  # type: ignore[method-assign]
        await pool.close(ready)


class _PoolSwitch:
    """把当前用例从单连接切到连接池，结束时删掉已提交的数据并恢复事务。"""

    def __init__(self) -> None:
        self.active = runtime.ACTIVE
        self.previous: object = None
        self.committed = False

    async def open(self) -> None:
        active = self.active
        assert active is not None
        assert active._trans is not None
        assert active._maker is not None
        self.previous = active._maker._makers['default']
        await active._trans.commit()
        active._trans = None
        self.committed = True
        active._maker._makers['default'] = active._pool_maker

    async def close(self, ready: dict[str, dict[str, object]]) -> None:
        active = self.active
        assert active is not None
        if self.committed and active._engine is not None:
            await _delete_provision(
                active._engine,
                site_id=int(ready['site']['id']),
                rider_id=int(ready['rider']['id']),
                plan_id=int(ready['plan']['plan_id']),
                version_id=int(ready['plan']['version_id']),
                site_code=str(ready['site']['code']),
            )
        if active._maker is not None and self.previous is not None:
            active._maker._makers['default'] = self.previous
        if self.committed and active._conn is not None and active._trans is None:
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
        delete from rs_audit_log
        where (target_type = 'advance' and target_id in (
            select id::text from rs_advance where site_id = :site_id or rider_id = :rider_id
        ))
        or description like :code_like
        or target_label like :code_like
        """,
        'delete from rs_calc_job where site_id = :site_id',
        'delete from rs_advance where site_id = :site_id or rider_id = :rider_id',
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
        'delete from rs_rider_plan_binding where rider_id = :rider_id',
        'delete from rs_rider_employ_history where rider_id = :rider_id',
        'delete from rs_settle_period where site_id = :site_id',
        'delete from rs_site_manager where site_id = :site_id',
        'delete from rs_rider where id = :rider_id or site_id = :site_id',
        'delete from rs_plan_item where plan_version_id = :version_id',
        'delete from rs_plan_version where id = :version_id or plan_id = :plan_id',
        'delete from rs_plan where id = :plan_id',
        'delete from rs_site where id = :site_id',
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
