from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.schema.plan import CreatePlanParam, UpdatePlanParam
from backend.utils.timezone import timezone


class CRUDPlan(CRUDPlus[RiderSalaryPlan]):
    """方案 CRUD"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryPlan | None:
        """按主键获取方案"""
        return await self.select_model(db, pk, deleted=0)

    async def get_by_code(self, db: AsyncSession, code: str) -> RiderSalaryPlan | None:
        """按编码获取方案"""
        return await self.select_model_by_column(db, code=code, deleted=0)

    async def get_select(self, name: str | None, status: str | None) -> Select:
        """列表查询"""
        filters: dict = {'deleted': 0}
        if name:
            filters['name__like'] = f'%{name}%'
        if status:
            filters['status'] = status
        return await self.select_order('id', 'desc', **filters)

    async def get_all(self, db: AsyncSession) -> Sequence[RiderSalaryPlan]:
        """全部方案"""
        return await self.select_models(db, deleted=0)

    async def create(self, db: AsyncSession, obj: CreatePlanParam) -> RiderSalaryPlan:
        """创建方案"""
        return await self.create_model(db, obj)

    async def update(self, db: AsyncSession, pk: int, obj: UpdatePlanParam) -> int:
        """更新方案"""
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """逻辑删除方案"""
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            id=pk,
            deleted=0,
        )

    async def count_versions(self, db: AsyncSession, plan_id: int) -> int:
        """方案下未删除版本数"""
        from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion

        result = await db.scalar(
            select(func.count())
            .select_from(RiderSalaryPlanVersion)
            .where(RiderSalaryPlanVersion.plan_id == plan_id, RiderSalaryPlanVersion.deleted == 0)
        )
        return int(result or 0)


plan_dao = CRUDPlan(RiderSalaryPlan)
