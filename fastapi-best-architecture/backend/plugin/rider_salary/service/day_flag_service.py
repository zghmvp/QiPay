from calendar import monthrange
from datetime import date

from fastapi import Request
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.day_flag import day_flag_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.enums import PayrollStatus
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.schema.day_flag import DayFlagItem, GetDayFlagDetail, UpsertDayFlagParam
from backend.plugin.rider_salary.service.audit_service import audit_service, snapshot
from backend.plugin.rider_salary.utils.db_errors import client_error_from_integrity
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.lock_check import site_locked_dates
from backend.plugin.rider_salary.utils.recalc import mark_stale

_LOCK_MSG = '该日期所属结算周期已锁账，禁止修改，请走反冲补发流程'
_DAY_FLAG_FIELDS = ('id', 'site_id', 'biz_date', 'bad_weather', 'high_temp', 'promo', 'remark')


def _day_flag_written(row: object, site_id: int, item: DayFlagItem) -> dict:
    """用本次提交的标记覆盖快照，避免更新语句没有回填内存对象。"""
    data = snapshot(row, _DAY_FLAG_FIELDS)
    data.update({
        'site_id': site_id,
        'biz_date': item.biz_date.isoformat(),
        'bad_weather': item.bad_weather,
        'high_temp': item.high_temp,
        'promo': item.promo,
        'remark': item.remark,
    })
    return data


async def rider_ids_for_day_flag_recalc(
    db: AsyncSession,
    *,
    site_id: int,
    dates: list[date],
) -> list[int]:
    """
    推导日标记变更后需要重算的骑手

    包含这些日期上有订单的骑手，以及草稿薪资单所属周期覆盖这些日期的骑手。
    不限于在职：离职但当日仍有订单或草稿的骑手一并纳入。
    """
    unique_dates = sorted(set(dates))
    if not unique_dates:
        return []
    order_ids = (
        await db.scalars(
            select(RiderSalaryOrder.rider_id)
            .where(
                RiderSalaryOrder.site_id == site_id,
                RiderSalaryOrder.biz_date.in_(unique_dates),
                RiderSalaryOrder.deleted == 0,
                RiderSalaryOrder.rider_id > 0,
            )
            .distinct()
        )
    ).all()
    covered = or_(*[
        and_(
            RiderSalarySettlePeriod.start_date <= biz_date,
            RiderSalarySettlePeriod.end_date >= biz_date,
        )
        for biz_date in unique_dates
    ])
    draft_ids = (
        await db.scalars(
            select(RiderSalaryPayroll.rider_id)
            .join(
                RiderSalarySettlePeriod,
                RiderSalaryPayroll.period_id == RiderSalarySettlePeriod.id,
            )
            .where(
                RiderSalarySettlePeriod.site_id == site_id,
                RiderSalarySettlePeriod.deleted == 0,
                covered,
                RiderSalaryPayroll.status == PayrollStatus.draft,
                RiderSalaryPayroll.deleted == 0,
                RiderSalaryPayroll.rider_id > 0,
            )
            .distinct()
        )
    ).all()
    return sorted({int(rider_id) for rider_id in (*order_ids, *draft_ids)})


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
        locked_dates = await site_locked_dates(db, site_id=site_id, date_from=date_from, date_to=date_to)
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
        locked_dates = await site_locked_dates(db, site_id=obj.site_id, date_from=min(dates), date_to=max(dates))
        if any(item.biz_date in locked_dates for item in obj.days):
            raise errors.ForbiddenError(msg=_LOCK_MSG)
        before_days: list[dict] = []
        after_days: list[dict] = []
        for item in obj.days:
            existed = await day_flag_dao.get_by_site_date(db, obj.site_id, item.biz_date)
            if existed:
                before_days.append(snapshot(existed, _DAY_FLAG_FIELDS))
                await day_flag_dao.update(db, existed.id, item)
                after_days.append(_day_flag_written(existed, obj.site_id, item))
            else:
                before_days.append({'biz_date': item.biz_date.isoformat(), 'exists': False})
                try:
                    created = await day_flag_dao.create(db, obj.site_id, item)
                except IntegrityError as exc:
                    raise client_error_from_integrity(exc) from exc
                after_days.append(_day_flag_written(created, obj.site_id, item))
        rider_ids = await rider_ids_for_day_flag_recalc(db, site_id=obj.site_id, dates=dates)
        await mark_stale(db, rider_ids=rider_ids, date_from=min(dates), date_to=max(dates))
        await audit_service.record(
            db,
            request,
            module='日标记',
            action='更新日标记',
            target_type='day_flag',
            target_id=obj.site_id,
            target_label=f'站点 {obj.site_id}',
            before={'count': len(before_days), 'days': before_days},
            after={'count': len(after_days), 'days': after_days},
        )


day_flag_service: DayFlagService = DayFlagService()
