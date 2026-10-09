import json

from calendar import monthrange
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from chinese_calendar import is_holiday
from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.day_flag import day_flag_dao
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
    PeriodStatus,
    SubjectDirection,
)
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.import_batch import RiderSalaryImportBatch
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.model.plan_item import RiderSalaryPlanItem
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.schema.calendar import (
    CalendarAdjustmentItem,
    CalendarDailyItem,
    CalendarDayFlagInfo,
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
from backend.plugin.rider_salary.service.payroll_view import (
    details_of_effective,
    effective_payroll_ids,
    pick_effective_payroll,
)
from backend.plugin.rider_salary.service.rider_service import Segment, resolve_effective_plans
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.excel import assert_export_row_limit, stream_rows
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.periods import compute_period_range
from backend.plugin.rider_salary.utils.recalc import (
    COVERAGE_CACHE_TTL_SECONDS,
    coverage_cache_key,
    get_cached_text,
    month_windows,
    set_cached_text,
)
from backend.utils.timezone import timezone

ZERO = Decimal('0.00')
_SITE_LEVEL = 0
_LOCKED = {PeriodStatus.locked.value, PeriodStatus.paid.value}


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


def dominant_site(site_ids: Sequence[int]) -> int:
    """同一天多个快照时，取出现次数最多的站点；次数相同取较小的站点 ID。"""
    counts: dict[int, int] = defaultdict(int)
    for site_id in site_ids:
        counts[int(site_id)] += 1
    return min(counts, key=lambda site_id: (-counts[site_id], site_id))


def assign_site_by_day(
    start: date,
    end: date,
    *,
    order_points: Sequence[tuple[date, int]],
    adjustment_points: Sequence[tuple[date, int]] = (),
    ranges: Sequence[tuple[date, date, int]] = (),
    edges: Sequence[tuple[date, int]] = (),
    fallback_site_id: int,
) -> dict[date, int]:
    """
    按订单、奖惩和骑手级周期上的站点快照，为区间内每一天选择站点。

    当天有订单时用订单站点，否则用当天奖惩站点。空白日若落在骑手级周期内，用该周期的站点。
    仍空白时沿用前一个快照，前面没有则用后一个。换站日是新站点第一次出现在快照里的日期，
    在此之前的空白日仍归旧站点。没有任何快照时才退回骑手当前站点。

    :param start: 区间开始
    :param end: 区间结束
    :param order_points: 订单 (业务日, 站点 ID)
    :param adjustment_points: 奖惩 (业务日, 站点 ID)
    :param ranges: 骑手级周期 (开始, 结束, 站点 ID)，按优先级从高到低
    :param edges: 区间外最近快照 (业务日, 站点 ID)
    :param fallback_site_id: 没有任何快照时使用的站点
    :return: 业务日 → 站点 ID
    """
    orders_on_day = _sites_on_day(order_points, start, end)
    adjustments_on_day = _sites_on_day(adjustment_points, start, end)
    chosen: dict[date, int] = {}
    for day in set(orders_on_day) | set(adjustments_on_day):
        if orders_on_day.get(day):
            chosen[day] = dominant_site(orders_on_day[day])
        else:
            chosen[day] = dominant_site(adjustments_on_day[day])
    anchors = sorted([*chosen.items(), *((biz_date, int(site_id)) for biz_date, site_id in edges)])
    result: dict[date, int] = {}
    for day in iter_dates(start, end):
        if day in chosen:
            result[day] = chosen[day]
            continue
        ranged = _site_from_ranges(day, ranges)
        if ranged is not None:
            result[day] = ranged
            continue
        previous = next((site_id for anchor_day, site_id in reversed(anchors) if anchor_day < day), None)
        if previous is not None:
            result[day] = previous
            continue
        following = next((site_id for anchor_day, site_id in anchors if anchor_day > day), None)
        result[day] = following if following is not None else int(fallback_site_id)
    return result


def _sites_on_day(points: Sequence[tuple[date, int]], start: date, end: date) -> dict[date, list[int]]:
    grouped: dict[date, list[int]] = defaultdict(list)
    for biz_date, site_id in points:
        if start <= biz_date <= end:
            grouped[biz_date].append(int(site_id))
    return grouped


def _site_from_ranges(day: date, ranges: Sequence[tuple[date, date, int]]) -> int | None:
    for range_start, range_end, site_id in ranges:
        if range_start <= day <= range_end:
            return int(site_id)
    return None


def _day_imported(day: date, site_id: int, coverage: dict[int, tuple[set[date], set[date]]]) -> bool:
    """该日在所属站点是否已导入，或该站点当天已有订单。"""
    covered, site_dates = coverage.get(site_id, (set(), set()))
    return day in covered or day in site_dates


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
    """优先骑手级周期，再站点级（rider_id=0）。同一层级按 id 升序。不创建。"""
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
            .order_by(RiderSalarySettlePeriod.id.asc())
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
        .order_by(RiderSalarySettlePeriod.id.asc())
        .limit(1)
    )


