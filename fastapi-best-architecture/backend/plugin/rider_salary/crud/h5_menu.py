from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.h5_menu import RiderSalaryH5Menu


class CRUDH5Menu(CRUDPlus[RiderSalaryH5Menu]):
    """骑手端菜单开关数据库操作"""

    async def get_by_site(self, db: AsyncSession, site_id: int) -> RiderSalaryH5Menu | None:
        """按站点读取未删除开关，site_id 为 0 表示全局。"""
        return await self.select_model_by_column(db, site_id=site_id, deleted=0)


h5_menu_dao: CRUDH5Menu = CRUDH5Menu(RiderSalaryH5Menu)
