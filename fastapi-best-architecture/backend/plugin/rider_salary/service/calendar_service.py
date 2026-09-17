from calendar import monthrange
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from chinese_calendar import is_holiday
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.payroll_daily import payroll_daily_dao
from backend.plugin.rider_salary.crud.plan import plan_dao
from backend.plugin.rider_salary.crud.plan_version import plan_version_dao
from backend.plugin.rider_salary.crud.rider import rider_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.engine.context import iter_dates
from backend.plugin.rider_salary.enums import (
    CalcStage,
    DayStatus,
    DetailSource,
    OrderStatus,
    PayrollKind,
    PayrollStatus,
    PeriodStatus,
    SubjectDirection,
)
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.import_batch import RiderSalaryImportBatch
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.schema.calendar import (
    CalendarAdjustmentItem,
    CalendarDailyItem,
    CalendarDayItem,
    CalendarDayOrder,
    CalendarDayTotals,
    CalendarHitDetail,
    CalendarMonthSummary,
    CalendarPeriodChip,
    CalendarPeriodInfo,
    CalendarPlanBand,
    CalendarPlanInfo,
    GetCalendarDayDetail,
    GetCalendarMonth,
)
from backend.plugin.rider_salary.service.rider_service import Segment, resolve_effective_plans
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.periods import compute_period_range
from backend.utils.timezone import timezone

ZERO = Decimal('0.00')
_SITE_LEVEL = 0
_LOCKED = {PeriodStatus.locked.value, PeriodStatus.paid.value}
_PAYROLL_OK = {PayrollStatus.draft.value, PayrollStatus.finalized.value, PayrollStatus.paid.value}


def parse_month(month: str | None, today: date | None = None) -> tuple[str, date, date]:
    """解析 YYYY-MM，缺省为当月"""
    if not month:
        base = today or timezone.now().date()
        month = f'{base.year:04d}-{base.month:02d}'
    try:
        year_s, mon_s = month.split('-')
        year, mon = int(year_s), int(mon_s)
        start = date(year, mon, 1)
    except (TypeError, ValueError):
        raise errors.RequestError(msg='月份格式须为 YYYY-MM')
    end = date(year, mon, monthrange(year, mon)[1])
    return f'{year:04d}-{mon:02d}', start, end


def period_range_text(start: date, end: date) -> str:
    """周期区间展示"""
    if start.year == end.year:
        return f'{start:%m-%d}~{end:%m-%d}'
    return f'{start.isoformat()}~{end.isoformat()}'


def resolve_day_status(*, has_plan: bool, order_count: int, valid_order_count: int, imported: bool) -> str:
    """日状态四态：无方案优先于有数据"""
    if not has_plan and valid_order_count > 0:
        return DayStatus.no_plan.value
    if order_count > 0:
        return DayStatus.has_data.value
    if imported:
        return DayStatus.no_orders.value
    return DayStatus.not_imported.value


def summarize_subjects(names: Sequence[str], *, limit: int = 3) -> list[str]:
    """去重科目名，超出 limit 时追加「等N项」"""
    seen: list[str] = []
    for name in names:
        text = (name or '').strip()
        if text and text not in seen:
            seen.append(text)
    if len(seen) <= limit:
        return seen
    extra = len(seen) - limit
    return [*seen[:limit], f'等{extra}项']


def clip_plan_bands(
    segments: Sequence[Segment],
    month_start: date,
    month_end: date,
    meta: dict[int, tuple[str | None, str | None]],
) -> list[CalendarPlanBand]:
    """
    将生效段裁剪到月边界；无方案段不进入色带；切换日断开为两条

    :param segments: resolve_effective_plans 结果
    :param month_start: 月初
    :param month_end: 月末
    :param meta: version_id → (short_name, color)
    :return:
    """
    bands: list[CalendarPlanBand] = []
    for seg in segments:
        if seg.plan_version_id is None:
            continue
        start = max(seg.start, month_start)
        end = min(seg.end, month_end)
        if end < start:
            continue
        short_name, color = meta.get(seg.plan_version_id, (None, None))
        bands.append(
            CalendarPlanBand(
                plan_version_id=seg.plan_version_id,
                short_name=short_name,
                color=color,
                start=start,
                end=end,
            )
        )
    return bands


