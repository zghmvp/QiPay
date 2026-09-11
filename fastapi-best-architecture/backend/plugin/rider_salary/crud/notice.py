from collections.abc import Sequence

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.notice import RiderSalaryNotice
from backend.plugin.rider_salary.schema.notice import CreateNoticeParam, UpdateNoticeParam
from backend.utils.timezone import timezone


class CRUDNotice(CRUDPlus[RiderSalaryNotice]):
    """站点公告数据库操作"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryNotice | None:
        """
        获取公告

        :param db: 数据库会话
        :param pk: 公告 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_select(
        self,
        title: str | None,
        status: str | None,
        site_id: int | None,
        site_ids: set[int] | None,
    ) -> Select:
        """
        公告列表查询

        :param title: 标题
        :param status: 状态
        :param site_id: 站点 ID
        :param site_ids: 可见站点，None 表示全部
        :return:
        """
        filters: dict = {'deleted': 0}
        if title:
            filters['title__like'] = f'%{title}%'
        if status:
            filters['status'] = status
        if site_id is not None:
            filters['site_id'] = site_id
        elif site_ids is not None:
            filters['site_id__in'] = list(site_ids) or [-1]
        return await self.select_order('created_time', 'desc', **filters)

    async def get_all(self, db: AsyncSession) -> Sequence[RiderSalaryNotice]:
        """
        获取全部公告

        :param db: 数据库会话
        :return:
        """
        return await self.select_models(db, deleted=0)

    async def create(self, db: AsyncSession, obj: CreateNoticeParam, *, publisher_id: int) -> RiderSalaryNotice:
        """
        创建公告

        :param db: 数据库会话
        :param obj: 创建参数
        :param publisher_id: 发布人 ID
        :return:
        """
        return await self.create_model(db, obj, flush=True, publisher_id=publisher_id)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateNoticeParam | dict) -> int:
        """
        更新公告

        :param db: 数据库会话
        :param pk: 公告 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        逻辑删除公告

        :param db: 数据库会话
        :param pk: 公告 ID
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


notice_dao: CRUDNotice = CRUDNotice(RiderSalaryNotice)
