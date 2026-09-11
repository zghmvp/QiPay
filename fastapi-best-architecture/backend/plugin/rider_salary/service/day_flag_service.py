from calendar import monthrange
from datetime import date

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.day_flag import day_flag_dao
from backend.plugin.rider_salary.crud.rider import rider_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.schema.day_flag import GetDayFlagDetail, UpsertDayFlagParam
from backend.plugin.rider_salary.service.audit_service import audit_service
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.lock_check import assert_not_locked, locked_dates_in_range
from backend.plugin.rider_salary.utils.recalc import mark_stale


class DayFlagService:
    """日标记服务"""

    @staticmethod
    async def get_month(*, db: AsyncSession, request: Request, site_id: int, month: str) -> list[GetDayFlagDetail]:
        """
        获取站点当月每日标记

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID
        :param month: 月份 YYYY-MM
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, site_id)
        if not await site_dao.get(db, site_id):
            raise errors.NotFoundError(msg='站点不存在')
        try:
            year_s, month_s = month.split('-')
            year, month_n = int(year_s), int(month_s)
            date_from = date(year, month_n, 1)
            date_to = date(year, month_n, monthrange(year, month_n)[1])
        except (TypeError, ValueError):
            raise errors.RequestError(msg='月份格式应为 YYYY-MM')
        rows = await day_flag_dao.get_by_site_range(db, site_id, date_from, date_to)
        by_date = {row.biz_date: row for row in rows}
        locked_dates = await locked_dates_in_range(
            db, site_id=site_id, rider_id=None, date_from=date_from, date_to=date_to
        )
        result: list[GetDayFlagDetail] = []
        current = date_from
        while current <= date_to:
            row = by_date.get(current)
            locked = current in locked_dates
            if row:
                detail = GetDayFlagDetail.model_validate(row)
                result.append(detail.model_copy(update={'is_locked': locked}))
            else:
                result.append(
                    GetDayFlagDetail(
                        id=None,
                        site_id=site_id,
                        biz_date=current,
                        bad_weather=False,
                        high_temp=False,
                        promo=False,
                        remark=None,
                        is_locked=locked,
                    )
                )
            current = date.fromordinal(current.toordinal() + 1)
        return result

    @staticmethod
    async def upsert(*, db: AsyncSession, request: Request, obj: UpsertDayFlagParam) -> None:
        """
        批量 upsert 日标记

        :param db: 数据库会话
        :param request: 请求对象
        :param obj: 更新参数
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, obj.site_id)
        if not await site_dao.get(db, obj.site_id):
            raise errors.NotFoundError(msg='站点不存在')
        if not obj.days:
            raise errors.RequestError(msg='日标记列表不能为空')
        dates = [item.biz_date for item in obj.days]
        for item in obj.days:
            await assert_not_locked(db, site_id=obj.site_id, rider_id=None, biz_date=item.biz_date)
            existed = await day_flag_dao.get_by_site_date(db, obj.site_id, item.biz_date)
            if existed:
                await day_flag_dao.update(db, existed.id, item)
            else:
                await day_flag_dao.create(db, obj.site_id, item)
        rider_ids = list(await rider_dao.get_on_job_ids_by_site(db, obj.site_id))
        await mark_stale(db, rider_ids=rider_ids, date_from=min(dates), date_to=max(dates))
        await audit_service.record(
            db,
            request,
            module='日标记',
            action='更新日标记',
            target_type='day_flag',
            target_id=obj.site_id,
            target_label=f'站点 {obj.site_id}',
            after={'days': [item.biz_date.isoformat() for item in obj.days]},
        )


day_flag_service: DayFlagService = DayFlagService()