async def get_or_create_period_fallback(
    db: AsyncSession,
    site_id: int,
    rider_id: int | None,
    any_date: date,
) -> RiderSalarySettlePeriod:
    """
    只查询已有周期；没有则按站点或骑手周期配置合成内存对象，不写入结算周期表。
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
    """只查询已有周期；没有则按站点或骑手配置在内存中合成，不写入结算周期表。"""
    return await get_or_create_period_fallback(db, site_id, rider_id, any_date)


def _dominant_site_id(site_counts: dict[int, int]) -> int:
    """与 dominant_site 同一规则：次数多的优先，次数相同取较小站点 ID。"""
    return min(site_counts, key=lambda site_id: (-site_counts[site_id], site_id))


class _OrderFold:
    """按日累计单量和站点次数，不保留订单对象。"""

    def __init__(self) -> None:
        self.count_by_day: dict[date, int] = defaultdict(int)
        self.valid_by_day: dict[date, int] = defaultdict(int)
        self.site_counts: dict[date, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    def add(self, biz_date: date, site_id: int, status: str) -> None:
        self.count_by_day[biz_date] += 1
        if status == OrderStatus.completed.value:
            self.valid_by_day[biz_date] += 1
        self.site_counts[biz_date][int(site_id)] += 1

    def dominant_points(self) -> list[tuple[date, int]]:
        return [(day, _dominant_site_id(counts)) for day, counts in self.site_counts.items() if counts]


class _AdjustmentFold:
    """按日累计奖惩净额、科目和站点次数，不保留奖惩对象。"""

    def __init__(self) -> None:
        self.net_by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
        self.site_counts: dict[date, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.subject_ids: dict[date, list[int]] = defaultdict(list)
        self._seen_subjects: dict[date, set[int]] = defaultdict(set)

    def add(self, biz_date: date, site_id: int, subject_id: int, signed_amount: Decimal | None) -> None:
        self.net_by_day[biz_date] += signed_amount or ZERO
        self.site_counts[biz_date][int(site_id)] += 1
        sid = int(subject_id)
        if sid not in self._seen_subjects[biz_date]:
            self._seen_subjects[biz_date].add(sid)
            self.subject_ids[biz_date].append(sid)

    def dominant_points(self) -> list[tuple[date, int]]:
        return [(day, _dominant_site_id(counts)) for day, counts in self.site_counts.items() if counts]


def _subject_names_on_day(
    day: date,
    detail_subjects: dict[date, list[int]],
    adjustment_subjects: dict[date, list[int]],
    subjects: dict[int, RiderSalarySubject],
) -> list[str]:
    names: list[str] = []
    for sid in [*detail_subjects.get(day, []), *adjustment_subjects.get(day, [])]:
        subject = subjects.get(sid)
        if subject is not None:
            names.append(subject.name)
    return names


async def _count_orders_in_range(db: AsyncSession, rider_id: int, start: date, end: date) -> int:
    value = await db.scalar(
        select(func.count())
        .select_from(RiderSalaryOrder)
        .where(
            RiderSalaryOrder.rider_id == rider_id,
            RiderSalaryOrder.biz_date >= start,
            RiderSalaryOrder.biz_date <= end,
            RiderSalaryOrder.deleted == 0,
        )
    )
    return int(value or 0)


async def _count_adjustments_in_range(db: AsyncSession, rider_id: int, start: date, end: date) -> int:
    value = await db.scalar(
        select(func.count())
        .select_from(RiderSalaryAdjustment)
        .where(
            RiderSalaryAdjustment.rider_id == rider_id,
            RiderSalaryAdjustment.biz_date >= start,
            RiderSalaryAdjustment.biz_date <= end,
            RiderSalaryAdjustment.deleted == 0,
        )
    )
    return int(value or 0)


async def _count_details_in_range(db: AsyncSession, rider_id: int, start: date, end: date) -> int:
    value = await db.scalar(
        select(func.count())
        .select_from(RiderSalaryPayrollDetail)
        .where(
            RiderSalaryPayrollDetail.rider_id == rider_id,
            RiderSalaryPayrollDetail.biz_date >= start,
            RiderSalaryPayrollDetail.biz_date <= end,
            RiderSalaryPayrollDetail.deleted == 0,
        )
    )
    return int(value or 0)


async def _count_payrolls_overlapping(db: AsyncSession, rider_id: int, start: date, end: date) -> int:
    value = await db.scalar(
        select(func.count())
        .select_from(RiderSalaryPayroll)
        .join(RiderSalarySettlePeriod, RiderSalarySettlePeriod.id == RiderSalaryPayroll.period_id)
        .where(
            RiderSalaryPayroll.rider_id == rider_id,
            RiderSalaryPayroll.deleted == 0,
            RiderSalarySettlePeriod.deleted == 0,
            RiderSalarySettlePeriod.start_date <= end,
            RiderSalarySettlePeriod.end_date >= start,
        )
    )
    return int(value or 0)


async def assert_calendar_volume(db: AsyncSession, rider_id: int, start: date, end: date) -> tuple[int, int, int, int]:
    """
    统计月历会扫描的订单、奖惩、明细和重叠薪资单。超过上限时拒绝，且不再读取这些行。

    :return: 订单数、奖惩数、明细数、薪资单数
    """
    orders = await _count_orders_in_range(db, rider_id, start, end)
    adjustments = await _count_adjustments_in_range(db, rider_id, start, end)
    details = await _count_details_in_range(db, rider_id, start, end)
    payrolls = await _count_payrolls_overlapping(db, rider_id, start, end)
    assert_export_row_limit(orders + adjustments + details + payrolls)
    return orders, adjustments, details, payrolls


async def _fold_orders(db: AsyncSession, rider_id: int, start: date, end: date) -> _OrderFold:
    fold = _OrderFold()
    stmt = select(RiderSalaryOrder.biz_date, RiderSalaryOrder.site_id, RiderSalaryOrder.status).where(
        RiderSalaryOrder.rider_id == rider_id,
        RiderSalaryOrder.biz_date >= start,
        RiderSalaryOrder.biz_date <= end,
        RiderSalaryOrder.deleted == 0,
    )
    async for row in stream_rows(db, stmt):
        fold.add(row[0], int(row[1]), row[2])
    return fold


async def _fold_adjustments(db: AsyncSession, rider_id: int, start: date, end: date) -> _AdjustmentFold:
    fold = _AdjustmentFold()
    stmt = select(
        RiderSalaryAdjustment.biz_date,
        RiderSalaryAdjustment.site_id,
        RiderSalaryAdjustment.subject_id,
        RiderSalaryAdjustment.signed_amount,
    ).where(
        RiderSalaryAdjustment.rider_id == rider_id,
        RiderSalaryAdjustment.biz_date >= start,
        RiderSalaryAdjustment.biz_date <= end,
        RiderSalaryAdjustment.deleted == 0,
    )
    async for row in stream_rows(db, stmt):
        fold.add(row[0], int(row[1]), int(row[2]), row[3])
    return fold


async def _fold_detail_subjects(
    db: AsyncSession,
    rider_id: int,
    start: date,
    end: date,
    allowed_payroll_ids: set[int],
) -> dict[date, list[int]]:
    """只保留有效单上的科目 ID，按首次出现的顺序，不保留明细对象。"""
    if not allowed_payroll_ids:
        return {}
    found: dict[date, list[int]] = defaultdict(list)
    seen: dict[date, set[int]] = defaultdict(set)
    stmt = (
        select(RiderSalaryPayrollDetail.biz_date, RiderSalaryPayrollDetail.subject_id)
        .where(
            RiderSalaryPayrollDetail.rider_id == rider_id,
            RiderSalaryPayrollDetail.biz_date >= start,
            RiderSalaryPayrollDetail.biz_date <= end,
            RiderSalaryPayrollDetail.deleted == 0,
            RiderSalaryPayrollDetail.payroll_id.in_(allowed_payroll_ids),
            RiderSalaryPayrollDetail.biz_date.is_not(None),
        )
        .order_by(RiderSalaryPayrollDetail.id.asc())
    )
    async for row in stream_rows(db, stmt):
        biz_date = row[0]
        subject_id = int(row[1])
        if subject_id in seen[biz_date]:
            continue
        seen[biz_date].add(subject_id)
        found[biz_date].append(subject_id)
    return found


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
        order_total, adjustment_total, detail_total, _payroll_upper = await assert_calendar_volume(
            db, rider_id, start, end
        )
        segments = await resolve_effective_plans(db, rider_id, start, end)
        plan_by_day = _plan_by_day(segments, start, end)
        version_ids = {seg.plan_version_id for seg in segments if seg.plan_version_id}
        meta = await _plan_meta(db, version_ids)
        dailies = {row.biz_date: row for row in await payroll_daily_dao.list_by_rider_range(db, rider_id, start, end)}
        order_fold = await _fold_orders(db, rider_id, start, end) if order_total else _OrderFold()
        adjustment_fold = await _fold_adjustments(db, rider_id, start, end) if adjustment_total else _AdjustmentFold()
        site_by_day = await _resolve_site_by_day(
            db,
            rider_id,
            start,
            end,
            fallback_site_id=int(rider.site_id),
            order_points=order_fold.dominant_points(),
            adjustment_points=adjustment_fold.dominant_points(),
        )
        site_ids = set(site_by_day.values())
        coverage = await _import_coverage_by_sites(db, site_ids, start, end)
        periods = await _periods_overlapping_sites(db, site_ids, rider_id, start, end)
        period_by_day = _period_by_day(periods, rider_id, start, end, site_by_day)
        payrolls = await _payrolls_for_periods(db, rider_id, [row.id for row in periods if row.id])
        payroll_by_period: dict[int, list[RiderSalaryPayroll]] = defaultdict(list)
        for row in payrolls:
            payroll_by_period[row.period_id].append(row)
        detail_subjects = (
            await _fold_detail_subjects(db, rider_id, start, end, effective_payroll_ids(payrolls))
            if detail_total
            else {}
        )
        subject_ids: set[int] = set()
        for bucket in detail_subjects.values():
            subject_ids.update(bucket)
        for bucket in adjustment_fold.subject_ids.values():
            subject_ids.update(bucket)
        subjects = await _subjects_map(db, subject_ids)

        days: list[CalendarDayItem] = []
        month_orders = 0
        month_valid = 0
        for day in iter_dates(start, end):
            cache = dailies.get(day)
            plan_vid = plan_by_day.get(day)
            imported = _day_imported(day, site_by_day[day], coverage)
            if cache is not None:
                order_count = cache.order_count
                valid_count = cache.valid_order_count
                net_adjust = q2(cache.net_adjust)
                day_status = cache.day_status
                plan_vid = cache.plan_version_id if cache.plan_version_id is not None else plan_vid
                period_id = cache.period_id
            else:
                order_count = order_fold.count_by_day.get(day, 0)
                valid_count = order_fold.valid_by_day.get(day, 0)
                net_adjust = q2(adjustment_fold.net_by_day.get(day, ZERO))
                day_status = resolve_day_status(
                    has_plan=plan_vid is not None,
                    order_count=order_count,
                    valid_order_count=valid_count,
                    imported=imported,
                )
                period_id = None
            period = period_by_day.get(day)
            if period is not None:
                period_id = period.id
                period_status = period.status
            else:
                period_status = None
            names = _subject_names_on_day(day, detail_subjects, adjustment_fold.subject_ids, subjects)
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
        await assert_calendar_volume(db, rider_id, biz_date, biz_date)
        segments = await resolve_effective_plans(db, rider_id, biz_date, biz_date)
        plan_vid = segments[0].plan_version_id if segments else None
        cached = await payroll_daily_dao.list_by_rider_range(db, rider_id, biz_date, biz_date)
        cache = cached[0] if cached else None
        if cache is not None and cache.plan_version_id is not None:
            plan_vid = cache.plan_version_id
        plan_info = await _plan_info(db, plan_vid)
        site_by_day = await _resolve_site_by_day(
            db,
            rider_id,
            biz_date,
            biz_date,
            fallback_site_id=int(rider.site_id),
        )
        day_site_id = site_by_day[biz_date]
        period = await lookup_period(db, site_id=day_site_id, rider_id=rider_id, biz_date=biz_date)
        period_info = None
        if period is not None:
            period_info = CalendarPeriodInfo(
                id=period.id,
                range=period_range_text(period.start_date, period.end_date),
                status=period.status,
            )
        flag_row = await day_flag_dao.get_by_site_date(db, day_site_id, biz_date)
        day_flag = CalendarDayFlagInfo(
            bad_weather=bool(getattr(flag_row, 'bad_weather', False)),
            high_temp=bool(getattr(flag_row, 'high_temp', False)),
            promo=bool(getattr(flag_row, 'promo', False)),
            is_holiday=bool(is_holiday(biz_date)),
            remark=getattr(flag_row, 'remark', None),
        )
        orders = await _orders_in_range(db, rider_id, biz_date, biz_date)
        period_payrolls: list[RiderSalaryPayroll] = []
        if period is not None and period.id:
            period_payrolls = await _payrolls_for_periods(db, rider_id, [period.id])
        details = details_of_effective(
            await _details_in_range(db, rider_id, biz_date, biz_date),
            period_payrolls,
        )
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
        covered, site_order_dates = await _import_coverage(db, day_site_id, biz_date, biz_date)
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
            day_flag=day_flag,
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
    rows = await db.scalars(
        select(RiderSalaryPlanItem).where(RiderSalaryPlanItem.id.in_(ids), RiderSalaryPlanItem.deleted == 0)
    )
    return {row.id: row.name for row in rows.all()}


async def _resolve_site_by_day(
    db: AsyncSession,
    rider_id: int,
    start: date,
    end: date,
    *,
    fallback_site_id: int,
    orders: Sequence[RiderSalaryOrder] | None = None,
    adjustments: Sequence[RiderSalaryAdjustment] | None = None,
    order_points: Sequence[tuple[date, int]] | None = None,
    adjustment_points: Sequence[tuple[date, int]] | None = None,
) -> dict[date, int]:
    """用订单、奖惩和骑手级周期的站点快照，解析区间内每天的站点。"""
    if order_points is None:
        if orders is None:
            orders = await _orders_in_range(db, rider_id, start, end)
        order_points = [(row.biz_date, int(row.site_id)) for row in orders]
    if adjustment_points is None:
        if adjustments is None:
            adjustments = await _adjustments_in_range(db, rider_id, start, end)
        adjustment_points = [(row.biz_date, int(row.site_id)) for row in adjustments]
    before = await _nearest_site_edge(db, rider_id, start, before=True)
    after = await _nearest_site_edge(db, rider_id, end, before=False)
    edges = [item for item in (before, after) if item is not None]
    return assign_site_by_day(
        start,
        end,
        order_points=order_points,
        adjustment_points=adjustment_points,
        ranges=await _rider_level_ranges(db, rider_id, start, end),
        edges=edges,
        fallback_site_id=fallback_site_id,
    )


async def _nearest_site_edge(
    db: AsyncSession,
    rider_id: int,
    bound: date,
    *,
    before: bool,
) -> tuple[date, int] | None:
    """区间外最近的一条订单或奖惩快照。同一天优先订单。"""
    if before:
        order_filter = RiderSalaryOrder.biz_date < bound
        order_by = (RiderSalaryOrder.biz_date.desc(), RiderSalaryOrder.id.desc())
        adjustment_filter = RiderSalaryAdjustment.biz_date < bound
        adjustment_by = (RiderSalaryAdjustment.biz_date.desc(), RiderSalaryAdjustment.id.desc())
    else:
        order_filter = RiderSalaryOrder.biz_date > bound
        order_by = (RiderSalaryOrder.biz_date.asc(), RiderSalaryOrder.id.asc())
        adjustment_filter = RiderSalaryAdjustment.biz_date > bound
        adjustment_by = (RiderSalaryAdjustment.biz_date.asc(), RiderSalaryAdjustment.id.asc())
    order_hit = (
        await db.execute(
            select(RiderSalaryOrder.biz_date, RiderSalaryOrder.site_id)
            .where(
                RiderSalaryOrder.rider_id == rider_id,
                order_filter,
                RiderSalaryOrder.deleted == 0,
            )
            .order_by(*order_by)
            .limit(1)
        )
    ).first()
    adjustment_hit = (
        await db.execute(
            select(RiderSalaryAdjustment.biz_date, RiderSalaryAdjustment.site_id)
            .where(
                RiderSalaryAdjustment.rider_id == rider_id,
                adjustment_filter,
                RiderSalaryAdjustment.deleted == 0,
            )
            .order_by(*adjustment_by)
            .limit(1)
        )
    ).first()
    if order_hit is not None and adjustment_hit is not None:
        order_closer = order_hit[0] >= adjustment_hit[0] if before else order_hit[0] <= adjustment_hit[0]
        chosen = order_hit if order_closer else adjustment_hit
        return chosen[0], int(chosen[1])
    if order_hit is not None:
        return order_hit[0], int(order_hit[1])
    if adjustment_hit is not None:
        return adjustment_hit[0], int(adjustment_hit[1])
    return None


async def _rider_level_ranges(
    db: AsyncSession,
    rider_id: int,
    start: date,
    end: date,
) -> list[tuple[date, date, int]]:
    """骑手级周期的站点快照。开始日越晚越优先，同一天取较小的周期 ID。"""
    rows = (
        await db.scalars(
            select(RiderSalarySettlePeriod)
            .where(
                RiderSalarySettlePeriod.rider_id == rider_id,
                RiderSalarySettlePeriod.start_date <= end,
                RiderSalarySettlePeriod.end_date >= start,
                RiderSalarySettlePeriod.deleted == 0,
            )
            .order_by(RiderSalarySettlePeriod.start_date.desc(), RiderSalarySettlePeriod.id.asc())
        )
    ).all()
    return [(row.start_date, row.end_date, int(row.site_id)) for row in rows]


async def _import_coverage(db: AsyncSession, site_id: int, start: date, end: date) -> tuple[set[date], set[date]]:
    coverage = await _import_coverage_by_sites(db, {site_id}, start, end)
    return coverage.get(site_id, (set(), set()))


def _clip_dates(days: set[date], start: date, end: date) -> set[date]:
    return {day for day in days if start <= day <= end}


def _dump_coverage(covered: set[date], order_dates: set[date]) -> str:
    return json.dumps(
        {
            'covered': [day.isoformat() for day in sorted(covered)],
            'orders': [day.isoformat() for day in sorted(order_dates)],
        },
        ensure_ascii=False,
    )


def _load_coverage(payload: str) -> tuple[set[date], set[date]] | None:
    try:
        data = json.loads(payload)
        covered = {date.fromisoformat(item) for item in data['covered']}
        order_dates = {date.fromisoformat(item) for item in data['orders']}
    except (KeyError, TypeError, ValueError):
        return None
    return covered, order_dates


async def _cached_month_coverage(site_id: int, month_start: date) -> tuple[set[date], set[date]] | None:
    raw = await get_cached_text(coverage_cache_key(site_id, month_start))
    if raw is None:
        return None
    return _load_coverage(raw)


async def _store_month_coverage(
    site_id: int,
    month_start: date,
    covered: set[date],
    order_dates: set[date],
) -> None:
    await set_cached_text(
        coverage_cache_key(site_id, month_start),
        _dump_coverage(covered, order_dates),
        ttl_seconds=COVERAGE_CACHE_TTL_SECONDS,
    )


async def _query_month_coverage(
    db: AsyncSession,
    site_ids: Sequence[int],
    month_start: date,
    month_end: date,
) -> dict[int, tuple[set[date], set[date]]]:
    """按自然月查询。订单日用 ``select distinct biz_date``，批次只取与该月重叠的区间。"""
    covered: dict[int, set[date]] = {site_id: set() for site_id in site_ids}
    order_dates: dict[int, set[date]] = {site_id: set() for site_id in site_ids}
    if not site_ids:
        return {}
    batches = (
        await db.scalars(
            select(RiderSalaryImportBatch).where(
                RiderSalaryImportBatch.site_id.in_(list(site_ids)),
                RiderSalaryImportBatch.deleted == 0,
                RiderSalaryImportBatch.date_from.is_not(None),
                RiderSalaryImportBatch.date_to.is_not(None),
                RiderSalaryImportBatch.date_from <= month_end,
                RiderSalaryImportBatch.date_to >= month_start,
            )
        )
    ).all()
    for batch in batches:
        if batch.date_from is None or batch.date_to is None:
            continue
        covered.setdefault(int(batch.site_id), set()).update(
            iter_dates(max(batch.date_from, month_start), min(batch.date_to, month_end))
        )
    for site_id in site_ids:
        rows = await db.scalars(
            select(RiderSalaryOrder.biz_date)
            .where(
                RiderSalaryOrder.site_id == site_id,
                RiderSalaryOrder.biz_date >= month_start,
                RiderSalaryOrder.biz_date <= month_end,
                RiderSalaryOrder.deleted == 0,
            )
            .distinct()
        )
        order_dates[site_id].update(rows.all())
    return {site_id: (covered[site_id], order_dates[site_id]) for site_id in site_ids}


async def _import_coverage_by_sites(
    db: AsyncSession,
    site_ids: set[int],
    start: date,
    end: date,
) -> dict[int, tuple[set[date], set[date]]]:
    """各站点在区间内的导入覆盖日，以及该站点已有订单的业务日。

    结果按（站点, 自然月）缓存。月内再请求同一站点不再查库。
    """
    if not site_ids:
        return {}
    covered: dict[int, set[date]] = {site_id: set() for site_id in site_ids}
    order_dates: dict[int, set[date]] = {site_id: set() for site_id in site_ids}
    missing: dict[date, list[int]] = defaultdict(list)
    windows = dict(month_windows(start, end))
    for month_start, month_end in windows.items():
        for site_id in site_ids:
            cached = await _cached_month_coverage(site_id, month_start)
            if cached is None:
                missing[month_start].append(site_id)
                continue
            month_covered, month_orders = cached
            covered[site_id].update(_clip_dates(month_covered, max(start, month_start), min(end, month_end)))
            order_dates[site_id].update(_clip_dates(month_orders, max(start, month_start), min(end, month_end)))
    for month_start, sites in missing.items():
        month_end = windows[month_start]
        loaded = await _query_month_coverage(db, sites, month_start, month_end)
        window_start = max(start, month_start)
        window_end = min(end, month_end)
        for site_id in sites:
            month_covered, month_orders = loaded.get(site_id, (set(), set()))
            await _store_month_coverage(site_id, month_start, month_covered, month_orders)
            covered[site_id].update(_clip_dates(month_covered, window_start, window_end))
            order_dates[site_id].update(_clip_dates(month_orders, window_start, window_end))
    return {site_id: (covered[site_id], order_dates[site_id]) for site_id in site_ids}


async def _periods_overlapping_sites(
    db: AsyncSession,
    site_ids: set[int],
    rider_id: int,
    start: date,
    end: date,
) -> list[RiderSalarySettlePeriod]:
    """区间内、指定站点上的站点级和骑手级周期。"""
    if not site_ids:
        return []
    rows = await db.scalars(
        select(RiderSalarySettlePeriod)
        .where(
            RiderSalarySettlePeriod.site_id.in_(site_ids),
            RiderSalarySettlePeriod.rider_id.in_([_SITE_LEVEL, rider_id]),
            RiderSalarySettlePeriod.start_date <= end,
            RiderSalarySettlePeriod.end_date >= start,
            RiderSalarySettlePeriod.deleted == 0,
        )
        .order_by(RiderSalarySettlePeriod.id.asc())
    )
    return list(rows.all())


def _period_by_day(
    periods: list[RiderSalarySettlePeriod],
    rider_id: int,
    start: date,
    end: date,
    site_by_day: dict[date, int],
) -> dict[date, RiderSalarySettlePeriod]:
    rider_level = [row for row in periods if row.rider_id == rider_id]
    site_level = [row for row in periods if row.rider_id == _SITE_LEVEL]
    mapping: dict[date, RiderSalarySettlePeriod] = {}
    for day in iter_dates(start, end):
        site_id = site_by_day.get(day)
        hit = next(
            (row for row in rider_level if row.site_id == site_id and row.start_date <= day <= row.end_date),
            None,
        )
        if hit is None:
            hit = next(
                (row for row in site_level if row.site_id == site_id and row.start_date <= day <= row.end_date),
                None,
            )
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
