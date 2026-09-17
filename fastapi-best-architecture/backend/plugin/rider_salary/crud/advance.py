from collections.abc import Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.enums import AdvanceStatus
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.schema.advance import CreateMeAdvanceParam
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
        pk: int | None = None,
    ) -> Select:
        """
        预支列表查询

        :param site_id: 站点 ID
        :param rider_id: 骑手 ID
        :param status: 状态
        :param date_from: 申请日起
        :param date_to: 申请日止
        :param site_ids: 可见站点，None 表示全部
        :param pk: 预支单 ID（精确）
        :return:
        """
        filters: dict = {'deleted': 0}
        if pk is not None:
            filters['id'] = pk
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

    async def count_monthly_consumed(
        self,
        db: AsyncSession,
        *,
        rider_id: int,
        site_id: int,
        month_start: datetime,
        month_end: datetime,
        statuses: Sequence[str],
    ) -> int:
        """
        骑手在某站点自然月内占用次数的预支单数量

        :param db: 数据库会话
        :param rider_id: 骑手 ID
        :param site_id: 站点 ID
        :param month_start: 自然月起（含）
        :param month_end: 自然月止（不含）
        :param statuses: 占用次数的状态
        :return:
        """
        result = await db.scalar(
            select(func.count())
            .select_from(RiderSalaryAdvance)
            .where(
                RiderSalaryAdvance.rider_id == rider_id,
                RiderSalaryAdvance.site_id == site_id,
                RiderSalaryAdvance.status.in_(list(statuses)),
                RiderSalaryAdvance.submit_time >= month_start,
                RiderSalaryAdvance.submit_time < month_end,
                RiderSalaryAdvance.deleted == 0,
            )
        )
        return int(result or 0)

    async def count_monthly_consumed_grouped(
        self,
        db: AsyncSession,
        *,
        rider_site_ids: set[tuple[int, int]],
        month_start: datetime,
        month_end: datetime,
        statuses: Sequence[str],
    ) -> dict[tuple[int, int], int]:
        """
        批量统计骑手×站点在自然月内占用的次数

        :param db: 数据库会话
        :param rider_site_ids: (骑手 ID, 站点 ID) 集合
        :param month_start: 自然月起（含）
        :param month_end: 自然月止（不含）
        :param statuses: 占用次数的状态
        :return:
        """
        if not rider_site_ids:
            return {}
        rider_ids = {rider_id for rider_id, _site_id in rider_site_ids}
        site_ids = {site_id for _rider_id, site_id in rider_site_ids}
        rows = await db.execute(
            select(
                RiderSalaryAdvance.rider_id,
                RiderSalaryAdvance.site_id,
                func.count(),
            )
            .where(
                RiderSalaryAdvance.rider_id.in_(list(rider_ids)),
                RiderSalaryAdvance.site_id.in_(list(site_ids)),
                RiderSalaryAdvance.status.in_(list(statuses)),
                RiderSalaryAdvance.submit_time >= month_start,
                RiderSalaryAdvance.submit_time < month_end,
                RiderSalaryAdvance.deleted == 0,
            )
            .group_by(RiderSalaryAdvance.rider_id, RiderSalaryAdvance.site_id)
        )
        result: dict[tuple[int, int], int] = {}
        for rider_id, site_id, count in rows.all():
            key = (int(rider_id), int(site_id))
            if key in rider_site_ids:
                result[key] = int(count)
        return result

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
