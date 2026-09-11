from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.day_flag import RiderSalaryDayFlag
from backend.plugin.rider_salary.schema.day_flag import DayFlagItem


class CRUDDayFlag(CRUDPlus[RiderSalaryDayFlag]):
    """日标记数据库操作"""

    async def get_by_site_range(
        self,
        db: AsyncSession,
        site_id: int,
        date_from: date,
        date_to: date,
    ) -> list[RiderSalaryDayFlag]:
        """
        获取站点日期范围内的日标记

        :param db: 数据库会话
        :param site_id: 站点 ID
        :param date_from: 开始日期
        :param date_to: 结束日期
        :return:
        """
        rows = await self.select_models_order(
            db,
            'biz_date',
            'asc',
            site_id=site_id,
            biz_date__ge=date_from,
            biz_date__le=date_to,
            deleted=0,
        )
        return list(rows)

    async def get_by_site_date(self, db: AsyncSession, site_id: int, biz_date: date) -> RiderSalaryDayFlag | None:
        """
        获取站点某日标记

        :param db: 数据库会话
        :param site_id: 站点 ID
        :param biz_date: 业务日期
        :return:
        """
        return await self.select_model_by_column(db, site_id=site_id, biz_date=biz_date, deleted=0)

    async def create(self, db: AsyncSession, site_id: int, obj: DayFlagItem) -> RiderSalaryDayFlag:
        """
        创建日标记

        :param db: 数据库会话
        :param site_id: 站点 ID
        :param obj: 日标记
        :return:
        """
        return await self.create_model(db, obj, flush=True, site_id=site_id)

    async def update(self, db: AsyncSession, pk: int, obj: DayFlagItem) -> int:
        """
        更新日标记

        :param db: 数据库会话
        :param pk: 日标记 ID
        :param obj: 日标记
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)


day_flag_dao: CRUDDayFlag = CRUDDayFlag(RiderSalaryDayFlag)
