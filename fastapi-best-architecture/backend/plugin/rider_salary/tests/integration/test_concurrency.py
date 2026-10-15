"""FIN-1 并发回归：B3 锁账后不能再算薪，B4 周期状态流转加行锁"""

from datetime import date

import anyio
import pytest

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.service.calc_service import calculate_period, calculate_rider_period
from backend.plugin.rider_salary.service.period_service import period_service
from backend.plugin.rider_salary.tests.integration.harness import Seed, admin_request, run_db

SEP1, SEP30 = date(2026, 9, 1), date(2026, 9, 30)


def test_b3_calc_rejected_once_period_locked_elsewhere() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, SEP1)
        period = await seed.period(site, SEP1, SEP30)
        await seed.orders(rider, date(2026, 9, 3), 2)
        # 模拟另一事务已锁账：内存里的周期对象仍是 open
        await db.execute(
            update(RiderSalarySettlePeriod).where(RiderSalarySettlePeriod.id == period.id).values(status='locked')
        )
        with pytest.raises(errors.RequestError, match='不允许算薪'):
            await calculate_rider_period(db, rider_id=rider.id, period=period, persist=True)

    run_db(_case)


def test_b4_concurrent_reverse_runs_once() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, SEP1)
        period = await seed.period(site, SEP1, SEP30)
        await seed.orders(rider, date(2026, 9, 3), 2)
        await calculate_period(db, period_id=period.id, operator=req)
        await period_service.lock(db=db, request=req, pk=period.id, reason='锁账')
        await db.commit()

        first = AsyncSession(db.bind, expire_on_commit=False)
        second = AsyncSession(db.bind, expire_on_commit=False)
        outcome: dict[str, object] = {}
        try:
            await period_service.reverse(db=first, request=req, pk=period.id, reason='第一次')

            async def _second() -> None:
                try:
                    await period_service.reverse(db=second, request=req, pk=period.id, reason='第二次')
                    outcome['second'] = 'ok'
                except errors.RequestError as exc:
                    outcome['second'] = exc.msg

            async with anyio.create_task_group() as tg:
                tg.start_soon(_second)
                await anyio.sleep(0.5)
                # 第一个事务未提交前，第二个反冲必须在行锁上等待
                assert 'second' not in outcome
                await first.commit()
            assert outcome['second'] != 'ok'
        finally:
            await second.rollback()
            await first.close()
            await second.close()

    run_db(_case)


def test_b5_concurrent_advance_submits_allow_only_one_in_flight() -> None:
    from decimal import Decimal

    from backend.plugin.rider_salary.model.rider import RiderSalaryRider
    from backend.plugin.rider_salary.schema.advance import CreateMeAdvanceParam
    from backend.plugin.rider_salary.service.advance_service import advance_service
    from backend.utils.timezone import timezone

    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '100'}])
        today = timezone.now().date()
        await seed.bind(rider, version, today.replace(day=1))
        await seed.orders(rider, today, 10)
        await db.commit()

        first = AsyncSession(db.bind, expire_on_commit=False)
        second = AsyncSession(db.bind, expire_on_commit=False)
        outcome: dict[str, object] = {}
        param = CreateMeAdvanceParam(amount=Decimal(100), reason='急用')
        try:
            rider_a = await first.get(RiderSalaryRider, rider.id)
            rider_b = await second.get(RiderSalaryRider, rider.id)
            await advance_service.submit_for_rider(db=first, request=req, rider=rider_a, obj=param)

            async def _second() -> None:
                try:
                    await advance_service.submit_for_rider(db=second, request=req, rider=rider_b, obj=param)
                    outcome['second'] = 'ok'
                except errors.RequestError as exc:
                    outcome['second'] = exc.msg

            async with anyio.create_task_group() as tg:
                tg.start_soon(_second)
                await anyio.sleep(0.5)
                assert 'second' not in outcome
                await first.commit()
            assert outcome['second'] != 'ok'
        finally:
            await second.rollback()
            await first.close()
            await second.close()

    run_db(_case)


def test_c1_concurrent_same_order_no_returns_chinese_error() -> None:
    from datetime import datetime
    from decimal import Decimal

    from backend.plugin.rider_salary.schema.order import CreateOrderParam
    from backend.plugin.rider_salary.service.order_service import order_service
    from backend.utils.timezone import timezone

    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        await db.commit()

        now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.tz_info)
        param = CreateOrderParam(
            order_no='DUP-1',
            site_id=site.id,
            rider_id=rider.id,
            distance_km=Decimal(1),
            weight_jin=Decimal(1),
            order_time=now,
            deliver_time=now,
            status='completed',
        )
        first = AsyncSession(db.bind, expire_on_commit=False)
        second = AsyncSession(db.bind, expire_on_commit=False)
        outcome: dict[str, object] = {}
        try:
            await order_service.create(db=first, request=req, obj=param)

            async def _second() -> None:
                try:
                    await order_service.create(db=second, request=req, obj=param)
                    outcome['second'] = 'ok'
                except errors.RequestError as exc:
                    outcome['second'] = exc.msg

            async with anyio.create_task_group() as tg:
                tg.start_soon(_second)
                await anyio.sleep(0.5)
                await first.commit()
            assert outcome['second'] == '订单号已存在'
        finally:
            await second.rollback()
            await first.close()
            await second.close()

    run_db(_case)
