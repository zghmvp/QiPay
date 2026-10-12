from datetime import date
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.enums import DayStatus
from backend.plugin.rider_salary.model.payroll_daily import RiderSalaryPayrollDaily

# 反冲后清掉日金额。单量保留，工资数字不再沿用反冲前的缓存。
PENDING_RECALC_DAILY_VALUES = {
    'day_status': DayStatus.pending_recalc.value,
    'formula_amount': Decimal('0.00'),
    'manual_bonus': Decimal('0.00'),
    'manual_penalty': Decimal('0.00'),
    'net_adjust': Decimal('0.00'),
}


class CRUDPayrollDaily(CRUDPlus[RiderSalaryPayrollDaily]):
    """日汇总 CRUD"""

    async def list_by_rider_range(
        self,
        db: AsyncSession,
        rider_id: int,
        start: date,
        end: date,
    ) -> list[RiderSalaryPayrollDaily]:
        """骑手日期区间日汇总"""
        rows = await db.scalars(
            select(RiderSalaryPayrollDaily)
            .where(
                RiderSalaryPayrollDaily.rider_id == rider_id,
                RiderSalaryPayrollDaily.biz_date >= start,
                RiderSalaryPayrollDaily.biz_date <= end,
                RiderSalaryPayrollDaily.deleted == 0,
            )
            .order_by(RiderSalaryPayrollDaily.biz_date.asc())
        )
        return list(rows.all())

    async def get_one(self, db: AsyncSession, rider_id: int, biz_date: date) -> RiderSalaryPayrollDaily | None:
        """取单日汇总"""
        return await db.scalar(
            select(RiderSalaryPayrollDaily).where(
                RiderSalaryPayrollDaily.rider_id == rider_id,
                RiderSalaryPayrollDaily.biz_date == biz_date,
                RiderSalaryPayrollDaily.deleted == 0,
            )
        )

    async def mark_period_pending_recalc(self, db: AsyncSession, period_id: int) -> None:
        """把该周期的日汇总标成待补算，并清掉缓存金额。

        :param db: 数据库会话
        :param period_id: 结算周期 ID
        """
        await db.execute(
            update(RiderSalaryPayrollDaily)
            .where(
                RiderSalaryPayrollDaily.period_id == period_id,
                RiderSalaryPayrollDaily.deleted == 0,
            )
            .values(**PENDING_RECALC_DAILY_VALUES)
        )


payroll_daily_dao = CRUDPayrollDaily(RiderSalaryPayrollDaily)