async def lookup_period(
    db: AsyncSession,
    *,
    site_id: int,
    rider_id: int | None,
    biz_date: date,
) -> RiderSalarySettlePeriod | None:
    """优先骑手级周期，再站点级（rider_id=0）。不创建。"""
    if rider_id:
        row = await db.scalar(
            select(RiderSalarySettlePeriod)
            .where(
                RiderSalarySettlePeriod.site_id == site_id,
                RiderSalarySettlePeriod.rider_id == rider_id,
                RiderSalarySettlePeriod.start_date <= biz_date,
                RiderSalarySettlePeriod.end_date >= biz_date,
                RiderSalarySettlePeriod.deleted == 0,
            )
            .limit(1)
        )
        if row is not None:
            return row
    return await db.scalar(
        select(RiderSalarySettlePeriod)
        .where(
            RiderSalarySettlePeriod.site_id == site_id,
            RiderSalarySettlePeriod.rider_id == _SITE_LEVEL,
            RiderSalarySettlePeriod.start_date <= biz_date,
            RiderSalarySettlePeriod.end_date >= biz_date,
            RiderSalarySettlePeriod.deleted == 0,
        )
        .limit(1)
    )


async def get_or_create_period_fallback(
    db: AsyncSession,
    site_id: int,
    rider_id: int | None,
    any_date: date,
) -> RiderSalarySettlePeriod:
    """
    D5 不可用时的私有实现：只查询已有周期；没有则按站点/骑手周期配置合成内存对象（不落库）。
    """
    existing = await lookup_period(db, site_id=site_id, rider_id=rider_id, biz_date=any_date)
    if existing is not None:
        return existing
    site = await site_dao.get(db, site_id)
    if site is None:
        raise errors.NotFoundError(msg='站点不存在')
    cycle = site.settle_cycle
    config = site.cycle_config
    if rider_id:
        rider = await rider_dao.get(db, rider_id)
        if rider is not None and rider.settle_cycle_override:
            cycle = rider.settle_cycle_override
            config = rider.cycle_config_override
    start, end = compute_period_range(cycle, config, any_date)
    return RiderSalarySettlePeriod(
        site_id=site_id,
        cycle_type=cycle,
        start_date=start,
        end_date=end,
        rider_id=rider_id or _SITE_LEVEL,
        status=PeriodStatus.open.value,
    )


async def resolve_period(
    db: AsyncSession,
    site_id: int,
    rider_id: int | None,
    any_date: date,
) -> RiderSalarySettlePeriod:
    """优先 D5 get_or_create_period，否则走私有回退"""
    getter = _load_d5_getter()
    if getter is not None:
        return await getter(db, site_id, rider_id, any_date)
    return await get_or_create_period_fallback(db, site_id, rider_id, any_date)


def _load_d5_getter() -> Any:
    try:
        from backend.plugin.rider_salary.service.period_service import period_service as d5
    except ImportError:
        return None
    return getattr(d5, 'get_or_create_period', None)


def pick_effective_payroll(rows: list[RiderSalaryPayroll]) -> RiderSalaryPayroll | None:
    """排除 voided/reversal；有 supplement 用最新 supplement，否则最新有效单"""
    valid = [
        row
        for row in rows
        if row.status != PayrollStatus.voided.value
        and row.kind != PayrollKind.reversal.value
        and row.status in _PAYROLL_OK
    ]
    if not valid:
        return None
    supplements = [row for row in valid if row.kind == PayrollKind.supplement.value]
    pool = supplements or valid
    pool.sort(key=lambda row: (row.calc_version, row.id), reverse=True)
    return pool[0]


