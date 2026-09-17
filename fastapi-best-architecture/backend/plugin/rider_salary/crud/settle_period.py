from calendar import monthrange
from datetime import date

from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.utils.timezone import timezone

SITE_LEVEL_RIDER_ID = 0


class CRUDSettlePeriod(CRUDPlus[RiderSalarySettlePeriod]):
    """结算周期 CRUD"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalarySettlePeriod | None:
        """
        按主键获取周期

        :param db: 数据库会话
        :param pk: 周期 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_unique(
        self,
        db: AsyncSession,
        *,
        site_id: int,
        rider_id: int,
        start_date: date,
    ) -> RiderSalarySettlePeriod | None:
        """
        按唯一键获取周期

        :param db: 数据库会话
        :param site_id: 站点 ID
        :param rider_id: 骑手 ID，0 为站点级
        :param start_date: 开始日期
        :return:
        """
        return await db.scalar(
            select(RiderSalarySettlePeriod)
            .where(
                RiderSalarySettlePeriod.site_id == site_id,
                RiderSalarySettlePeriod.rider_id == rider_id,
                RiderSalarySettlePeriod.start_date == start_date,
                RiderSalarySettlePeriod.deleted == 0,
            )
            .limit(1)
        )

    async def get_covering(
        self,
        db: AsyncSession,
        *,
        site_id: int,
        rider_id: int,
        any_date: date,
    ) -> RiderSalarySettlePeriod | None:
        """
        获取覆盖指定日期的周期

        :param db: 数据库会话
        :param site_id: 站点 ID
        :param rider_id: 骑手 ID，0 为站点级
        :param any_date: 周期内任意日期
        :return:
        """
        return await db.scalar(
            select(RiderSalarySettlePeriod)
            .where(
                RiderSalarySettlePeriod.site_id == site_id,
                RiderSalarySettlePeriod.rider_id == rider_id,
                RiderSalarySettlePeriod.start_date <= any_date,
                RiderSalarySettlePeriod.end_date >= any_date,
                RiderSalarySettlePeriod.deleted == 0,
            )
            .order_by(RiderSalarySettlePeriod.start_date.desc())
            .limit(1)
        )

    async def get_select(
        self,
        *,
        site_id: int | None,
        rider_id: int | None,
        status: str | None,
        month_start: date | None,
        month_end: date | None,
        site_ids: set[int] | None,
        stale: bool | None = None,
    ) -> Select:
        """
        周期列表查询

        :param site_id: 站点 ID
        :param rider_id: 骑手 ID
        :param status: 状态
        :param month_start: 筛选月份起始
        :param month_end: 筛选月份结束
        :param site_ids: 可见站点，None 表示全部
        :param stale: 仅含需重算薪资单的周期
        :return:
        """
        filters: dict = {'deleted': 0}
        if site_id is not None:
            filters['site_id'] = site_id
        if rider_id is not None:
            filters['rider_id'] = rider_id
        if status:
            filters['status'] = status
        if site_ids is not None:
            filters['site_id__in'] = list(site_ids) or [-1]
        stmt = await self.select_order('start_date', 'desc', **filters)
        if month_start is not None and month_end is not None:
            stmt = stmt.where(
                RiderSalarySettlePeriod.start_date <= month_end,
                RiderSalarySettlePeriod.end_date >= month_start,
            )
        if stale:
            stmt = stmt.where(
                exists(
                    select(1).where(
                        RiderSalaryPayroll.period_id == RiderSalarySettlePeriod.id,
                        RiderSalaryPayroll.stale.is_(True),
                        RiderSalaryPayroll.deleted == 0,
                    )
                )
            )
        return stmt

    async def create(
        self,
        db: AsyncSession,
        *,
        site_id: int,
        rider_id: int,
        cycle_type: str,
        start_date: date,
        end_date: date,
        remark: str | None = None,
    ) -> RiderSalarySettlePeriod:
        """
        创建周期

        :param db: 数据库会话
        :param site_id: 站点 ID
        :param rider_id: 骑手 ID
        :param cycle_type: 周期类型
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param remark: 备注
        :return:
        """
        period = RiderSalarySettlePeriod(
            site_id=site_id,
            cycle_type=cycle_type,
            start_date=start_date,
            end_date=end_date,
            rider_id=rider_id,
            remark=remark,
        )
        db.add(period)
        await db.flush()
        return period

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        逻辑删除周期

        :param db: 数据库会话
        :param pk: 周期 ID
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


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """
    自然月起止

    :param year: 年
    :param month: 月
    :return:
    """
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


settle_period_dao: CRUDSettlePeriod = CRUDSettlePeriod(RiderSalarySettlePeriod)
