"""FIN-1 结算链路回归（A1 二次反冲、A2 锁账漏算、A6 回退归还预支）"""

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import PayrollKind, PayrollStatus
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.service.calc_service import calculate_period
from backend.plugin.rider_salary.service.period_service import period_service
from backend.plugin.rider_salary.tests.integration.harness import Seed, admin_request, run_db
from backend.utils.timezone import timezone

SEP1, SEP30 = date(2026, 9, 1), date(2026, 9, 30)


async def _payrolls(db: AsyncSession, period_id: int) -> list[RiderSalaryPayroll]:
    return list(
        (
            await db.scalars(
                select(RiderSalaryPayroll)
                .where(RiderSalaryPayroll.period_id == period_id, RiderSalaryPayroll.deleted == 0)
                .order_by(RiderSalaryPayroll.id)
            )
        ).all()
    )


def _net_sum(rows: list[RiderSalaryPayroll]) -> Decimal:
    return sum((row.net for row in rows if row.status != PayrollStatus.voided.value), Decimal(0))


def test_a1_second_reverse_cycle_can_recalculate() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, SEP1)
        period = await seed.period(site, SEP1, SEP30)
        await seed.orders(rider, date(2026, 9, 3), 10)

        await calculate_period(db, period_id=period.id, operator=req)
        await period_service.lock(db=db, request=req, pk=period.id, reason='首次锁账')
        await period_service.mark_paid(db=db, request=req, pk=period.id, reason=None)
        for round_no in (1, 2):
            await period_service.reverse(db=db, request=req, pk=period.id, reason=f'第{round_no}次反冲')
            await calculate_period(db, period_id=period.id, operator=req)
            await period_service.lock(db=db, request=req, pk=period.id, reason=f'第{round_no}次再锁')
            await period_service.mark_paid(db=db, request=req, pk=period.id, reason=None)

        rows = await _payrolls(db, period.id)
        assert _net_sum(rows) == Decimal('50.00')
        supplements = [r for r in rows if r.kind == PayrollKind.supplement.value]
        assert len(supplements) == 2

    run_db(_case)


def test_a2_lock_rejects_uncalculated_rider() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        version = await seed.plan_version([{'formula': '5'}])
        calculated = await seed.rider(site)
        missing = await seed.rider(site)
        for rider in (calculated, missing):
            await seed.bind(rider, version, SEP1)
        period = await seed.period(site, SEP1, SEP30)
        await seed.orders(calculated, date(2026, 9, 3), 2)
        await calculate_period(db, period_id=period.id, rider_ids=[calculated.id], operator=req)
        await seed.orders(missing, date(2026, 9, 4), 3)

        with pytest.raises(errors.RequestError) as exc:
            await period_service.lock(db=db, request=req, pk=period.id, reason='锁账')
        assert missing.job_no in exc.value.msg

    run_db(_case)


def test_a6_rollback_void_draft_restores_advance() -> None:
    from backend.plugin.rider_salary.schema.rollback import RollbackParam
    from backend.plugin.rider_salary.service.rollback_service import rollback_service

    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, SEP1)
        period = await seed.period(site, SEP1, SEP30)
        await seed.orders(rider, date(2026, 9, 3), 10)
        advance = await seed.paid_advance(
            rider, '30.00', paid_time=datetime.combine(date(2026, 9, 10), time(12), tzinfo=timezone.tz_info)
        )
        await calculate_period(db, period_id=period.id, operator=req)
        await db.refresh(advance)
        assert advance.remaining_amount == Decimal('0.00')

        await rollback_service.rollback(db, version.id, RollbackParam(reason='方案错误'), req)
        await db.refresh(advance)
        assert advance.remaining_amount == Decimal('30.00')
        assert advance.deducted_amount == Decimal('0.00')

    run_db(_case)


def test_a4_site_period_covers_days_outside_rider_level_period() -> None:
    from backend.plugin.rider_salary.model.order import RiderSalaryOrder

    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, SEP1)
        site_period = await seed.period(site, SEP1, SEP30)
        rider_period = await seed.period(site, SEP1, date(2026, 9, 10), rider_id=rider.id)
        early = await seed.orders(rider, date(2026, 9, 5), 5)
        late = await seed.orders(rider, date(2026, 9, 20), 3)

        site_results = await calculate_period(db, period_id=site_period.id, operator=req)
        rider_results = await calculate_period(db, period_id=rider_period.id, operator=req)
        assert [r.net for r in site_results] == [Decimal('15.00')]
        assert [r.net for r in rider_results] == [Decimal('25.00')]

        await period_service.lock(db=db, request=req, pk=site_period.id, reason='锁账')
        for order in early + late:
            await db.refresh(order)
        assert all(not o.is_locked for o in early)
        assert all(o.is_locked for o in late)
        assert isinstance(early[0], RiderSalaryOrder)

    run_db(_case)


async def _site_periods(db: AsyncSession, site_id: int, rider_id: int = 0) -> list[tuple[date, date]]:
    from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod

    rows = await db.scalars(
        select(RiderSalarySettlePeriod)
        .where(
            RiderSalarySettlePeriod.site_id == site_id,
            RiderSalarySettlePeriod.rider_id == rider_id,
            RiderSalarySettlePeriod.deleted == 0,
        )
        .order_by(RiderSalarySettlePeriod.start_date)
    )
    return [(row.start_date, row.end_date) for row in rows.all()]


