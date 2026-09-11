from sqlalchemy import Select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.utils.timezone import timezone


class CRUDPayrollDetail(CRUDPlus[RiderSalaryPayrollDetail]):
    """薪资明细 CRUD"""

    async def list_by_payroll(self, db: AsyncSession, payroll_id: int) -> list[RiderSalaryPayrollDetail]:
        """薪资单全部明细"""
        rows = await self.select_models_order(db, 'id', 'asc', payroll_id=payroll_id, deleted=0)
        return list(rows)

    async def get_select(
        self,
        payroll_id: int,
        biz_date: str | None,
        stage: str | None,
        subject_id: int | None,
        order_id: int | None,
    ) -> Select:
        """明细分页查询"""
        filters: dict = {'payroll_id': payroll_id, 'deleted': 0}
        if biz_date:
            filters['biz_date'] = biz_date
        if stage:
            filters['stage'] = stage
        if subject_id is not None:
            filters['subject_id'] = subject_id
        if order_id is not None:
            filters['order_id'] = order_id
        return await self.select_order('id', 'asc', **filters)

    async def logical_delete_by_payroll(self, db: AsyncSession, payroll_id: int) -> None:
        """逻辑删除薪资单旧明细"""
        stmt = (
            update(RiderSalaryPayrollDetail)
            .where(
                RiderSalaryPayrollDetail.payroll_id == payroll_id,
                RiderSalaryPayrollDetail.deleted == 0,
            )
            .values(deleted=RiderSalaryPayrollDetail.id, deleted_time=timezone.now())
        )
        await db.execute(stmt)


payroll_detail_dao = CRUDPayrollDetail(RiderSalaryPayrollDetail)
