from collections.abc import Iterable
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.rider_salary.crud.payroll_daily import payroll_daily_dao
from backend.plugin.rider_salary.enums import PayrollStatus, PeriodStatus
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod


async def mark_stale(
    db: AsyncSession,
    *,
    rider_ids: Iterable[int],
    date_from: date,
    date_to: date,
) -> int:
    """
    将覆盖日期范围内、开放或补发中周期（骑手级或 rider_id=0 站点级）下的草稿薪资单标记为需重算

    :param db: 数据库会话
    :param rider_ids: 受影响骑手 ID
    :param date_from: 开始日期
    :param date_to: 结束日期
    :return:
    """
    ids = list({int(rider_id) for rider_id in rider_ids})
    if not ids:
        return 0

    overlapping = select(RiderSalarySettlePeriod.id).where(
        RiderSalarySettlePeriod.status.in_([PeriodStatus.open, PeriodStatus.reopened]),
        RiderSalarySettlePeriod.start_date <= date_to,
        RiderSalarySettlePeriod.end_date >= date_from,
        RiderSalarySettlePeriod.deleted == 0,
        RiderSalarySettlePeriod.rider_id.in_([*ids, 0]),
    )
    stmt = (
        update(RiderSalaryPayroll)
        .where(
            RiderSalaryPayroll.rider_id.in_(ids),
            RiderSalaryPayroll.status == PayrollStatus.draft,
            RiderSalaryPayroll.deleted == 0,
            RiderSalaryPayroll.period_id.in_(overlapping),
        )
        .values(stale=True)
    )
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


async def invalidate_payroll_dailies(
    db: AsyncSession,
    *,
    rider_ids: Iterable[int],
    date_from: date,
    date_to: date,
) -> int:
    """
    绑定变更后逻辑删除受影响日的 rs_payroll_daily，避免日历/工作台继续信任过期方案快照。

    :param db: 数据库会话
    :param rider_ids: 受影响骑手 ID
    :param date_from: 开始日期
    :param date_to: 结束日期
    :return: 删除行数
    """
    ids = list({int(rider_id) for rider_id in rider_ids})
    if not ids or date_to < date_from:
        return 0
    total = 0
    for rider_id in ids:
        total += await payroll_daily_dao.soft_delete_by_rider_range(db, rider_id, date_from, date_to)
    return total
