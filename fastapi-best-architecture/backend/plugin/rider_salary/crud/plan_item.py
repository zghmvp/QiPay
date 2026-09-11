from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.plan_item import RiderSalaryPlanItem
from backend.plugin.rider_salary.schema.plan_item import PlanItemParam
from backend.utils.timezone import timezone


class CRUDPlanItem(CRUDPlus[RiderSalaryPlanItem]):
    """方案项 CRUD"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryPlanItem | None:
        """按主键获取方案项"""
        return await self.select_model(db, pk, deleted=0)

    async def list_by_version(self, db: AsyncSession, plan_version_id: int) -> list[RiderSalaryPlanItem]:
        """版本下全部方案项"""
        rows = await self.select_models_order(
            db,
            'sort_order',
            'asc',
            plan_version_id=plan_version_id,
            deleted=0,
        )
        return list(rows)

    async def create(self, db: AsyncSession, plan_version_id: int, obj: PlanItemParam, **kwargs) -> RiderSalaryPlanItem:
        """创建方案项"""
        return await self.create_model(db, obj, plan_version_id=plan_version_id, **kwargs)

    async def logical_delete_by_version(self, db: AsyncSession, plan_version_id: int) -> None:
        """逻辑删除版本下全部方案项"""
        stmt = (
            update(RiderSalaryPlanItem)
            .where(
                RiderSalaryPlanItem.plan_version_id == plan_version_id,
                RiderSalaryPlanItem.deleted == 0,
            )
            .values(deleted=RiderSalaryPlanItem.id, deleted_time=timezone.now())
        )
        await db.execute(stmt)


plan_item_dao = CRUDPlanItem(RiderSalaryPlanItem)