class CalendarService:
    """薪资日历"""

    async def build_month(  # ruff:ignore[complex-structure]
        self,
        db: AsyncSession,
        rider_id: int,
        month: str | None,
        *,
        request: Request | None = None,
        for_rider: bool = False,
    ) -> GetCalendarMonth:
        """
        构建月历。/me 与管理端共用。

        :param db: 会话
        :param rider_id: 骑手
        :param month: YYYY-MM
        :param request: 管理端用于站点可见性
        :param for_rider: 骑手端裁剪内部字段（月历本身不含 calc_trace）
        :return:
        """
        rider = await rider_dao.get(db, rider_id)
        if rider is None:
            raise errors.NotFoundError(msg='骑手不存在')
        if request is not None and not for_rider:
            visible = await get_visible_site_ids(request, db)
            assert_site_visible(visible, rider.site_id)
        month_key, start, end = parse_month(month)
        segments = await resolve_effective_plans(db, rider_id, start, end)
        plan_by_day = _plan_by_day(segments, start, end)
        version_ids = {seg.plan_version_id for seg in segments if seg.plan_version_id}
        meta = await _plan_meta(db, version_ids)
        dailies = {row.biz_date: row for row in await payroll_daily_dao.list_by_rider_range(db, rider_id, start, end)}
        orders = await _orders_in_range(db, rider_id, start, end)
        orders_by_day: dict[date, list[RiderSalaryOrder]] = defaultdict(list)
        for row in orders:
            orders_by_day[row.biz_date].append(row)
        adjustments = await _adjustments_in_range(db, rider_id, start, end)
        adj_by_day: dict[date, list[RiderSalaryAdjustment]] = defaultdict(list)
        for row in adjustments:
            adj_by_day[row.biz_date].append(row)
        subjects = await _subjects_map(db, {row.subject_id for row in adjustments})
        details = await _details_in_range(db, rider_id, start, end)
        detail_names_by_day: dict[date, list[str]] = defaultdict(list)
        subject_ids = {row.subject_id for row in details} | set(subjects)
        extra_subjects = await _subjects_map(db, subject_ids)
        subjects.update(extra_subjects)
        for row in details:
            if row.biz_date is None:
                continue
            name = subjects.get(row.subject_id)
            if name is not None:
                detail_names_by_day[row.biz_date].append(name.name)
        covered, site_order_dates = await _import_coverage(db, rider.site_id, start, end)
        periods = await _periods_overlapping(db, rider.site_id, rider_id, start, end)
        period_by_day = _period_by_day(periods, rider_id, start, end)
        payrolls = await _payrolls_for_periods(db, rider_id, [row.id for row in periods if row.id])
        payroll_by_period: dict[int, list[RiderSalaryPayroll]] = defaultdict(list)
        for row in payrolls:
            payroll_by_period[row.period_id].append(row)

        days: list[CalendarDayItem] = []
        month_orders = 0
        month_valid = 0
        for day in iter_dates(start, end):
            cache = dailies.get(day)
            day_orders = orders_by_day.get(day, [])
            completed = [row for row in day_orders if row.status == OrderStatus.completed.value]
            plan_vid = plan_by_day.get(day)
            imported = day in covered or day in site_order_dates
            if cache is not None:
                order_count = cache.order_count
                valid_count = cache.valid_order_count
                net_adjust = q2(cache.net_adjust)
                day_status = cache.day_status
                plan_vid = cache.plan_version_id if cache.plan_version_id is not None else plan_vid
                period_id = cache.period_id
            else:
                order_count = len(day_orders)
                valid_count = len(completed)
                net_adjust = q2(sum((row.signed_amount or ZERO for row in adj_by_day.get(day, [])), ZERO))
                day_status = resolve_day_status(
                    has_plan=plan_vid is not None,
                    order_count=order_count,
                    valid_order_count=valid_count,
                    imported=imported,
                )
                period_id = None
            period = period_by_day.get(day)
            if period_id is None and period is not None:
                period_id = period.id
            period_status = period.status if period is not None else None
            names = list(detail_names_by_day.get(day, []))
            for adj in adj_by_day.get(day, []):
                sub = subjects.get(adj.subject_id)
                if sub is not None:
                    names.append(sub.name)
            short_name = color = None
            if plan_vid:
                short_name, color = meta.get(plan_vid, (None, None))[:2]
            days.append(
                CalendarDayItem(
                    date=day,
                    order_count=order_count,
                    valid_order_count=valid_count,
                    net_adjust=net_adjust,
                    subjects=summarize_subjects(names),
                    plan_version_id=plan_vid,
                    plan_short_name=short_name,
                    plan_color=color,
                    day_status=day_status,
                    period_id=period_id,
                    period_status=period_status,
                    is_locked=period_status in _LOCKED if period_status else False,
                )
            )
            month_orders += order_count
            month_valid += valid_count

        gross = bonus = penalty = deduction = advance = net = ZERO
        stale = False
        chips: list[CalendarPeriodChip] = []
        seen_period: set[int] = set()
        for period in sorted(periods, key=lambda row: row.start_date):
            if not period.id or period.id in seen_period:
                continue
            seen_period.add(period.id)
            chips.append(
                CalendarPeriodChip(
                    id=period.id,
                    range=period_range_text(period.start_date, period.end_date),
                    status=period.status,
                )
            )
            chosen = pick_effective_payroll(payroll_by_period.get(period.id, []))
            if chosen is None:
                continue
            if chosen.stale:
                stale = True
            gross += q2(chosen.gross)
            bonus += q2(chosen.bonus_total)
            penalty += q2(chosen.penalty_total)
            deduction += q2(chosen.deduction_total)
            advance += q2(chosen.advance_deduction)
            net += q2(chosen.net)

        _ = for_rider
        return GetCalendarMonth(
            month=month_key,
            summary=CalendarMonthSummary(
                order_count=month_orders,
                valid_order_count=month_valid,
                gross=q2(gross),
                bonus=q2(bonus),
                penalty=q2(penalty),
                deduction_total=q2(deduction),
                advance_deduction=q2(advance),
                net=q2(net),
                periods=chips,
                stale=stale,
            ),
            days=days,
            plan_bands=clip_plan_bands(segments, start, end, meta),
        )

    async def build_day(  # ruff:ignore[complex-structure]
        self,
        db: AsyncSession,
        rider_id: int,
        biz_date: date,
        *,
        request: Request | None = None,
        for_rider: bool = False,
    ) -> GetCalendarDayDetail:
        """构建日详情。/me 传入 for_rider=True 去掉 calc_trace。"""
        rider = await rider_dao.get(db, rider_id)
        if rider is None:
            raise errors.NotFoundError(msg='骑手不存在')
        if request is not None and not for_rider:
            visible = await get_visible_site_ids(request, db)
            assert_site_visible(visible, rider.site_id)
        segments = await resolve_effective_plans(db, rider_id, biz_date, biz_date)
        plan_vid = segments[0].plan_version_id if segments else None
        cache = await payroll_daily_dao.get_one(db, rider_id, biz_date)
        if cache is not None and cache.plan_version_id is not None:
            plan_vid = cache.plan_version_id
        plan_info = await _plan_info(db, plan_vid)
        period = await lookup_period(db, site_id=rider.site_id, rider_id=rider_id, biz_date=biz_date)
        period_info = None
        if period is not None:
            period_info = CalendarPeriodInfo(
                id=period.id,
                range=period_range_text(period.start_date, period.end_date),
                status=period.status,
            )
        is_holiday_day = bool(is_holiday(biz_date))
        orders = await _orders_in_range(db, rider_id, biz_date, biz_date)
        details = await _details_in_range(db, rider_id, biz_date, biz_date)
        subject_ids = {row.subject_id for row in details}
        adjustments = await _adjustments_in_range(db, rider_id, biz_date, biz_date)
        subject_ids |= {row.subject_id for row in adjustments}
        subjects = await _subjects_map(db, subject_ids)
        item_names = await _item_names(db, {row.plan_item_id for row in details if row.plan_item_id})
        details_by_order: dict[int, list[RiderSalaryPayrollDetail]] = defaultdict(list)
        daily_items: list[CalendarDailyItem] = []
        formula_amount = ZERO
        for row in details:
            if row.order_id:
                details_by_order[row.order_id].append(row)
            if row.source == DetailSource.formula.value and row.stage == CalcStage.daily.value:
                sub = subjects.get(row.subject_id)
                daily_items.append(
                    CalendarDailyItem(
                        subject=sub.name if sub else str(row.subject_id),
                        name=item_names.get(row.plan_item_id) if row.plan_item_id else None,
                        amount=q2(row.amount),
                        calc_trace=None if for_rider else row.calc_trace,
                    )
                )
            if row.source == DetailSource.formula.value and row.stage in {
                CalcStage.per_order.value,
                CalcStage.daily.value,
            }:
                formula_amount += q2(row.amount)
        if cache is not None:
            formula_amount = q2(cache.formula_amount)
        order_models: list[CalendarDayOrder] = []
        for order in orders:
            hits = [
                CalendarHitDetail(
                    subject=(subjects[row.subject_id].name if row.subject_id in subjects else str(row.subject_id)),
                    amount=q2(row.amount),
                    calc_trace=None if for_rider else row.calc_trace,
                )
                for row in details_by_order.get(order.id, [])
            ]
            order_models.append(
                CalendarDayOrder(
                    id=order.id,
                    order_no=order.order_no,
                    distance_km=order.distance_km,
                    weight_jin=order.weight_jin,
                    order_time=order.order_time,
                    deliver_time=order.deliver_time,
                    status=order.status,
                    amount=order.amount,
                    details=hits,
                )
            )
        adj_models: list[CalendarAdjustmentItem] = []
        manual_bonus = ZERO
        manual_penalty = ZERO
        for adj in adjustments:
            sub = subjects.get(adj.subject_id)
            signed = q2(adj.signed_amount if adj.signed_amount is not None else adj.amount)
            if sub is not None and adj.signed_amount is None:
                signed = signed if sub.direction == SubjectDirection.bonus.value else q2(-signed)
            direction = sub.direction if sub else SubjectDirection.bonus.value
            if direction == SubjectDirection.bonus.value:
                manual_bonus += signed
            else:
                manual_penalty += signed
            adj_models.append(
                CalendarAdjustmentItem(
                    id=adj.id,
                    subject=sub.name if sub else str(adj.subject_id),
                    direction=direction,
                    amount=signed,
                    remark=adj.remark,
                )
            )
        if cache is not None:
            manual_bonus = q2(cache.manual_bonus)
            manual_penalty = q2(cache.manual_penalty)
        covered, site_order_dates = await _import_coverage(db, rider.site_id, biz_date, biz_date)
        imported = biz_date in covered or biz_date in site_order_dates
        completed = [row for row in orders if row.status == OrderStatus.completed.value]
        if cache is not None:
            day_status = cache.day_status
            order_count = cache.order_count
        else:
            day_status = resolve_day_status(
                has_plan=plan_vid is not None,
                order_count=len(orders),
                valid_order_count=len(completed),
                imported=imported,
            )
            order_count = len(orders)
        net = q2(formula_amount + manual_bonus + manual_penalty)
        return GetCalendarDayDetail(
            date=biz_date,
            plan=plan_info,
            period=period_info,
            is_holiday=is_holiday_day,
            day_status=day_status,
            orders=order_models,
            daily_items=daily_items,
            adjustments=adj_models,
            totals=CalendarDayTotals(
                order_count=order_count,
                formula_amount=q2(formula_amount),
                manual_bonus=q2(manual_bonus),
                manual_penalty=q2(manual_penalty),
                net=net,
            ),
        )