def test_a3_cycle_change_never_overlaps_existing_periods() -> None:
    from backend.plugin.rider_salary.schema.period import GeneratePeriodParam

    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site(settle_cycle='month')
        await period_service.generate(db=db, request=req, obj=GeneratePeriodParam(site_id=site.id, month='2026-09'))
        site.settle_cycle = 'half_month'
        await db.flush()
        await period_service.generate(db=db, request=req, obj=GeneratePeriodParam(site_id=site.id, month='2026-09'))
        await period_service.generate(db=db, request=req, obj=GeneratePeriodParam(site_id=site.id, month='2026-10'))
        assert await _site_periods(db, site.id) == [
            (date(2026, 9, 1), date(2026, 9, 30)),
            (date(2026, 10, 1), date(2026, 10, 15)),
            (date(2026, 10, 16), date(2026, 10, 31)),
        ]

        other = await seed.site(settle_cycle='half_month')
        await seed.period(other, SEP1, date(2026, 9, 15), cycle_type='half_month')
        other.settle_cycle = 'month'
        await db.flush()
        await period_service.generate(db=db, request=req, obj=GeneratePeriodParam(site_id=other.id, month='2026-09'))
        assert await _site_periods(db, other.id) == [
            (date(2026, 9, 1), date(2026, 9, 15)),
            (date(2026, 9, 16), date(2026, 9, 30)),
        ]

    run_db(_case)


def test_a3_rider_override_skips_dates_settled_by_site_period() -> None:
    from backend.plugin.rider_salary.schema.period import GeneratePeriodParam

    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site(settle_cycle='month')
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, SEP1)
        await seed.orders(rider, date(2026, 9, 3), 4)
        period = await seed.period(site, SEP1, SEP30)
        await calculate_period(db, period_id=period.id, operator=req)
        await period_service.lock(db=db, request=req, pk=period.id, reason='锁账')

        rider.settle_cycle_override = 'half_month'
        await db.flush()
        await period_service.generate(db=db, request=req, obj=GeneratePeriodParam(site_id=site.id, month='2026-09'))
        assert await _site_periods(db, site.id, rider.id) == []
        await period_service.generate(db=db, request=req, obj=GeneratePeriodParam(site_id=site.id, month='2026-10'))
        assert await _site_periods(db, site.id, rider.id) == [
            (date(2026, 10, 1), date(2026, 10, 15)),
            (date(2026, 10, 16), date(2026, 10, 31)),
        ]

    run_db(_case)


def test_b8_mid_period_plan_switch_pays_base_and_guarantee_once() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        items = [
            {'formula': '5'},
            {'formula': '3000', 'stage': 'period', 'name': '底薪'},
            {'formula': '最大值(4000 - 本期已计金额, 0)', 'stage': 'period', 'name': '保底'},
            {'formula': '10 * 方案期内单量', 'stage': 'period', 'name': '段内冲单奖'},
        ]
        first = await seed.plan_version(items)
        second = await seed.plan_version(items)
        await seed.bind(rider, first, SEP1, date(2026, 9, 15))
        await seed.bind(rider, second, date(2026, 9, 16))
        await seed.orders(rider, date(2026, 9, 3), 10)
        await seed.orders(rider, date(2026, 9, 20), 10)
        period = await seed.period(site, SEP1, SEP30)
        await calculate_period(db, period_id=period.id, operator=req)
        row = (await _payrolls(db, period.id))[0]
        # 逐单 100 + 段内冲单奖 100×2 + 底薪 3000（一次）= 3300，保底补到 4000 一次
        assert row.gross == Decimal(4000)
        assert any('只按期末方案计算一次' in text for text in row.warnings or [])

    run_db(_case)


def test_b10_calendar_day_shows_only_effective_payroll_amounts() -> None:
    from backend.plugin.rider_salary.service.calendar_service import calendar_service

    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, SEP1)
        await seed.orders(rider, date(2026, 9, 3), 2)
        period = await seed.period(site, SEP1, SEP30)
        await calculate_period(db, period_id=period.id, operator=req)
        await period_service.lock(db=db, request=req, pk=period.id, reason='锁账')
        await period_service.reverse(db=db, request=req, pk=period.id, reason='补发')
        await calculate_period(db, period_id=period.id, operator=req)

        day = await calendar_service.build_day(db, rider.id, date(2026, 9, 3))
        # 原单 +10、反冲 -10、补发 +10：只显示补发单的 10
        assert day.totals.formula_amount == Decimal(10)
        assert [[hit.amount for hit in order.details] for order in day.orders] == [[Decimal(5)], [Decimal(5)]]

    run_db(_case)


def test_b11_voided_plan_version_is_not_paid() -> None:
    from backend.plugin.rider_salary.enums import PlanVersionStatus

    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, SEP1)
        await seed.orders(rider, date(2026, 9, 3), 2)
        version.status = PlanVersionStatus.voided.value
        await db.flush()
        period = await seed.period(site, SEP1, SEP30)
        await calculate_period(db, period_id=period.id, operator=admin_request())
        row = (await _payrolls(db, period.id))[0]
        assert row.gross == Decimal(0)
        assert any('已作废' in text for text in row.warnings or [])

    run_db(_case)
