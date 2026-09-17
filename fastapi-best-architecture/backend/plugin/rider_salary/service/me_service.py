from datetime import date
from decimal import Decimal

from fastapi import Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.advance import advance_dao
from backend.plugin.rider_salary.crud.plan import plan_dao
from backend.plugin.rider_salary.crud.plan_item import plan_item_dao
from backend.plugin.rider_salary.crud.plan_version import plan_version_dao
from backend.plugin.rider_salary.crud.rider_plan_binding import rider_plan_binding_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.enums import BindingType, EmployType, NoticeStatus, PayrollStatus, RiderStatus
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.notice import RiderSalaryNotice
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.schema.advance import CreateMeAdvanceParam, GetAdvanceDetail
from backend.plugin.rider_salary.schema.calendar import GetCalendarDayDetail, GetCalendarMonth
from backend.plugin.rider_salary.schema.me import (
    GetMeAdjustmentItem,
    GetMeAdvanceLimit,
    GetMePayrollEstimate,
    GetMePlan,
    GetMePlanBinding,
    GetMeProfile,
    MeCurrentPlan,
    MePlanItem,
)
from backend.plugin.rider_salary.schema.notice import GetNoticeDetail
from backend.plugin.rider_salary.service.advance_service import advance_service, resolve_advance_limit
from backend.plugin.rider_salary.service.calc_service import calculate_rider_period
from backend.plugin.rider_salary.service.calendar_service import (
    calendar_service,
    parse_month,
    period_range_text,
    pick_effective_payroll,
    resolve_period,
)
from backend.plugin.rider_salary.service.rider_service import resolve_effective_plans
from backend.plugin.rider_salary.utils.item_summary import build_item_summary
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

ZERO = Decimal('0.00')
_STORED = {PayrollStatus.draft.value, PayrollStatus.finalized.value, PayrollStatus.paid.value}


