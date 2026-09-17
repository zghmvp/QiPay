from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.enums import EnableStatus
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.plan_item import RiderSalaryPlanItem
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.schema.subject import CreateSubjectParam, UpdateSubjectParam
from backend.utils.timezone import timezone


class CRUDSubject(CRUDPlus[RiderSalarySubject]):
    """科目数据库操作"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalarySubject | None:
        """
        获取科目

        :param db: 数据库会话
        :param pk: 科目 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_code(self, db: AsyncSession, code: str) -> RiderSalarySubject | None:
        """
        按编码获取科目

        :param db: 数据库会话
        :param code: 科目编码
        :return:
        """
        return await self.select_model_by_column(db, code=code, deleted=0)

    async def get_select(self, name: str | None, status: str | None, direction: str | None) -> Select:
        """
        科目列表查询

        :param name: 科目名称
        :param status: 状态
        :param direction: 方向
        :return:
        """
        filters: dict = {'deleted': 0}
        if name:
            filters['name__like'] = f'%{name}%'
        if status:
            filters['status'] = status
        if direction:
            filters['direction'] = direction
        return await self.select_order('sort_order', 'asc', **filters)

    async def get_all(self, db: AsyncSession) -> Sequence[RiderSalarySubject]:
        """
        获取启用科目（新建方案/奖惩下拉，不含已下线天气科目）

        :param db: 数据库会话
        :return:
        """
        return await self.select_models_order(db, 'sort_order', 'asc', deleted=0, status=EnableStatus.enable.value)

    async def count_refs(self, db: AsyncSession, subject_id: int) -> tuple[int, int]:
        """
        统计科目被奖惩与方案项引用数

        :param db: 数据库会话
        :param subject_id: 科目 ID
        :return:
        """
        adj_count = await db.scalar(
            select(func.count())
            .select_from(RiderSalaryAdjustment)
            .where(
                RiderSalaryAdjustment.subject_id == subject_id,
                RiderSalaryAdjustment.deleted == 0,
            )
        )
        item_count = await db.scalar(
            select(func.count())
            .select_from(RiderSalaryPlanItem)
            .where(
                RiderSalaryPlanItem.subject_id == subject_id,
                RiderSalaryPlanItem.deleted == 0,
            )
        )
        return int(adj_count or 0), int(item_count or 0)

    async def create(self, db: AsyncSession, obj: CreateSubjectParam) -> RiderSalarySubject:
        """
        创建科目

        :param db: 数据库会话
        :param obj: 创建参数
        :return:
        """
        return await self.create_model(db, obj, flush=True)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateSubjectParam | dict) -> int:
        """
        更新科目

        :param db: 数据库会话
        :param pk: 科目 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        逻辑删除科目

        :param db: 数据库会话
        :param pk: 科目 ID
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


subject_dao: CRUDSubject = CRUDSubject(RiderSalarySubject)
