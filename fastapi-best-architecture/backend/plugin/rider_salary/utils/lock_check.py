from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import PeriodStatus
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod

_LOCKED_STATUSES = {PeriodStatus.locked, PeriodStatus.paid}
_LOCKED_STATUS_VALUES = {item.value for item in _LOCKED_STATUSES}
_SITE_LEVEL_RIDER_ID = 0


def is_status_locked(status: str | PeriodStatus | None) -> bool:
    """周期状态是否视为已锁账（locked / paid）"""
    if status is None:
        return False
    return status in _LOCKED_STATUSES or status in _LOCKED_STATUS_VALUES


async def find_covering_period(
    db: AsyncSession,
    *,
    site_id: int,
    rider_id: int | None,
    biz_date: date,
) -> RiderSalarySettlePeriod | None:
    """
    查找覆盖目标日期的结算周期

    优先骑手级周期（rider_id=该骑手），再站点级（rider_id=0）；无周期返回 None
    """
    period = None
    if rider_id:
        period = await db.scalar(
            select(RiderSalarySettlePeriod)
            .where(
                RiderSalarySettlePeriod.site_id == site_id,
                RiderSalarySettlePeriod.rider_id == rider_id,
                RiderSalarySettlePeriod.start_date <= biz_date,
                RiderSalarySettlePeriod.end_date >= biz_date,
                RiderSalarySettlePeriod.deleted == 0,
            )
            .limit(1)
        )
    if period is None:
        period = await db.scalar(
            select(RiderSalarySettlePeriod)
            .where(
                RiderSalarySettlePeriod.site_id == site_id,
                RiderSalarySettlePeriod.rider_id == _SITE_LEVEL_RIDER_ID,
                RiderSalarySettlePeriod.start_date <= biz_date,
                RiderSalarySettlePeriod.end_date >= biz_date,
                RiderSalarySettlePeriod.deleted == 0,
            )
            .limit(1)
        )
    return period


async def is_locked(
    db: AsyncSession,
    *,
    site_id: int,
    rider_id: int | None,
    biz_date: date,
) -> bool:
    """目标日期所属周期是否 locked/paid；无周期视为未锁"""
    period = await find_covering_period(db, site_id=site_id, rider_id=rider_id, biz_date=biz_date)
    return is_status_locked(None if period is None else period.status)


async def locked_dates_in_range(
    db: AsyncSession,
    *,
    site_id: int,
    rider_id: int | None,
    date_from: date,
    date_to: date,
) -> set[date]:
    """
    返回区间内所属周期为 locked/paid 的日期集合

    逐日规则与 find_covering_period 一致：骑手级优先，再站点级
    """
    rider_filter = [_SITE_LEVEL_RIDER_ID]
    if rider_id:
        rider_filter.append(rider_id)
    rows = list(
        (
            await db.scalars(
                select(RiderSalarySettlePeriod).where(
                    RiderSalarySettlePeriod.site_id == site_id,
                    RiderSalarySettlePeriod.rider_id.in_(rider_filter),
                    RiderSalarySettlePeriod.start_date <= date_to,
                    RiderSalarySettlePeriod.end_date >= date_from,
                    RiderSalarySettlePeriod.deleted == 0,
                )
            )
        ).all()
    )
    rider_periods = [row for row in rows if rider_id and row.rider_id == rider_id]
    site_periods = [row for row in rows if row.rider_id == _SITE_LEVEL_RIDER_ID]
    locked: set[date] = set()
    current = date_from
    while current <= date_to:
        period = _pick_period(current, rider_periods, site_periods)
        if is_status_locked(None if period is None else period.status):
            locked.add(current)
        current += timedelta(days=1)
    return locked


async def assert_not_locked(
    db: AsyncSession,
    *,
    site_id: int,
    rider_id: int | None,
    biz_date: date,
) -> None:
    """
    校验目标日期所属结算周期未锁账、未发薪

    优先匹配骑手级周期（rider_id=该骑手），再匹配站点级周期（rider_id=0）；无周期则放行

    :param db: 数据库会话
    :param site_id: 站点 ID
    :param rider_id: 骑手 ID
    :param biz_date: 业务日期
    :return:
    """
    if await is_locked(db, site_id=site_id, rider_id=rider_id, biz_date=biz_date):
        raise errors.ForbiddenError(msg='该日期所属结算周期已锁账，禁止修改，请走反冲补发流程')


def _pick_period(
    biz_date: date,
    rider_periods: list[RiderSalarySettlePeriod],
    site_periods: list[RiderSalarySettlePeriod],
) -> RiderSalarySettlePeriod | None:
    for row in rider_periods:
        if row.start_date <= biz_date <= row.end_date:
            return row
    for row in site_periods:
        if row.start_date <= biz_date <= row.end_date:
            return row
    return None
