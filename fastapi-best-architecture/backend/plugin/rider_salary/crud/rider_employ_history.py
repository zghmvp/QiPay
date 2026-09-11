from collections.abc import Sequence
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.rider_employ_history import RiderSalaryRiderEmployHistory
from backend.plugin.rider_salary.schema.rider import CreateEmployHistoryParam, UpdateEmployHistoryParam
from backend.utils.timezone import timezone


class CRUDRiderEmployHistory(CRUDPlus[RiderSalaryRiderEmployHistory]):
    """用工类型历史数据库操作"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryRiderEmployHistory | None:
        """
        获取用工类型历史

        :param db: 数据库会话
        :param pk: 记录 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_rider(self, db: AsyncSession, rider_id: int) -> Sequence[RiderSalaryRiderEmployHistory]:
        """
        获取骑手全部用工类型历史

        :param db: 数据库会话
        :param rider_id: 骑手 ID
        :return:
        """
        return await self.select_models_order(db, 'start_date', 'asc', rider_id=rider_id, deleted=0)

    async def create(
        self,
        db: AsyncSession,
        rider_id: int,
        obj: CreateEmployHistoryParam,
    ) -> RiderSalaryRiderEmployHistory:
        """
        创建用工类型历史

        :param db: 数据库会话
        :param rider_id: 骑手 ID
        :param obj: 创建参数
        :return:
        """
        return await self.create_model(db, obj, flush=True, rider_id=rider_id)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateEmployHistoryParam) -> int:
        """
        更新用工类型历史

        :param db: 数据库会话
        :param pk: 记录 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def close_open(self, db: AsyncSession, rider_id: int, end_date: date) -> int:
        """
        关闭仍在生效的用工类型历史

        :param db: 数据库会话
        :param rider_id: 骑手 ID
        :param end_date: 结束日期
        :return:
        """
        return await self.update_model_by_column(
            db,
            {'end_date': end_date},
            allow_multiple=True,
            rider_id=rider_id,
            end_date=None,
            deleted=0,
        )

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        逻辑删除用工类型历史

        :param db: 数据库会话
        :param pk: 记录 ID
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


rider_employ_history_dao: CRUDRiderEmployHistory = CRUDRiderEmployHistory(RiderSalaryRiderEmployHistory)
