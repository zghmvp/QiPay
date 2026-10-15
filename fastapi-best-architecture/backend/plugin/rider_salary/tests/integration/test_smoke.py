from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.rider_salary.service.calc_service import calculate_period
from backend.plugin.rider_salary.tests.integration.harness import Seed, admin_request, run_db


def test_basic_period_calc() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        site = await seed.site()
        rider = await seed.rider(site)
        version = await seed.plan_version([{'formula': '5'}])
        await seed.bind(rider, version, date(2026, 9, 1))
        period = await seed.period(site, date(2026, 9, 1), date(2026, 9, 30))
        await seed.orders(rider, date(2026, 9, 3), 10)
        results = await calculate_period(db, period_id=period.id, operator=admin_request())
        assert len(results) == 1
        assert results[0].net == Decimal('50.00')

    run_db(_case)
