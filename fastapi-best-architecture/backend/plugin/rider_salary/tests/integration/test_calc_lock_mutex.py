"""P0-13：算薪与锁账互斥，后台失败留在周期详情里。

基座把一个用例的请求绑在同一条数据库连接上，算薪事务还没结束时再发锁账会抢这条连接。
因此「计算中点锁账」不并行打两个 HTTP：先写入一条计算中的作业，再调锁账接口。
作业状态由算薪写入，由同文件里的探针用例覆盖。后台任务在请求结束后、连接空闲时直接调服务层。
"""

import asyncio

from datetime import date

from factories import (
    calculate_period,
    expect_error,
    get_period,
    lock_period,
    month_bounds,
    order_row,
    period_payrolls,
    provision_c01_month,
)
from runtime import ApiClient

from backend.database.db import async_db_session
from backend.plugin.rider_salary.enums import CalcJobStatus
from backend.plugin.rider_salary.model.calc_job import RiderSalaryCalcJob
from backend.plugin.rider_salary.service import calc_job_service, calc_service
from backend.plugin.rider_salary.service.import_service import recalc_imported_periods
from backend.plugin.rider_salary.service.period_service import _calculate_period_background


def test_lock_returns_409_while_period_calculating(client: ApiClient, admin_token: dict[str, str]) -> None:
    """计算中标记还在时锁账返回 409，草稿保持不动；标记去掉后可以锁账。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-03',
        orders=[order_row('LK-0301', '2026-03-06')],
        hire_date='2026-03-01',
        rider_name='计算中锁账骑手',
        site_name='计算中锁账站点',
    )
    period_id = ready['period']['id']
    calculate_period(client, admin_token, period_id)
    before = period_payrolls(client, admin_token, period_id)

    job_id = client.loop.run_until_complete(_insert_running_job(period_id=period_id, site_id=int(ready['site']['id'])))
    try:
        response = client.post(
            f'/rider-salary/periods/{period_id}/lock',
            headers=admin_token,
            json={'reason': '计算中尝试锁账'},
        )
        assert '正在算薪' in expect_error(response, 409)
        detail = get_period(client, admin_token, period_id)
        assert detail['status'] == 'open'
        assert [row['id'] for row in detail['payrolls']] == [row['id'] for row in before]
        assert all(row['status'] == 'draft' for row in detail['payrolls'])
    finally:
        client.loop.run_until_complete(_finish_job(job_id))

    lock_period(client, admin_token, period_id, '计算结束后锁账')
    assert get_period(client, admin_token, period_id)['status'] == 'locked'


def test_calculate_sets_period_marker_before_persist(client: ApiClient, admin_token: dict[str, str]) -> None:
    """落库前能看到计算中的作业；请求结束后作业不再处于活动状态。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-04',
        orders=[order_row('MK-0401', '2026-04-06')],
        hire_date='2026-04-01',
        rider_name='标记探针骑手',
        site_name='标记探针站点',
    )
    period_id = ready['period']['id']
    seen: dict[str, object] = {}
    original = calc_service.calculate_rider_period

    async def _spy(db: object, **kwargs: object) -> object:
        period = kwargs['period']
        seen['calculating'] = await calc_job_service.period_has_active_job(db, period.id)  # type: ignore[arg-type]
        return await original(db, **kwargs)  # type: ignore[arg-type]

    calc_service.calculate_rider_period = _spy  # type: ignore[assignment]
    try:
        calculate_period(client, admin_token, period_id)
    finally:
        calc_service.calculate_rider_period = original

    assert seen['calculating'] is True
    still = client.loop.run_until_complete(calc_service.is_period_calculating(period_id))
    assert still is False


def test_background_calc_after_lock_skips_draft(client: ApiClient, admin_token: dict[str, str]) -> None:
    """锁账后跑后台算薪，不新增草稿，周期详情能看到跳过告警。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-05',
        orders=[order_row('BG-0501', '2026-05-06')],
        hire_date='2026-05-01',
        rider_name='锁后后台骑手',
        site_name='锁后后台站点',
    )
    period_id = ready['period']['id']
    calculate_period(client, admin_token, period_id)
    lock_period(client, admin_token, period_id, '后台任务前锁账')
    before_ids = [row['id'] for row in period_payrolls(client, admin_token, period_id)]

    client.loop.run_until_complete(_calculate_period_background(period_id=period_id, rider_ids=None))

    detail = get_period(client, admin_token, period_id)
    assert [row['id'] for row in detail['payrolls']] == before_ids
    assert all(row['status'] != 'draft' for row in detail['payrolls'])
    assert any('未新增草稿' in item for item in detail['calc_warnings'])


def test_import_recalc_failure_is_visible(client: ApiClient, admin_token: dict[str, str]) -> None:
    """导入后自动重算抛错时，失败写进周期告警，不吞成只有日志。"""
    month = '2026-06'
    ready = provision_c01_month(
        client,
        admin_token,
        month=month,
        orders=[order_row('IM-0601', '2026-06-06')],
        hire_date='2026-06-01',
        rider_name='导入重算骑手',
        site_name='导入重算站点',
    )
    period_id = ready['period']['id']
    start, end = month_bounds(month)
    original = calc_service.calculate_period

    async def _boom(*_args: object, **_kwargs: object) -> list[object]:
        await asyncio.sleep(0)
        raise RuntimeError('模拟失败')

    calc_service.calculate_period = _boom  # type: ignore[assignment]
    try:
        client.loop.run_until_complete(
            recalc_imported_periods(
                site_id=ready['site']['id'],
                rider_ids=[ready['rider']['id']],
                date_from=date.fromisoformat(start),
                date_to=date.fromisoformat(end),
                operator_id=1,
            )
        )
    finally:
        calc_service.calculate_period = original

    detail = get_period(client, admin_token, period_id)
    assert any('导入后自动重算失败' in item and '模拟失败' in item for item in detail['calc_warnings'])


async def _insert_running_job(*, period_id: int, site_id: int) -> int:
    async with async_db_session.begin() as db:
        job = RiderSalaryCalcJob(
            period_id=period_id,
            site_id=site_id,
            status=CalcJobStatus.running.value,
            total_count=1,
        )
        db.add(job)
        await db.flush()
        return int(job.id)


async def _finish_job(job_id: int) -> None:
    async with async_db_session.begin() as db:
        job = await db.get(RiderSalaryCalcJob, job_id)
        if job is not None:
            job.status = CalcJobStatus.succeeded.value
