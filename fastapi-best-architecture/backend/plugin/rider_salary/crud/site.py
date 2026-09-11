from collections.abc import Sequence

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.schema.site import CreateSiteParam, UpdateSiteParam
from backend.utils.timezone import timezone


class CRUDSite(CRUDPlus[RiderSalarySite]):
    """站点数据库操作"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalarySite | None:
        """
        获取站点

        :param db: 数据库会话
        :param pk: 站点 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_code(self, db: AsyncSession, code: str) -> RiderSalarySite | None:
        """
        按编码获取站点

        :param db: 数据库会话
        :param code: 站点编码
        :return:
        """
        return await self.select_model_by_column(db, code=code, deleted=0)

    async def get_select(
        self,
        name: str | None,
        code: str | None,
        status: str | None,
        site_ids: set[int] | None,
    ) -> Select:
        """
        站点列表查询

        :param name: 站点名称
        :param code: 站点编码
        :param status: 状态
        :param site_ids: 可见站点，None 表示全部
        :return:
        """
        filters: dict = {'deleted': 0}
        if name:
            filters['name__like'] = f'%{name}%'
        if code:
            filters['code__like'] = f'%{code}%'
        if status:
            filters['status'] = status
        if site_ids is not None:
            filters['id__in'] = list(site_ids) or [-1]
        return await self.select_order('id', 'desc', **filters)

    async def get_all(self, db: AsyncSession, site_ids: set[int] | None) -> Sequence[RiderSalarySite]:
        """
        获取全部可见站点

        :param db: 数据库会话
        :param site_ids: 可见站点，None 表示全部
        :return:
        """
        filters: dict = {'deleted': 0}
        if site_ids is not None:
            filters['id__in'] = list(site_ids) or [-1]
        return await self.select_models_order(db, 'id', 'asc', **filters)

    async def create(self, db: AsyncSession, obj: CreateSiteParam) -> RiderSalarySite:
        """
        创建站点

        :param db: 数据库会话
        :param obj: 创建参数
        :return:
        """
        return await self.create_model(db, obj, flush=True)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateSiteParam) -> int:
        """
        更新站点

        :param db: 数据库会话
        :param pk: 站点 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        逻辑删除站点

        :param db: 数据库会话
        :param pk: 站点 ID
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


site_dao: CRUDSite = CRUDSite(RiderSalarySite)
