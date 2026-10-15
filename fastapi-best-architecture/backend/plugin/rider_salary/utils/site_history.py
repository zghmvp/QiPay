from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.rider_site_history import RiderSalaryRiderSiteHistory


async def rider_at_site(db: AsyncSession, rider: RiderSalaryRider, site_id: int, biz_date: date) -> bool:
    """业务日骑手是否归属该站点。

    有覆盖该日的履历时以履历为准，否则看当前站点，兼容尚未调岗的历史数据。
    """
    rows = list(
        (
            await db.scalars(
                select(RiderSalaryRiderSiteHistory).where(
                    RiderSalaryRiderSiteHistory.rider_id == rider.id,
                    RiderSalaryRiderSiteHistory.deleted == 0,
                    RiderSalaryRiderSiteHistory.start_date <= biz_date,
                )
            )
        ).all()
    )
    covering = [row for row in rows if row.end_date is None or row.end_date >= biz_date]
    if covering:
        return any(row.site_id == site_id for row in covering)
    return rider.site_id == site_id