def _plan_by_day(segments: Sequence[Segment], start: date, end: date) -> dict[date, int | None]:
    mapping: dict[date, int | None] = {}
    for seg in segments:
        cur = max(seg.start, start)
        last = min(seg.end, end)
        while cur <= last:
            mapping[cur] = seg.plan_version_id
            cur += timedelta(days=1)
    return mapping


async def _plan_meta(db: AsyncSession, version_ids: set[int]) -> dict[int, tuple[str | None, str | None]]:
    if not version_ids:
        return {}
    versions = {
        row.id: row
        for row in (
            await db.scalars(
                select(RiderSalaryPlanVersion).where(
                    RiderSalaryPlanVersion.id.in_(version_ids),
                    RiderSalaryPlanVersion.deleted == 0,
                )
            )
        ).all()
    }
    plan_ids = {row.plan_id for row in versions.values()}
    plans: dict[int, RiderSalaryPlan] = {}
    if plan_ids:
        plans = {
            row.id: row
            for row in (
                await db.scalars(
                    select(RiderSalaryPlan).where(
                        RiderSalaryPlan.id.in_(plan_ids),
                        RiderSalaryPlan.deleted == 0,
                    )
                )
            ).all()
        }
    result: dict[int, tuple[str | None, str | None]] = {}
    for vid, version in versions.items():
        plan = plans.get(version.plan_id)
        result[vid] = (getattr(plan, 'short_name', None), getattr(plan, 'color', None))
    return result


