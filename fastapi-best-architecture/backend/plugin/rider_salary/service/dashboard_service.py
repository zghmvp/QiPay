from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.rider_salary.engine.context import iter_dates
from backend.plugin.rider_salary.enums import (
    AdvanceStatus,
    DayStatus,
    OrderStatus,
    PayrollKind,
    PayrollStatus,
    PeriodStatus,
    RiderStatus,
)
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.model.import_batch import RiderSalaryImportBatch
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_daily import RiderSalaryPayrollDaily
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.rider_plan_binding import RiderSalaryRiderPlanBinding
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.schema.dashboard import (
    DashboardAttentionBlock,
    DashboardCards,
    DashboardRiderRank,
    DashboardTopRiders,
    DashboardTrendPoint,
    GetDashboardSummary,
)
from backend.plugin.rider_salary.service.calendar_service import parse_month, period_range_text, pick_effective_payroll
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

ZERO = Decimal('0.00')
_PAYROLL_OK = {PayrollStatus.draft.value, PayrollStatus.finalized.value, PayrollStatus.paid.value}
_ATTENTION_LIMIT = 10


class DashboardService:
    """工作台"""

    async def summary(
        self,
        *,
        db: AsyncSession,
        request: Request,
        site_id: int | None,
        month: str | None,
    ) -> GetDashboardSummary:
        visible = await get_visible_site_ids(request, db)
        if site_id is not None:
            assert_site_visible(visible, site_id)
            site_ids: set[int] | None = {site_id}
        else:
            site_ids = visible
        today = timezone.now().date()
        month_key, start, end = parse_month(month, today)
        rider_filter = _site_filter(RiderSalaryRider.site_id, site_ids)
        order_filter = _site_filter(RiderSalaryOrder.site_id, site_ids)
        advance_filter = _site_filter(RiderSalaryAdvance.site_id, site_ids)
        period_filter = _site_filter(RiderSalarySettlePeriod.site_id, site_ids)

        on_job = int(
            await db.scalar(
                select(func.count())
                .select_from(RiderSalaryRider)
                .where(RiderSalaryRider.status == RiderStatus.on_job.value, RiderSalaryRider.deleted == 0, rider_filter)
            )
            or 0
        )
        month_order_count = int(
            await db.scalar(
                select(func.count())
                .select_from(RiderSalaryOrder)
                .where(
                    RiderSalaryOrder.biz_date >= start,
                    RiderSalaryOrder.biz_date <= end,
                    RiderSalaryOrder.deleted == 0,
                    order_filter,
                )
            )
            or 0
        )
        month_valid = int(
            await db.scalar(
                select(func.count())
                .select_from(RiderSalaryOrder)
                .where(
                    RiderSalaryOrder.biz_date >= start,
                    RiderSalaryOrder.biz_date <= end,
                    RiderSalaryOrder.status == OrderStatus.completed.value,
                    RiderSalaryOrder.deleted == 0,
                    order_filter,
                )
            )
            or 0
        )
        pending_advances = int(
            await db.scalar(
                select(func.count())
                .select_from(RiderSalaryAdvance)
                .where(
                    RiderSalaryAdvance.status == AdvanceStatus.pending.value,
                    RiderSalaryAdvance.deleted == 0,
                    advance_filter,
                )
            )
            or 0
        )
        to_pay_advances = int(
            await db.scalar(
                select(func.count())
                .select_from(RiderSalaryAdvance)
                .where(
                    RiderSalaryAdvance.status == AdvanceStatus.to_pay.value,
                    RiderSalaryAdvance.deleted == 0,
                    advance_filter,
                )
            )
            or 0
        )
        estimated_gross = await self._estimated_gross(db, site_ids, start, end, period_filter)
        attention = await self._attention(
            db,
            site_ids=site_ids,
            start=start,
            end=end,
            today=today,
            pending_count=pending_advances,
        )
        trend = await self._trend(db, site_ids, today)
        top_riders = await self._top_riders(db, site_ids, start, end)
        return GetDashboardSummary(
            month=month_key,
            cards=DashboardCards(
                on_job_riders=on_job,
                month_order_count=month_order_count,
                month_valid_order_count=month_valid,
                estimated_gross=q2(estimated_gross),
                pending_advances=pending_advances,
                to_pay_advances=to_pay_advances,
            ),
            attention=attention,
            trend=trend,
            top_riders=top_riders,
        )

    async def _estimated_gross(
        self,
        db: AsyncSession,
        site_ids: set[int] | None,
        start: date,
        end: date,
        period_filter: Any,
    ) -> Decimal:
        periods = list(
            (
                await db.scalars(
                    select(RiderSalarySettlePeriod).where(
                        RiderSalarySettlePeriod.start_date <= end,
                        RiderSalarySettlePeriod.end_date >= start,
                        RiderSalarySettlePeriod.deleted == 0,
                        period_filter,
                    )
                )
            ).all()
        )
        if not periods:
            return ZERO
        period_ids = [row.id for row in periods]
        payrolls = list(
            (
                await db.scalars(
                    select(RiderSalaryPayroll).where(
                        RiderSalaryPayroll.period_id.in_(period_ids),
                        RiderSalaryPayroll.deleted == 0,
                        RiderSalaryPayroll.status.in_(list(_PAYROLL_OK)),
                        RiderSalaryPayroll.kind != PayrollKind.reversal.value,
                    )
                )
            ).all()
        )
        grouped: dict[tuple[int, int], list[RiderSalaryPayroll]] = defaultdict(list)
        for row in payrolls:
            grouped[row.period_id, row.rider_id].append(row)
        total = ZERO
        for rows in grouped.values():
            chosen = pick_effective_payroll(rows)
            if chosen is not None:
                total += q2(chosen.gross)
        return total

    async def _attention(
        self,
        db: AsyncSession,
        *,
        site_ids: set[int] | None,
        start: date,
        end: date,
        today: date,
        pending_count: int,
    ) -> list[DashboardAttentionBlock]:
        blocks: list[DashboardAttentionBlock] = []
        stale_block = await self._stale_periods(db, site_ids, start, end)
        if stale_block:
            blocks.append(stale_block)
        no_plan_block = await self._no_plan_days(db, site_ids, start, end)
        if no_plan_block:
            blocks.append(no_plan_block)
        pending_block = await self._pending_advances(db, site_ids, pending_count)
        if pending_block:
            blocks.append(pending_block)
        gap_block = await self._import_gaps(db, site_ids, start, end, today)
        if gap_block:
            blocks.append(gap_block)
        abnormal_block = await self._abnormal_orders(db, site_ids, start, end)
        if abnormal_block:
            blocks.append(abnormal_block)
        due_block = await self._due_periods(db, site_ids, today)
        if due_block:
            blocks.append(due_block)
        resigned_block = await self._resigned_with_orders(db, site_ids, start, end)
        if resigned_block:
            blocks.append(resigned_block)
        return blocks

    async def _stale_periods(
        self,
        db: AsyncSession,
        site_ids: set[int] | None,
        start: date,
        end: date,
    ) -> DashboardAttentionBlock | None:
        stmt = (
            select(RiderSalarySettlePeriod, func.count(RiderSalaryPayroll.id))
            .join(RiderSalaryPayroll, RiderSalaryPayroll.period_id == RiderSalarySettlePeriod.id)
            .where(
                RiderSalaryPayroll.stale.is_(True),
                RiderSalaryPayroll.deleted == 0,
                RiderSalarySettlePeriod.deleted == 0,
                RiderSalarySettlePeriod.start_date <= end,
                RiderSalarySettlePeriod.end_date >= start,
                _site_filter(RiderSalarySettlePeriod.site_id, site_ids),
            )
            .group_by(RiderSalarySettlePeriod.id)
            .order_by(RiderSalarySettlePeriod.end_date.asc())
        )
        rows = (await db.execute(stmt)).all()
        if not rows:
            return None
        items = []
        for period, cnt in rows[:_ATTENTION_LIMIT]:
            items.append({
                'period_id': period.id,
                'site_id': period.site_id,
                'rider_id': period.rider_id,
                'range': period_range_text(period.start_date, period.end_date),
                'status': period.status,
                'stale_count': int(cnt or 0),
            })
        return DashboardAttentionBlock(
            key='stale_periods',
            title='需重算周期',
            count=len(rows),
            items=items,
            link='/rider-salary/period?status=open&stale=1',
        )

    async def _no_plan_days(
        self,
        db: AsyncSession,
        site_ids: set[int] | None,
        start: date,
        end: date,
    ) -> DashboardAttentionBlock | None:
        rider_ids_stmt = select(RiderSalaryRider.id).where(
            RiderSalaryRider.deleted == 0,
            _site_filter(RiderSalaryRider.site_id, site_ids),
        )
        stmt = (
            select(
                RiderSalaryPayrollDaily.rider_id,
                func.count(RiderSalaryPayrollDaily.id),
            )
            .where(
                RiderSalaryPayrollDaily.day_status == DayStatus.no_plan.value,
                RiderSalaryPayrollDaily.biz_date >= start,
                RiderSalaryPayrollDaily.biz_date <= end,
                RiderSalaryPayrollDaily.deleted == 0,
                RiderSalaryPayrollDaily.rider_id.in_(rider_ids_stmt),
            )
            .group_by(RiderSalaryPayrollDaily.rider_id)
            .order_by(func.count(RiderSalaryPayrollDaily.id).desc())
        )
        rows = (await db.execute(stmt)).all()
        if not rows:
            return None
        rider_map = await _riders_by_id(db, [row[0] for row in rows[:_ATTENTION_LIMIT]])
        items = []
        for rider_id, cnt in rows[:_ATTENTION_LIMIT]:
            rider = rider_map.get(rider_id)
            items.append({
                'rider_id': rider_id,
                'job_no': getattr(rider, 'job_no', ''),
                'name': getattr(rider, 'name', ''),
                'count': int(cnt or 0),
            })
        return DashboardAttentionBlock(
            key='no_plan_days',
            title='无方案日',
            count=len(rows),
            items=items,
            link='/rider-salary/calendar',
        )

    async def _pending_advances(
        self,
        db: AsyncSession,
        site_ids: set[int] | None,
        pending_count: int,
    ) -> DashboardAttentionBlock | None:
        if pending_count <= 0:
            return None
        rows = list(
            (
                await db.scalars(
                    select(RiderSalaryAdvance)
                    .where(
                        RiderSalaryAdvance.status == AdvanceStatus.pending.value,
                        RiderSalaryAdvance.deleted == 0,
                        _site_filter(RiderSalaryAdvance.site_id, site_ids),
                    )
                    .order_by(RiderSalaryAdvance.submit_time.asc(), RiderSalaryAdvance.id.asc())
                    .limit(_ATTENTION_LIMIT)
                )
            ).all()
        )
        rider_map = await _riders_by_id(db, [row.rider_id for row in rows])
        items = [
            {
                'id': row.id,
                'rider_id': row.rider_id,
                'rider_name': getattr(rider_map.get(row.rider_id), 'name', ''),
                'amount': str(q2(row.amount)),
                'submit_time': timezone.to_str(row.submit_time) if row.submit_time else None,
            }
            for row in rows
        ]
        return DashboardAttentionBlock(
            key='pending_advances',
            title='待审核预支',
            count=pending_count,
            items=items,
            link='/rider-salary/advance?status=pending',
        )

    async def _import_gaps(
        self,
        db: AsyncSession,
        site_ids: set[int] | None,
        start: date,
        end: date,
        today: date,
    ) -> DashboardAttentionBlock | None:
        gap_end = min(end, today - timedelta(days=1))
        if gap_end < start:
            return None
        sites = list(
            (
                await db.scalars(
                    select(RiderSalarySite).where(
                        RiderSalarySite.deleted == 0,
                        _site_filter(RiderSalarySite.id, site_ids),
                    )
                )
            ).all()
        )
        items: list[dict[str, Any]] = []
        total = 0
        for site in sites:
            batches = list(
                (
                    await db.scalars(
                        select(RiderSalaryImportBatch).where(
                            RiderSalaryImportBatch.site_id == site.id,
                            RiderSalaryImportBatch.deleted == 0,
                        )
                    )
                ).all()
            )
            covered: set[date] = set()
            for batch in batches:
                if batch.date_from is None or batch.date_to is None:
                    continue
                covered.update(iter_dates(max(batch.date_from, start), min(batch.date_to, gap_end)))
            order_dates = set(
                (
                    await db.scalars(
                        select(RiderSalaryOrder.biz_date).where(
                            RiderSalaryOrder.site_id == site.id,
                            RiderSalaryOrder.biz_date >= start,
                            RiderSalaryOrder.biz_date <= gap_end,
                            RiderSalaryOrder.deleted == 0,
                        )
                    )
                ).all()
            )
            for day in iter_dates(start, gap_end):
                if day in covered or day in order_dates:
                    continue
                total += 1
                if len(items) < _ATTENTION_LIMIT:
                    items.append({'site_id': site.id, 'site_name': site.name, 'date': day.isoformat()})
        if total <= 0:
            return None
        return DashboardAttentionBlock(
            key='import_gaps',
            title='导入覆盖缺口',
            count=total,
            items=items,
            link='/rider-salary/order',
        )

    async def _abnormal_orders(
        self,
        db: AsyncSession,
        site_ids: set[int] | None,
        start: date,
        end: date,
    ) -> DashboardAttentionBlock | None:
        duration_sec = func.extract('epoch', RiderSalaryOrder.deliver_time - RiderSalaryOrder.order_time)
        abnormal_cond = or_(
            RiderSalaryOrder.status.in_([OrderStatus.abnormal.value, OrderStatus.refunded.value]),
            and_(RiderSalaryOrder.deliver_time.is_not(None), duration_sec > 3600),
        )
        total = int(
            await db.scalar(
                select(func.count())
                .select_from(RiderSalaryOrder)
                .where(
                    RiderSalaryOrder.biz_date >= start,
                    RiderSalaryOrder.biz_date <= end,
                    RiderSalaryOrder.deleted == 0,
                    _site_filter(RiderSalaryOrder.site_id, site_ids),
                    abnormal_cond,
                )
            )
            or 0
        )
        if total <= 0:
            return None
        matched = list(
            (
                await db.scalars(
                    select(RiderSalaryOrder)
                    .where(
                        RiderSalaryOrder.biz_date >= start,
                        RiderSalaryOrder.biz_date <= end,
                        RiderSalaryOrder.deleted == 0,
                        _site_filter(RiderSalaryOrder.site_id, site_ids),
                        abnormal_cond,
                    )
                    .order_by(RiderSalaryOrder.id.desc())
                    .limit(_ATTENTION_LIMIT)
                )
            ).all()
        )
        rider_map = await _riders_by_id(db, [row.rider_id for row in matched])
        items = []
        for row in matched:
            duration = None
            if row.deliver_time is not None and row.order_time is not None:
                duration = round((row.deliver_time - row.order_time).total_seconds() / 60, 1)
            items.append({
                'id': row.id,
                'order_no': row.order_no,
                'rider_id': row.rider_id,
                'rider_name': getattr(rider_map.get(row.rider_id), 'name', ''),
                'status': row.status,
                'duration_min': duration,
            })
        return DashboardAttentionBlock(
            key='abnormal_orders',
            title='异常订单',
            count=total,
            items=items,
            link='/rider-salary/order?status=abnormal',
        )

    async def _due_periods(
        self,
        db: AsyncSession,
        site_ids: set[int] | None,
        today: date,
    ) -> DashboardAttentionBlock | None:
        due_end = today + timedelta(days=3)
        rows = list(
            (
                await db.scalars(
                    select(RiderSalarySettlePeriod)
                    .where(
                        RiderSalarySettlePeriod.status == PeriodStatus.open.value,
                        RiderSalarySettlePeriod.end_date >= today,
                        RiderSalarySettlePeriod.end_date <= due_end,
                        RiderSalarySettlePeriod.deleted == 0,
                        _site_filter(RiderSalarySettlePeriod.site_id, site_ids),
                    )
                    .order_by(RiderSalarySettlePeriod.end_date.asc())
                )
            ).all()
        )
        if not rows:
            return None
        items = [
            {
                'period_id': row.id,
                'site_id': row.site_id,
                'rider_id': row.rider_id,
                'range': period_range_text(row.start_date, row.end_date),
                'end_date': row.end_date.isoformat(),
                'days_left': (row.end_date - today).days,
            }
            for row in rows[:_ATTENTION_LIMIT]
        ]
        return DashboardAttentionBlock(
            key='due_periods',
            title='即将到期周期',
            count=len(rows),
            items=items,
            link='/rider-salary/period?status=open',
        )

    async def _resigned_with_orders(
        self,
        db: AsyncSession,
        site_ids: set[int] | None,
        start: date,
        end: date,
    ) -> DashboardAttentionBlock | None:
        stmt = (
            select(RiderSalaryRider, func.count(RiderSalaryOrder.id))
            .join(RiderSalaryOrder, RiderSalaryOrder.rider_id == RiderSalaryRider.id)
            .where(
                RiderSalaryRider.status == RiderStatus.resigned.value,
                RiderSalaryRider.deleted == 0,
                RiderSalaryOrder.deleted == 0,
                RiderSalaryOrder.biz_date >= start,
                RiderSalaryOrder.biz_date <= end,
                _site_filter(RiderSalaryRider.site_id, site_ids),
            )
            .group_by(RiderSalaryRider.id)
            .order_by(func.count(RiderSalaryOrder.id).desc())
        )
        rows = (await db.execute(stmt)).all()
        if not rows:
            return None
        items = [
            {
                'rider_id': rider.id,
                'job_no': rider.job_no,
                'name': rider.name,
                'order_count': int(cnt or 0),
            }
            for rider, cnt in rows[:_ATTENTION_LIMIT]
        ]
        return DashboardAttentionBlock(
            key='resigned_with_orders',
            title='离职仍有本月订单',
            count=len(rows),
            items=items,
            link='/rider-salary/rider?status=resigned',
        )

    async def _trend(
        self,
        db: AsyncSession,
        site_ids: set[int] | None,
        today: date,
    ) -> list[DashboardTrendPoint]:
        start = today - timedelta(days=29)
        order_rows = (
            await db.execute(
                select(RiderSalaryOrder.biz_date, func.count(RiderSalaryOrder.id))
                .where(
                    RiderSalaryOrder.biz_date >= start,
                    RiderSalaryOrder.biz_date <= today,
                    RiderSalaryOrder.deleted == 0,
                    _site_filter(RiderSalaryOrder.site_id, site_ids),
                )
                .group_by(RiderSalaryOrder.biz_date)
            )
        ).all()
        order_map = {row[0]: int(row[1] or 0) for row in order_rows}
        rider_ids_stmt = select(RiderSalaryRider.id).where(
            RiderSalaryRider.deleted == 0,
            _site_filter(RiderSalaryRider.site_id, site_ids),
        )
        amount_rows = (
            await db.execute(
                select(
                    RiderSalaryPayrollDaily.biz_date,
                    func.coalesce(func.sum(RiderSalaryPayrollDaily.formula_amount), 0),
                )
                .where(
                    RiderSalaryPayrollDaily.biz_date >= start,
                    RiderSalaryPayrollDaily.biz_date <= today,
                    RiderSalaryPayrollDaily.deleted == 0,
                    RiderSalaryPayrollDaily.rider_id.in_(rider_ids_stmt),
                )
                .group_by(RiderSalaryPayrollDaily.biz_date)
            )
        ).all()
        amount_map = {row[0]: q2(row[1] or ZERO) for row in amount_rows}
        if not order_map and not amount_map:
            return []
        points: list[DashboardTrendPoint] = [
            DashboardTrendPoint(
                date=day,
                order_count=order_map.get(day, 0),
                formula_amount=amount_map.get(day, ZERO),
            )
            for day in iter_dates(start, today)
        ]
        return points

    async def _top_riders(
        self,
        db: AsyncSession,
        site_ids: set[int] | None,
        start: date,
        end: date,
    ) -> DashboardTopRiders:
        bound_ids = set(
            (
                await db.scalars(
                    select(RiderSalaryRiderPlanBinding.rider_id).where(RiderSalaryRiderPlanBinding.deleted == 0)
                )
            ).all()
        )
        if not bound_ids:
            return DashboardTopRiders()
        stmt = (
            select(RiderSalaryRider, func.count(RiderSalaryOrder.id))
            .outerjoin(
                RiderSalaryOrder,
                and_(
                    RiderSalaryOrder.rider_id == RiderSalaryRider.id,
                    RiderSalaryOrder.biz_date >= start,
                    RiderSalaryOrder.biz_date <= end,
                    RiderSalaryOrder.deleted == 0,
                ),
            )
            .where(
                RiderSalaryRider.status == RiderStatus.on_job.value,
                RiderSalaryRider.deleted == 0,
                RiderSalaryRider.id.in_(list(bound_ids)),
                _site_filter(RiderSalaryRider.site_id, site_ids),
            )
            .group_by(RiderSalaryRider.id)
        )
        rows = (await db.execute(stmt)).all()
        if not rows:
            return DashboardTopRiders()
        ranked = sorted(
            [
                DashboardRiderRank(rider_id=rider.id, job_no=rider.job_no, name=rider.name, order_count=int(cnt or 0))
                for rider, cnt in rows
            ],
            key=lambda item: (-item.order_count, item.rider_id),
        )
        top = ranked[:10]
        bottom = sorted(ranked, key=lambda item: (item.order_count, item.rider_id))[:5]
        return DashboardTopRiders(top=top, bottom=bottom)


def _site_filter(column: Any, site_ids: set[int] | None) -> Any:
    if site_ids is None:
        return true()
    if not site_ids:
        return column.in_([-1])
    return column.in_(list(site_ids))


async def _riders_by_id(db: AsyncSession, ids: list[int]) -> dict[int, RiderSalaryRider]:
    ids = [pk for pk in ids if pk]
    if not ids:
        return {}
    rows = await db.scalars(select(RiderSalaryRider).where(RiderSalaryRider.id.in_(ids)))
    return {row.id: row for row in rows.all()}


dashboard_service: DashboardService = DashboardService()
