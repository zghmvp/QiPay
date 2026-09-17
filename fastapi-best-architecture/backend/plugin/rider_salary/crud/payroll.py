from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod


class CRUDPayroll(CRUDPlus[RiderSalaryPayroll]):
    """薪资单 CRUD"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryPayroll | None:
        """按主键获取薪资单"""
        return await self.select_model(db, pk, deleted=0)

    async def get_select(
        self,
        period_id: int | None,
        rider_id: int | None,
        site_id: int | None,
        kind: str | None,
        status: str | None,
        *,
        stale: bool | None,
        site_ids: set[int] | None,
    ) -> Select:
        """列表查询"""
        filters: dict = {'deleted': 0}
        if period_id is not None:
            filters['period_id'] = period_id
        if rider_id is not None:
            filters['rider_id'] = rider_id
        if kind:
            filters['kind'] = kind
        if status:
            filters['status'] = status
        if stale is not None:
            filters['stale'] = stale
        stmt = await self.select_order('id', 'desc', **filters)
        need_join = site_id is not None or site_ids is not None
        if need_join:
            stmt = stmt.join(
                RiderSalarySettlePeriod,
                RiderSalarySettlePeriod.id == RiderSalaryPayroll.period_id,
            )
            if site_id is not None:
                stmt = stmt.where(RiderSalarySettlePeriod.site_id == site_id)
            if site_ids is not None:
                stmt = stmt.where(RiderSalarySettlePeriod.site_id.in_(list(site_ids) or [-1]))
        return stmt

    async def list_by_period_rider(
        self,
        db: AsyncSession,
        period_id: int,
        rider_id: int,
    ) -> list[RiderSalaryPayroll]:
        """周期×骑手下薪资单"""
        rows = await self.select_models(db, period_id=period_id, rider_id=rider_id, deleted=0)
        return list(rows)

    async def get_draft(
        self,
        db: AsyncSession,
        period_id: int,
        rider_id: int,
        kind: str,
    ) -> RiderSalaryPayroll | None:
        """取当前草稿薪资单"""
        from backend.plugin.rider_salary.enums import PayrollStatus

        return await db.scalar(
            select(RiderSalaryPayroll)
            .where(
                RiderSalaryPayroll.period_id == period_id,
                RiderSalaryPayroll.rider_id == rider_id,
                RiderSalaryPayroll.kind == kind,
                RiderSalaryPayroll.status == PayrollStatus.draft.value,
                RiderSalaryPayroll.deleted == 0,
            )
            .order_by(RiderSalaryPayroll.id.desc())
            .limit(1)
        )

    async def get_current(
        self,
        db: AsyncSession,
        period_id: int,
        rider_id: int,
        kind: str,
    ) -> RiderSalaryPayroll | None:
        """取当前未作废薪资单（同 kind 最新）"""
        from backend.plugin.rider_salary.enums import PayrollStatus

        return await db.scalar(
            select(RiderSalaryPayroll)
            .where(
                RiderSalaryPayroll.period_id == period_id,
                RiderSalaryPayroll.rider_id == rider_id,
                RiderSalaryPayroll.kind == kind,
                RiderSalaryPayroll.status != PayrollStatus.voided.value,
                RiderSalaryPayroll.deleted == 0,
            )
            .order_by(RiderSalaryPayroll.id.desc())
            .limit(1)
        )


payroll_dao = CRUDPayroll(RiderSalaryPayroll)
