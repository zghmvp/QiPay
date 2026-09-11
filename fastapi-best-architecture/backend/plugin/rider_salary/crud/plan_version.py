from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.schema.plan import CreatePlanVersionParam, UpdatePlanVersionParam
from backend.utils.timezone import timezone


class CRUDPlanVersion(CRUDPlus[RiderSalaryPlanVersion]):
    """方案版本 CRUD"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryPlanVersion | None:
        """按主键获取版本"""
        return await self.select_model(db, pk, deleted=0)

    async def get_select(self, plan_id: int | None, status: str | None) -> Select:
        """列表查询"""
        filters: dict = {'deleted': 0}
        if plan_id is not None:
            filters['plan_id'] = plan_id
        if status:
            filters['status'] = status
        return await self.select_order('id', 'desc', **filters)

    async def next_version_no(self, db: AsyncSession, plan_id: int) -> int:
        """同方案下一版本号"""
        current = await db.scalar(
            select(func.max(RiderSalaryPlanVersion.version_no)).where(
                RiderSalaryPlanVersion.plan_id == plan_id,
                RiderSalaryPlanVersion.deleted == 0,
            )
        )
        return int(current or 0) + 1

    async def get_active_list(self, db: AsyncSession) -> list[RiderSalaryPlanVersion]:
        """全部启用版本"""
        from backend.plugin.rider_salary.enums import PlanVersionStatus

        rows = await self.select_models_order(
            db,
            'id',
            'desc',
            status=PlanVersionStatus.active.value,
            deleted=0,
        )
        return list(rows)

    async def create(self, db: AsyncSession, obj: CreatePlanVersionParam, version_no: int) -> RiderSalaryPlanVersion:
        """创建草稿版本"""
        return await self.create_model(db, obj, version_no=version_no)

    async def update(self, db: AsyncSession, pk: int, obj: UpdatePlanVersionParam) -> int:
        """更新基本信息"""
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """逻辑删除版本"""
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

    async def list_by_plan(self, db: AsyncSession, plan_id: int) -> list[RiderSalaryPlanVersion]:
        """方案下全部版本"""
        rows = await self.select_models(db, plan_id=plan_id, deleted=0)
        return list(rows)


plan_version_dao = CRUDPlanVersion(RiderSalaryPlanVersion)
