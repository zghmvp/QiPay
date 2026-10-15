"""FIN-1 欠款结转（#32）与预支抵扣归属（#33）回归"""

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.rider_salary.enums import DetailSource, PayrollKind, PayrollStatus, SubjectDirection
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.service.calc_service import calculate_period
from backend.plugin.rider_salary.service.period_service import period_service
from backend.plugin.rider_salary.tests.integration.harness import Seed, admin_request, run_db
from backend.utils.timezone import timezone

SEP1, SEP30 = date(2026, 9, 1), date(2026, 9, 30)
OCT1, OCT31 = date(2026, 10, 1), date(2026, 10, 31)
NOV1, NOV30 = date(2026, 11, 1), date(2026, 11, 30)


async def _current(db: AsyncSession, period_id: int, rider_id: int) -> RiderSalaryPayroll:
    rows = (
        await db.scalars(
            select(RiderSalaryPayroll)
            .where(
                RiderSalaryPayroll.period_id == period_id,
                RiderSalaryPayroll.rider_id == rider_id,
                RiderSalaryPayroll.kind != PayrollKind.reversal.value,
                RiderSalaryPayroll.reversed.is_(False),
                RiderSalaryPayroll.status != PayrollStatus.voided.value,
                RiderSalaryPayroll.deleted == 0,
            )
            .order_by(RiderSalaryPayroll.id.desc())
        )
    ).all()
    assert rows
    return rows[0]


async def _penalty(seed: Seed, rider: RiderSalaryRider, day: date, amount: str) -> RiderSalaryAdjustment:
    subject = await seed.subject(SubjectDirection.penalty.value, include_in_gross=False)
    return await seed.add(
        RiderSalaryAdjustment(
            rider_id=rider.id,
            site_id=rider.site_id,
            biz_date=day,
            subject_id=subject.id,
            amount=Decimal(amount),
            remark='罚款',
        )
    )


async def _calc_lock(db: AsyncSession, period: RiderSalarySettlePeriod) -> None:
    req = admin_request()
    await calculate_period(db, period_id=period.id, operator=req)
    await period_service.lock(db=db, request=req, pk=period.id, reason='锁账')


def test_a8_negative_net_carries_forward_and_refunds_after_correction() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, SEP1)
        sep = await seed.period(site, SEP1, SEP30)
        octo = await seed.period(site, OCT1, OCT31)
        nov = await seed.period(site, NOV1, NOV30)
        await seed.orders(rider, date(2026, 9, 3), 1)
        penalty = await _penalty(seed, rider, date(2026, 9, 4), '30')
        await seed.orders(rider, date(2026, 10, 3), 10)
        await seed.orders(rider, date(2026, 11, 3), 10)

        await _calc_lock(db, sep)
        sep_row = await _current(db, sep.id, rider.id)
        assert (sep_row.gross, sep_row.deduction_total, sep_row.net) == (Decimal(5), Decimal(30), Decimal(0))
        assert sep_row.carry_out == Decimal(25)

        await _calc_lock(db, octo)
        oct_row = await _current(db, octo.id, rider.id)
        assert oct_row.carry_in == Decimal(25)
        assert oct_row.net == Decimal(25)
        carry_rows = (
            await db.scalars(
                select(RiderSalaryPayrollDetail).where(
                    RiderSalaryPayrollDetail.payroll_id == oct_row.id,
                    RiderSalaryPayrollDetail.source == DetailSource.carry.value,
                    RiderSalaryPayrollDetail.deleted == 0,
                )
            )
        ).all()
        assert [row.amount for row in carry_rows] == [Decimal(-25)]

        # 9 月罚款改为 10 元：反冲补发后 9 月只欠 5 元，10 月已多扣 20 元，11 月退回
        await period_service.reverse(db=db, request=req, pk=sep.id, reason='罚款录错')
        penalty.amount = Decimal(10)
        penalty.signed_amount = None
        await db.flush()
        await _calc_lock(db, sep)
        assert (await _current(db, sep.id, rider.id)).carry_out == Decimal(5)

        await calculate_period(db, period_id=nov.id, operator=req)
        nov_row = await _current(db, nov.id, rider.id)
        assert nov_row.carry_in == Decimal(-20)
        assert nov_row.net == Decimal(70)
        assert nov_row.carry_out == Decimal(0)

    run_db(_case)


def test_b7_advance_paid_later_is_not_deducted_from_earlier_period() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, SEP1)
        sep = await seed.period(site, SEP1, SEP30)
        octo = await seed.period(site, OCT1, OCT31)
        await seed.orders(rider, date(2026, 9, 3), 10)
        await seed.orders(rider, date(2026, 10, 3), 10)
        advance = await seed.paid_advance(
            rider, '20', paid_time=datetime.combine(date(2026, 10, 10), time(12), tzinfo=timezone.tz_info)
        )

        await _calc_lock(db, sep)
        sep_row = await _current(db, sep.id, rider.id)
        assert sep_row.advance_deduction == Decimal(0)
        assert sep_row.net == Decimal(50)

        await calculate_period(db, period_id=octo.id, operator=admin_request())
        oct_row = await _current(db, octo.id, rider.id)
        assert oct_row.advance_deduction == Decimal(20)
        assert oct_row.net == Decimal(30)
        assert advance.remaining_amount == Decimal(0)

    run_db(_case)


