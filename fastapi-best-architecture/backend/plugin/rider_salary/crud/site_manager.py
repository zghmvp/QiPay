from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.site_manager import RiderSalarySiteManager
from backend.plugin.rider_salary.schema.site import SiteManagerItem
from backend.utils.timezone import timezone


class CRUDSiteManager(CRUDPlus[RiderSalarySiteManager]):
    """站点负责人数据库操作"""

    async def get_by_site(self, db: AsyncSession, site_id: int) -> Sequence[RiderSalarySiteManager]:
        """
        获取站点全部负责人

        :param db: 数据库会话
        :param site_id: 站点 ID
        :return:
        """
        return await self.select_models_order(db, 'id', 'asc', site_id=site_id, deleted=0)

    async def create(self, db: AsyncSession, site_id: int, obj: SiteManagerItem) -> RiderSalarySiteManager:
        """
        创建站点负责人

        :param db: 数据库会话
        :param site_id: 站点 ID
        :param obj: 负责人项
        :return:
        """
        return await self.create_model(db, obj, flush=True, site_id=site_id)

    async def delete_by_site(self, db: AsyncSession, site_id: int) -> int:
        """
        逻辑删除站点全部负责人

        :param db: 数据库会话
        :param site_id: 站点 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            allow_multiple=True,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now,
            site_id=site_id,
            deleted=0,
        )


site_manager_dao: CRUDSiteManager = CRUDSiteManager(RiderSalarySiteManager)
