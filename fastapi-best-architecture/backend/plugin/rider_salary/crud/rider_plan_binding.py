from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.rider_plan_binding import RiderSalaryRiderPlanBinding
from backend.plugin.rider_salary.schema.rider import CreatePlanBindingParam, UpdatePlanBindingParam
from backend.utils.timezone import timezone


class CRUDRiderPlanBinding(CRUDPlus[RiderSalaryRiderPlanBinding]):
    """方案绑定数据库操作"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryRiderPlanBinding | None:
        """
        获取方案绑定

        :param db: 数据库会话
        :param pk: 绑定 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_rider(self, db: AsyncSession, rider_id: int) -> Sequence[RiderSalaryRiderPlanBinding]:
        """
        获取骑手全部方案绑定

        :param db: 数据库会话
        :param rider_id: 骑手 ID
        :return:
        """
        return await self.select_models_order(db, 'start_date', 'asc', rider_id=rider_id, deleted=0)

    async def create(
        self,
        db: AsyncSession,
        rider_id: int,
        obj: CreatePlanBindingParam,
    ) -> RiderSalaryRiderPlanBinding:
        """
        创建方案绑定

        :param db: 数据库会话
        :param rider_id: 骑手 ID
        :param obj: 创建参数
        :return:
        """
        return await self.create_model(db, obj, flush=True, rider_id=rider_id)

    async def update(self, db: AsyncSession, pk: int, obj: UpdatePlanBindingParam) -> int:
        """
        更新方案绑定

        :param db: 数据库会话
        :param pk: 绑定 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        逻辑删除方案绑定

        :param db: 数据库会话
        :param pk: 绑定 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now,
            id=pk,
            deleted=0,
        )


rider_plan_binding_dao: CRUDRiderPlanBinding = CRUDRiderPlanBinding(RiderSalaryRiderPlanBinding)