def test_b7_later_open_period_defers_until_earlier_period_locks() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, SEP1)
        sep = await seed.period(site, SEP1, SEP30)
        octo = await seed.period(site, OCT1, OCT31)
        await seed.orders(rider, date(2026, 9, 3), 2)
        await seed.orders(rider, date(2026, 10, 3), 10)
        advance = await seed.paid_advance(
            rider, '40', paid_time=datetime.combine(date(2026, 9, 10), time(12), tzinfo=timezone.tz_info)
        )

        # 10 月先算：此时 9 月尚无草稿，10 月先抵扣
        await calculate_period(db, period_id=octo.id, operator=req)
        assert (await _current(db, octo.id, rider.id)).advance_deduction == Decimal(40)

        # 9 月再算：把 10 月占用的预支还回来，由 9 月优先抵扣，10 月需重算
        await calculate_period(db, period_id=sep.id, operator=req)
        sep_row = await _current(db, sep.id, rider.id)
        assert sep_row.advance_deduction == Decimal(10)
        oct_row = await _current(db, octo.id, rider.id)
        assert oct_row.stale is True
        assert oct_row.advance_deduction == Decimal(0)
        assert advance.remaining_amount == Decimal(30)

        # 9 月未锁账时重算 10 月：暂不抵扣
        await calculate_period(db, period_id=octo.id, operator=req)
        oct_row = await _current(db, octo.id, rider.id)
        assert oct_row.advance_deduction == Decimal(0)
        assert any('更早的结算周期尚未锁账' in text for text in oct_row.warnings or [])

        # 9 月锁账后 10 月标记需重算，重算后抵扣剩余 30 元
        await period_service.lock(db=db, request=req, pk=sep.id, reason='锁账')
        assert (await _current(db, octo.id, rider.id)).stale is True
        await calculate_period(db, period_id=octo.id, operator=req)
        oct_row = await _current(db, octo.id, rider.id)
        assert oct_row.advance_deduction == Decimal(30)
        assert oct_row.net == Decimal(20)
        assert advance.remaining_amount == Decimal(0)

    run_db(_case)


def test_a5_quote_counts_undeducted_advance_and_estimate_subtracts_it() -> None:
    from backend.plugin.rider_salary.service.advance_policy_service import advance_policy_service
    from backend.plugin.rider_salary.service.me_service import me_service

    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '100'}])
        today = timezone.now().date()
        await seed.bind(rider, version, today.replace(day=1))
        await seed.orders(rider, today, 10)
        await seed.paid_advance(rider, '300', paid_time=timezone.now())

        quote = await advance_policy_service.evaluate(db, rider)
        assert quote.estimate_net == Decimal(1000)
        assert quote.used_pending_amount == Decimal(300)
        assert quote.available == Decimal(200)

        estimate = await me_service.payroll_estimate(db=db, rider=rider)
        assert estimate.advance_deduction_estimate == Decimal(300)
        assert estimate.net_estimate == Decimal(700)

        # 算薪落库后（草稿已暂扣预支），额度口径不变
        period = await period_service.get_or_create_period(db, site.id, rider.id, today)
        await calculate_period(db, period_id=period.id, operator=admin_request())
        quote = await advance_policy_service.evaluate(db, rider)
        assert quote.estimate_net == Decimal(1000)
        assert quote.used_pending_amount == Decimal(300)
        assert quote.available == Decimal(200)

    run_db(_case)


def test_a9_leave_blocks_in_flight_and_requires_confirm_for_outstanding() -> None:
    import pytest

    from backend.common.exception import errors
    from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
    from backend.plugin.rider_salary.schema.rider import RiderLeaveParam
    from backend.plugin.rider_salary.service.rider_service import rider_service

    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        pending = await seed.add(
            RiderSalaryAdvance(rider_id=rider.id, site_id=site.id, amount=Decimal(50), reason='急用', status='pending')
        )
        leave = RiderLeaveParam(leave_date=date(2026, 10, 20), reason='个人原因')
        with pytest.raises(errors.RequestError, match='待审核或待发放'):
            await rider_service.leave(db=db, request=req, pk=rider.id, obj=leave)

        pending.status = 'rejected'
        await seed.paid_advance(rider, '120')
        check = await rider_service.leave_check(db=db, request=req, pk=rider.id)
        assert (check.in_flight_count, check.undeducted_amount, check.debt_amount) == (0, Decimal(120), Decimal(0))
        with pytest.raises(errors.RequestError, match='未扣回预支 120.00 元'):
            await rider_service.leave(db=db, request=req, pk=rider.id, obj=leave)

        leave.confirm_outstanding = True
        assert await rider_service.leave(db=db, request=req, pk=rider.id, obj=leave) > 0
        await db.refresh(rider)
        assert rider.leave_date == date(2026, 10, 20)

    run_db(_case)