class MeService:
    """骑手端"""

    async def profile(self, *, db: AsyncSession, rider: RiderSalaryRider) -> GetMeProfile:
        site = await site_dao.get(db, rider.site_id)
        today = timezone.now().date()
        segments = await resolve_effective_plans(db, rider.id, today, today)
        current = None
        if segments and segments[0].plan_version_id:
            seg = segments[0]
            version = await plan_version_dao.get(db, seg.plan_version_id)
            plan = await plan_dao.get(db, version.plan_id) if version else None
            bindings = await rider_plan_binding_dao.get_by_rider(db, rider.id)
            covering = [
                row
                for row in bindings
                if row.plan_version_id == seg.plan_version_id
                and row.start_date <= today
                and (row.end_date is None or row.end_date >= today)
            ]
            covering.sort(key=lambda row: (0 if row.binding_type == BindingType.override.value else 1, row.id))
            bind = covering[0] if covering else None
            current = MeCurrentPlan(
                version_id=seg.plan_version_id,
                plan_name=getattr(plan, 'name', None),
                short_name=getattr(plan, 'short_name', None),
                version_no=getattr(version, 'version_no', None),
                mode_tag=getattr(version, 'mode_tag', None),
                start_date=bind.start_date if bind is not None else seg.start,
                end_date=bind.end_date if bind is not None else None,
            )
        limit = resolve_advance_limit(
            rider.advance_limit,
            getattr(site, 'advance_limit', None) if site else None,
        )
        in_flight = await advance_dao.list_in_flight(db, rider.id)
        try:
            employ_label = EmployType(rider.employ_type).label
        except ValueError:
            employ_label = rider.employ_type
        return GetMeProfile(
            rider_id=rider.id,
            job_no=rider.job_no,
            name=rider.name,
            site_id=rider.site_id,
            site_name=getattr(site, 'name', '') or '',
            employ_type=rider.employ_type,
            employ_type_label=employ_label,
            hire_date=rider.hire_date,
            current_plan=current,
            advance_limit=limit,
            has_in_flight_advance=bool(in_flight),
        )

    async def calendar(self, *, db: AsyncSession, rider: RiderSalaryRider, month: str | None) -> GetCalendarMonth:
        return await calendar_service.build_month(db, rider.id, month, for_rider=True)

    async def day(self, *, db: AsyncSession, rider: RiderSalaryRider, biz_date: date) -> GetCalendarDayDetail:
        return await calendar_service.build_day(db, rider.id, biz_date, for_rider=True)

    async def payroll_estimate(self, *, db: AsyncSession, rider: RiderSalaryRider) -> GetMePayrollEstimate:
        today = timezone.now().date()
        period = await resolve_period(db, rider.site_id, rider.id, today)
        range_text = period_range_text(period.start_date, period.end_date)
        stored = None
        if getattr(period, 'id', None):
            rows = list(
                (
                    await db.scalars(
                        select(RiderSalaryPayroll).where(
                            RiderSalaryPayroll.period_id == period.id,
                            RiderSalaryPayroll.rider_id == rider.id,
                            RiderSalaryPayroll.deleted == 0,
                        )
                    )
                ).all()
            )
            stored = pick_effective_payroll(rows)
            stale_draft = any(row.status == PayrollStatus.draft.value and row.stale for row in rows)
            if stale_draft or (stored is not None and stored.status not in _STORED):
                stored = None
        if stored is not None:
            return GetMePayrollEstimate(
                period_range=range_text,
                period_status=period.status,
                order_count=stored.order_count,
                gross=q2(stored.gross),
                deduction_total=q2(stored.deduction_total),
                advance_deduction_estimate=q2(stored.advance_deduction),
                net_estimate=q2(stored.net),
                is_estimate=False,
                updated_at=stored.calc_time or getattr(stored, 'updated_time', None),
            )
        result = await calculate_rider_period(db, rider_id=rider.id, period=period, persist=False)
        return GetMePayrollEstimate(
            period_range=range_text,
            period_status=period.status,
            order_count=result.order_count,
            gross=q2(result.gross),
            deduction_total=q2(result.deduction_total),
            advance_deduction_estimate=q2(result.advance_deductible),
            net_estimate=q2(result.net),
            is_estimate=True,
            updated_at=timezone.now(),
        )

    async def adjustments(
        self,
        *,
        db: AsyncSession,
        rider: RiderSalaryRider,
        month: str | None,
    ) -> list[GetMeAdjustmentItem]:
        _, start, end = parse_month(month)
        rows = list(
            (
                await db.scalars(
                    select(RiderSalaryAdjustment)
                    .where(
                        RiderSalaryAdjustment.rider_id == rider.id,
                        RiderSalaryAdjustment.biz_date >= start,
                        RiderSalaryAdjustment.biz_date <= end,
                        RiderSalaryAdjustment.deleted == 0,
                    )
                    .order_by(RiderSalaryAdjustment.biz_date.desc(), RiderSalaryAdjustment.id.desc())
                )
            ).all()
        )
        if not rows:
            return []
        subjects = {
            row.id: row
            for row in (
                await db.scalars(
                    select(RiderSalarySubject).where(
                        RiderSalarySubject.id.in_({item.subject_id for item in rows}),
                        RiderSalarySubject.deleted == 0,
                    )
                )
            ).all()
        }
        result: list[GetMeAdjustmentItem] = []
        for row in rows:
            sub = subjects.get(row.subject_id)
            signed = q2(row.signed_amount if row.signed_amount is not None else row.amount)
            direction = getattr(sub, 'direction', '') or ''
            result.append(
                GetMeAdjustmentItem(
                    id=row.id,
                    biz_date=row.biz_date,
                    subject_name=getattr(sub, 'name', str(row.subject_id)),
                    direction=direction,
                    amount=signed,
                    remark=row.remark,
                )
            )
        return result

    async def plan(self, *, db: AsyncSession, rider: RiderSalaryRider) -> GetMePlan:
        today = timezone.now().date()
        bindings = await rider_plan_binding_dao.get_by_rider(db, rider.id)
        upcoming = [row for row in bindings if row.end_date is None or row.end_date >= today]
        upcoming.sort(key=lambda row: row.start_date)
        result: list[GetMePlanBinding] = []
        for row in upcoming:
            version = await plan_version_dao.get(db, row.plan_version_id)
            plan = await plan_dao.get(db, version.plan_id) if version else None
            items = await plan_item_dao.list_by_version(db, row.plan_version_id) if version else []
            subject_ids = {item.subject_id for item in items}
            subjects: dict[int, RiderSalarySubject] = {}
            if subject_ids:
                subject_rows = await db.scalars(
                    select(RiderSalarySubject).where(
                        RiderSalarySubject.id.in_(subject_ids),
                        RiderSalarySubject.deleted == 0,
                    )
                )
                subjects = {sub.id: sub for sub in subject_rows.all()}
            is_current = row.start_date <= today and (row.end_date is None or row.end_date >= today)
            result.append(
                GetMePlanBinding(
                    plan_version_id=row.plan_version_id,
                    plan_name=getattr(plan, 'name', '') or '',
                    short_name=getattr(plan, 'short_name', '') or '',
                    color=getattr(plan, 'color', '') or '',
                    version_no=getattr(version, 'version_no', 0) or 0,
                    mode_tag=getattr(version, 'mode_tag', '') or '',
                    binding_type=row.binding_type,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    is_current=is_current,
                    items=[
                        MePlanItem(
                            name=item.name,
                            subject_name=getattr(subjects.get(item.subject_id), 'name', str(item.subject_id)),
                            summary=build_item_summary(
                                remark=item.remark,
                                condition_expr=item.condition_expr,
                                formula_expr=item.formula_expr,
                                condition_json=item.condition_json,
                                formula_json=item.formula_json,
                            ),
                        )
                        for item in items
                        if item.enabled
                    ],
                )
            )
        return GetMePlan(bindings=result)

    async def notices(self, *, db: AsyncSession, rider: RiderSalaryRider) -> list[GetNoticeDetail]:
        rows = list(
            (
                await db.scalars(
                    select(RiderSalaryNotice)
                    .where(
                        RiderSalaryNotice.status == NoticeStatus.published.value,
                        RiderSalaryNotice.deleted == 0,
                        or_(
                            RiderSalaryNotice.site_id.is_(None),
                            RiderSalaryNotice.site_id == rider.site_id,
                        ),
                    )
                    .order_by(RiderSalaryNotice.publish_time.desc(), RiderSalaryNotice.id.desc())
                )
            ).all()
        )
        return [GetNoticeDetail.model_validate(row) for row in rows]

    async def advance_limit(self, *, db: AsyncSession, rider: RiderSalaryRider) -> GetMeAdvanceLimit:
        data = await advance_service.limit_for_rider(db=db, rider=rider)
        return GetMeAdvanceLimit(**data)

    async def advances(self, *, db: AsyncSession, rider: RiderSalaryRider) -> list[GetAdvanceDetail]:
        return await advance_service.list_for_rider(db=db, rider_id=rider.id)

    async def create_advance(
        self,
        *,
        db: AsyncSession,
        request: Request,
        rider: RiderSalaryRider,
        obj: CreateMeAdvanceParam,
    ) -> GetAdvanceDetail:
        if rider.status == RiderStatus.resigned:
            raise errors.RequestError(msg='离职骑手不能申请预支')
        advance = await advance_service.submit_for_rider(db=db, request=request, rider=rider, obj=obj)
        items = await advance_service.list_for_rider(db=db, rider_id=rider.id)
        for item in items:
            if item.id == advance.id:
                return item
        return GetAdvanceDetail.model_validate(advance)

    async def cancel_advance(
        self,
        *,
        db: AsyncSession,
        request: Request,
        rider: RiderSalaryRider,
        pk: int,
    ) -> None:
        await advance_service.cancel_for_rider(db=db, request=request, rider=rider, pk=pk)


me_service: MeService = MeService()
