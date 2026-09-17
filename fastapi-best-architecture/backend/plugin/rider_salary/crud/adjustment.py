from decimal import Decimal

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.schema.adjustment import CreateAdjustmentParam
from backend.utils.timezone import timezone


class CRUDAdjustment(CRUDPlus[RiderSalaryAdjustment]):
    """奖惩记录数据库操作"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryAdjustment | None:
        """
        获取奖惩记录

        :param db: 数据库会话
        :param pk: 记录 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_select(
        self,
        site_id: int | None,
        rider_id: int | None,
        subject_id: int | None,
        date_from: str | None,
        date_to: str | None,
        site_ids: set[int] | None,
        pk: int | None = None,
    ) -> Select:
        """
        奖惩记录列表查询

        :param site_id: 站点 ID
        :param rider_id: 骑手 ID
        :param subject_id: 科目 ID
        :param date_from: 开始日期
        :param date_to: 结束日期
        :param site_ids: 可见站点，None 表示全部
        :param pk: 奖惩单 ID（精确）
        :return:
        """
        filters: dict = {'deleted': 0}
        if pk is not None:
            filters['id'] = pk
        if site_id is not None:
            filters['site_id'] = site_id
        if rider_id is not None:
            filters['rider_id'] = rider_id
        if subject_id is not None:
            filters['subject_id'] = subject_id
        if date_from:
            filters['biz_date__ge'] = date_from
        if date_to:
            filters['biz_date__le'] = date_to
        if site_ids is not None:
            filters['site_id__in'] = list(site_ids) or [-1]
        return await self.select_order('biz_date', 'desc', **filters)

    async def create(
        self,
        db: AsyncSession,
        obj: CreateAdjustmentParam,
        *,
        site_id: int,
        signed_amount: Decimal,
        operator_id: int,
    ) -> RiderSalaryAdjustment:
        """
        创建奖惩记录

        :param db: 数据库会话
        :param obj: 创建参数
        :param site_id: 站点 ID 快照
        :param signed_amount: 带符号金额
        :param operator_id: 操作人 ID
        :return:
        """
        return await self.create_model(
            db,
            obj,
            flush=True,
            site_id=site_id,
            signed_amount=signed_amount,
            operator_id=operator_id,
        )

    async def update(self, db: AsyncSession, pk: int, payload: dict) -> int:
        """
        更新奖惩记录

        :param db: 数据库会话
        :param pk: 记录 ID
        :param payload: 更新字段
        :return:
        """
        return await self.update_model_by_column(db, payload, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        逻辑删除奖惩记录

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


adjustment_dao: CRUDAdjustment = CRUDAdjustment(RiderSalaryAdjustment)