async def _plan_info(db: AsyncSession, version_id: int | None) -> CalendarPlanInfo | None:
    if not version_id:
        return CalendarPlanInfo()
    version = await plan_version_dao.get(db, version_id)
    if version is None:
        return CalendarPlanInfo(version_id=version_id)
    plan = await plan_dao.get(db, version.plan_id)
    return CalendarPlanInfo(
        version_id=version.id,
        plan_name=getattr(plan, 'name', None),
        short_name=getattr(plan, 'short_name', None),
        version_no=version.version_no,
        mode_tag=version.mode_tag,
    )


async def _orders_in_range(db: AsyncSession, rider_id: int, start: date, end: date) -> list[RiderSalaryOrder]:
    rows = await db.scalars(
        select(RiderSalaryOrder)
        .where(
            RiderSalaryOrder.rider_id == rider_id,
            RiderSalaryOrder.biz_date >= start,
            RiderSalaryOrder.biz_date <= end,
            RiderSalaryOrder.deleted == 0,
        )
        .order_by(RiderSalaryOrder.id.asc())
    )
    return list(rows.all())


async def _adjustments_in_range(db: AsyncSession, rider_id: int, start: date, end: date) -> list[RiderSalaryAdjustment]:
    rows = await db.scalars(
        select(RiderSalaryAdjustment)
        .where(
            RiderSalaryAdjustment.rider_id == rider_id,
            RiderSalaryAdjustment.biz_date >= start,
            RiderSalaryAdjustment.biz_date <= end,
            RiderSalaryAdjustment.deleted == 0,
        )
        .order_by(RiderSalaryAdjustment.id.asc())
    )
    return list(rows.all())


