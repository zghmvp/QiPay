from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.payroll_daily import RiderSalaryPayrollDaily


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


payroll_daily_dao = CRUDPayrollDaily(RiderSalaryPayrollDaily)
