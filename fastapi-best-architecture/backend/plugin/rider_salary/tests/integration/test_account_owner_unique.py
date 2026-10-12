"""P3-11：同一登录账号只绑一名骑手，每个站点至多一名负责人。"""

from datetime import date

import runtime

from factories import bind_site_manager, create_rider, create_site, expect_error, expect_ok
from runtime import ApiClient, RoleAccount
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.site_manager import RiderSalarySiteManager
from backend.plugin.rider_salary.utils.db_errors import (
    RIDER_USER_BOUND_MSG,
    SITE_OWNER_EXISTS_MSG,
    client_error_from_integrity,
)

_SITE_ID = 770311001
_USER_ID = 770311002


def test_rebinding_same_user_returns_409(
    client: ApiClient,
    admin_token: dict[str, str],
    role_accounts: dict[str, RoleAccount],
) -> None:
    """工号撞上已绑定骑手的登录名时，开通账号返回 409。"""
    site = create_site(client, admin_token, name='重复账号站点')
    rider = create_rider(
        client,
        admin_token,
        site_id=site['id'],
        job_no=role_accounts['rider'].username,
        name='重复绑定',
    )
    opened = client.post(
        f'/rider-salary/riders/{rider["id"]}/open-account',
        headers=admin_token,
        json={'password': 'Rider@123456', 'reason': '重复绑定已有账号'},
    )
    assert expect_error(opened, 409) == RIDER_USER_BOUND_MSG
    detail = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}', headers=admin_token))
    assert detail['user_id'] is None


def test_open_account_still_binds_a_fresh_user(client: ApiClient, admin_token: dict[str, str]) -> None:
    """未占用的工号仍能开通，并写入不重复的 user_id。"""
    site = create_site(client, admin_token, name='正常开户站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='正常开户')
    expect_ok(
        client.post(
            f'/rider-salary/riders/{rider["id"]}/open-account',
            headers=admin_token,
            json={'password': 'Rider@123456', 'reason': '首次开通'},
        )
    )
    detail = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}', headers=admin_token))
    assert detail['user_id'] is not None


def test_second_owner_returns_409(
    client: ApiClient,
    admin_token: dict[str, str],
    role_accounts: dict[str, RoleAccount],
) -> None:
    """同一次提交两名负责人返回 409；一名负责人和一名副负责人可以保存。"""
    site = create_site(client, admin_token, name='双负责人站点')
    owner_id = role_accounts['site_owner'].user_id
    deputy_id = role_accounts['site_deputy'].user_id
    duplicated = client.put(
        f'/rider-salary/sites/{site["id"]}/managers',
        headers=admin_token,
        json=[
            {'user_id': owner_id, 'role': 'owner'},
            {'user_id': deputy_id, 'role': 'owner'},
        ],
    )
    assert expect_error(duplicated, 409) == SITE_OWNER_EXISTS_MSG

    expect_ok(
        client.put(
            f'/rider-salary/sites/{site["id"]}/managers',
            headers=admin_token,
            json=[
                {'user_id': owner_id, 'role': 'owner'},
                {'user_id': deputy_id, 'role': 'deputy'},
            ],
        )
    )
    managers = expect_ok(client.get(f'/rider-salary/sites/{site["id"]}/managers', headers=admin_token))
    assert {item['role'] for item in managers} == {'owner', 'deputy'}
    bind_site_manager(client, admin_token, site_id=site['id'], user_id=deputy_id, role='owner')
    replaced = expect_ok(client.get(f'/rider-salary/sites/{site["id"]}/managers', headers=admin_token))
    assert [item['user_id'] for item in replaced] == [deputy_id]


def test_partial_unique_indexes_reject_live_duplicates(client: ApiClient) -> None:
    """部分唯一索引拒绝重复绑定和第二个负责人，放行空账号、软删除和副负责人。"""
    client.loop.run_until_complete(_assert_partial_unique_indexes())


async def _assert_partial_unique_indexes() -> None:
    active = runtime.ACTIVE
    assert active is not None
    engine = active._engine
    assert engine is not None
    async with engine.connect() as conn:
        trans = await conn.begin()
        for name, needles in (
            ('uq_rs_rider_one_user', ('user_id', 'not null')),
            ('uq_rs_site_manager_one_owner', ('site_id', 'owner')),
        ):
            defined = await conn.scalar(text('select indexdef from pg_indexes where indexname = :name'), {'name': name})
            assert defined is not None, name
            folded = str(defined).lower()
            assert 'unique' in folded
            assert 'deleted = 0' in folded or 'deleted = 0::bigint' in folded
            assert all(needle in folded for needle in needles), folded
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode='create_savepoint')
        try:
            first = RiderSalaryRider(
                job_no='P311A',
                name='已绑定',
                site_id=_SITE_ID,
                hire_date=date(2026, 1, 1),
                user_id=_USER_ID,
            )
            session.add(first)
            session.add(
                RiderSalaryRider(
                    job_no='P311B',
                    name='未开户',
                    site_id=_SITE_ID,
                    hire_date=date(2026, 1, 1),
                )
            )
            await session.flush()
            rejected = False
            try:
                async with session.begin_nested():
                    session.add(
                        RiderSalaryRider(
                            job_no='P311C',
                            name='重复绑定',
                            site_id=_SITE_ID,
                            hire_date=date(2026, 1, 1),
                            user_id=_USER_ID,
                        )
                    )
                    await session.flush()
            except IntegrityError as exc:
                rejected = True
                conflict = client_error_from_integrity(exc)
                assert conflict.code == 409
                assert conflict.msg == RIDER_USER_BOUND_MSG
            assert rejected
            first.deleted = first.id
            await session.flush()
            session.add(
                RiderSalaryRider(
                    job_no='P311D',
                    name='复用账号',
                    site_id=_SITE_ID,
                    hire_date=date(2026, 1, 1),
                    user_id=_USER_ID,
                )
            )
            await session.flush()

            session.add(RiderSalarySiteManager(site_id=_SITE_ID, user_id=88001, role='owner'))
            session.add(RiderSalarySiteManager(site_id=_SITE_ID, user_id=88002, role='deputy'))
            await session.flush()
            owner_rejected = False
            try:
                async with session.begin_nested():
                    session.add(RiderSalarySiteManager(site_id=_SITE_ID, user_id=88003, role='owner'))
                    await session.flush()
            except IntegrityError as exc:
                owner_rejected = True
                conflict = client_error_from_integrity(exc)
                assert conflict.code == 409
                assert conflict.msg == SITE_OWNER_EXISTS_MSG
            assert owner_rejected
            session.add(RiderSalarySiteManager(site_id=_SITE_ID + 1, user_id=88003, role='owner'))
            await session.flush()
        finally:
            await session.close()
            await trans.rollback()