async def _details_in_range(db: AsyncSession, rider_id: int, start: date, end: date) -> list[RiderSalaryPayrollDetail]:
    rows = await db.scalars(
        select(RiderSalaryPayrollDetail).where(
            RiderSalaryPayrollDetail.rider_id == rider_id,
            RiderSalaryPayrollDetail.biz_date >= start,
            RiderSalaryPayrollDetail.biz_date <= end,
            RiderSalaryPayrollDetail.deleted == 0,
        )
    )
    return list(rows.all())


async def _subjects_map(db: AsyncSession, ids: set[int]) -> dict[int, RiderSalarySubject]:
    ids = {pk for pk in ids if pk}
    if not ids:
        return {}
    rows = await db.scalars(
        select(RiderSalarySubject).where(
            RiderSalarySubject.id.in_(ids),
            RiderSalarySubject.deleted == 0,
        )
    )
    return {row.id: row for row in rows.all()}


async def _item_names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    ids = {pk for pk in ids if pk}
    if not ids:
        return {}
    from backend.plugin.rider_salary.model.plan_item import RiderSalaryPlanItem

    rows = await db.scalars(
        select(RiderSalaryPlanItem).where(RiderSalaryPlanItem.id.in_(ids), RiderSalaryPlanItem.deleted == 0)
    )
    return {row.id: row.name for row in rows.all()}


async def _import_coverage(db: AsyncSession, site_id: int, start: date, end: date) -> tuple[set[date], set[date]]:
    batches = (
        await db.scalars(
            select(RiderSalaryImportBatch).where(
                RiderSalaryImportBatch.site_id == site_id,
                RiderSalaryImportBatch.deleted == 0,
            )
        )
    ).all()
    covered: set[date] = set()
    for batch in batches:
        if batch.date_from is None or batch.date_to is None:
            continue
        covered.update(iter_dates(max(batch.date_from, start), min(batch.date_to, end)))
    site_dates = set(
        (
            await db.scalars(
                select(RiderSalaryOrder.biz_date).where(
                    RiderSalaryOrder.site_id == site_id,
                    RiderSalaryOrder.biz_date >= start,
                    RiderSalaryOrder.biz_date <= end,
                    RiderSalaryOrder.deleted == 0,
                )
            )
        ).all()
    )
    return covered, site_dates


async def _periods_overlapping(
    db: AsyncSession,
    site_id: int,
    rider_id: int,
    start: date,
    end: date,
) -> list[RiderSalarySettlePeriod]:
    rows = await db.scalars(
        select(RiderSalarySettlePeriod).where(
            RiderSalarySettlePeriod.site_id == site_id,
            RiderSalarySettlePeriod.rider_id.in_([_SITE_LEVEL, rider_id]),
            RiderSalarySettlePeriod.start_date <= end,
            RiderSalarySettlePeriod.end_date >= start,
            RiderSalarySettlePeriod.deleted == 0,
        )
    )
    return list(rows.all())


def _period_by_day(
    periods: list[RiderSalarySettlePeriod],
    rider_id: int,
    start: date,
    end: date,
) -> dict[date, RiderSalarySettlePeriod]:
    rider_level = [row for row in periods if row.rider_id == rider_id]
    site_level = [row for row in periods if row.rider_id == _SITE_LEVEL]
    mapping: dict[date, RiderSalarySettlePeriod] = {}
    for day in iter_dates(start, end):
        hit = next((row for row in rider_level if row.start_date <= day <= row.end_date), None)
        if hit is None:
            hit = next((row for row in site_level if row.start_date <= day <= row.end_date), None)
        if hit is not None:
            mapping[day] = hit
    return mapping


async def _payrolls_for_periods(db: AsyncSession, rider_id: int, period_ids: list[int]) -> list[RiderSalaryPayroll]:
    if not period_ids:
        return []
    rows = await db.scalars(
        select(RiderSalaryPayroll).where(
            RiderSalaryPayroll.rider_id == rider_id,
            RiderSalaryPayroll.period_id.in_(period_ids),
            RiderSalaryPayroll.deleted == 0,
        )
    )
    return list(rows.all())


calendar_service: CalendarService = CalendarService()
