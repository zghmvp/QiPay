from datetime import date, datetime, timedelta

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.enums import AdvanceStatus
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.schema.advance import CreateMeAdvanceParam
from backend.plugin.rider_salary.utils.advance_quota import QUOTA_CONSUMING_STATUSES
from backend.utils.timezone import timezone

_IN_FLIGHT = (AdvanceStatus.pending.value, AdvanceStatus.to_pay.value)


class CRUDAdvance(CRUDPlus[RiderSalaryAdvance]):
    """预支单数据库操作"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryAdvance | None:
        """
        获取预支单

        :param db: 数据库会话
        :param pk: 预支单 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_select(
        self,
        *,
        site_id: int | None,
        rider_id: int | None,
        status: str | None,
        date_from: date | None,
        date_to: date | None,
        site_ids: set[int] | None,
    ) -> Select:
        """
        预支列表查询

        :param site_id: 站点 ID
        :param rider_id: 骑手 ID
        :param status: 状态
        :param date_from: 申请日起
        :param date_to: 申请日止
        :param site_ids: 可见站点，None 表示全部
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
        if date_from is not None:
            filters['submit_time__ge'] = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.tz_info)
        if date_to is not None:
            next_day = date_to + timedelta(days=1)
            filters['submit_time__lt'] = datetime.combine(next_day, datetime.min.time(), tzinfo=timezone.tz_info)
        return await self.select_order('id', 'desc', **filters)

    async def list_in_flight(self, db: AsyncSession, rider_id: int) -> list[RiderSalaryAdvance]:
        """
        骑手在途预支（待审核 / 待发放）

        :param db: 数据库会话
        :param rider_id: 骑手 ID
        :return:
        """
        rows = await db.scalars(
            select(RiderSalaryAdvance).where(
                RiderSalaryAdvance.rider_id == rider_id,
                RiderSalaryAdvance.status.in_(_IN_FLIGHT),
                RiderSalaryAdvance.deleted == 0,
            )
        )
        return list(rows.all())

    async def list_quota_consuming_in_month(
        self,
        db: AsyncSession,
        rider_id: int,
        start: datetime,
        end: datetime,
    ) -> list[RiderSalaryAdvance]:
        """
        骑手当月占用次数的预支单（pending / to_pay / paid）

        :param db: 数据库会话
        :param rider_id: 骑手 ID
        :param start: 自然月起（含）
        :param end: 自然月止（不含）
        :return:
        """
        rows = await db.scalars(
            select(RiderSalaryAdvance).where(
                RiderSalaryAdvance.rider_id == rider_id,
                RiderSalaryAdvance.status.in_(tuple(QUOTA_CONSUMING_STATUSES)),
                RiderSalaryAdvance.deleted == 0,
                RiderSalaryAdvance.submit_time >= start,
                RiderSalaryAdvance.submit_time < end,
            )
        )
        return list(rows.all())

    async def list_by_rider(self, db: AsyncSession, rider_id: int) -> list[RiderSalaryAdvance]:
        """
        骑手全部预支记录

        :param db: 数据库会话
        :param rider_id: 骑手 ID
        :return:
        """
        rows = await self.select_models_order(db, 'id', 'desc', rider_id=rider_id, deleted=0)
        return list(rows)

    async def create(
        self,
        db: AsyncSession,
        obj: CreateMeAdvanceParam,
        *,
        rider_id: int,
        site_id: int,
    ) -> RiderSalaryAdvance:
        """
        创建预支单（直接 pending）

        :param db: 数据库会话
        :param obj: 创建参数
        :param rider_id: 骑手 ID
        :param site_id: 站点 ID
        :return:
        """
        return await self.create_model(
            db,
            obj,
            flush=True,
            rider_id=rider_id,
            site_id=site_id,
            status=AdvanceStatus.pending.value,
            submit_time=timezone.now(),
        )

    async def list_all(
        self,
        db: AsyncSession,
        *,
        site_id: int | None,
        status: str | None,
        date_from: date | None,
        date_to: date | None,
        site_ids: set[int] | None,
    ) -> list[RiderSalaryAdvance]:
        """
        导出用全量列表

        :param db: 数据库会话
        :param site_id: 站点 ID
        :param status: 状态
        :param date_from: 申请日起
        :param date_to: 申请日止
        :param site_ids: 可见站点
        :return:
        """
        stmt = await self.get_select(
            site_id=site_id,
            rider_id=None,
            status=status,
            date_from=date_from,
            date_to=date_to,
            site_ids=site_ids,
        )
        rows = await db.scalars(stmt)
        return list(rows.all())


advance_dao: CRUDAdvance = CRUDAdvance(RiderSalaryAdvance)
