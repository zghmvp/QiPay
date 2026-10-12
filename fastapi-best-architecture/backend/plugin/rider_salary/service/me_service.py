import json

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from fastapi import Request
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.admin.crud.crud_user import user_dao
from backend.app.admin.schema.user_password_history import CreateUserPasswordHistoryParam
from backend.app.admin.service.user_password_history_service import password_security_service
from backend.app.admin.utils.password_security import password_verify, validate_new_password
from backend.common.exception import errors
from backend.plugin.rider_salary.crud.advance import advance_dao
from backend.plugin.rider_salary.crud.notice import notice_list_order_by
from backend.plugin.rider_salary.crud.payroll_detail import payroll_detail_dao
from backend.plugin.rider_salary.crud.plan import plan_dao
from backend.plugin.rider_salary.crud.plan_item import plan_item_dao
from backend.plugin.rider_salary.crud.plan_version import plan_version_dao
from backend.plugin.rider_salary.crud.rider import rider_dao
from backend.plugin.rider_salary.crud.rider_plan_binding import rider_plan_binding_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.enums import (
    AdvanceStatus,
    BindingType,
    CalcStage,
    DetailSource,
    EmployType,
    LabeledStrEnum,
    NoticeStatus,
    PayrollKind,
    PayrollStatus,
    PeriodStatus,
    RiderStatus,
)
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.model.notice import RiderSalaryNotice
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.schema.advance import CreateMeAdvanceParam, GetAdvanceDetail
from backend.plugin.rider_salary.schema.calendar import GetCalendarDayDetail, GetCalendarMonth
from backend.plugin.rider_salary.schema.me import (
    ChangeMePasswordParam,
    GetMeAdjustmentItem,
    GetMeAdvanceLimit,
    GetMePayrollEstimate,
    GetMePayslipDetail,
    GetMePayslipItem,
    GetMePayslipLine,
    GetMePlan,
    GetMePlanBinding,
    GetMeProfile,
    MeCurrentPlan,
    MePlanItem,
)
from backend.plugin.rider_salary.schema.notice import GetNoticeDetail
from backend.plugin.rider_salary.schema.rider import UpdateRiderParam
from backend.plugin.rider_salary.service.advance_service import advance_service, resolve_advance_limit
from backend.plugin.rider_salary.service.calc_service import calculate_rider_period
from backend.plugin.rider_salary.service.calendar_service import (
    calendar_service,
    parse_month,
    period_range_text,
    resolve_period,
)
from backend.plugin.rider_salary.service.payroll_service import preview_advance_deduction
from backend.plugin.rider_salary.service.payroll_view import RiderPayrollView, build_rider_views, pick_effective_payroll
from backend.plugin.rider_salary.service.rider_service import resolve_effective_plans
from backend.plugin.rider_salary.utils.lifecycle import is_resigned
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.read_grace import assert_rider_can_write, resigned_read_until
from backend.plugin.rider_salary.utils.recalc import (
    ESTIMATE_CACHE_TTL_SECONDS,
    estimate_cache_key,
    get_cached_text,
    set_cached_text,
)
from backend.utils.timezone import timezone

ZERO = Decimal('0.00')
_STORED = {PayrollStatus.draft.value, PayrollStatus.finalized.value, PayrollStatus.paid.value}


def _estimate_json_default(value: object) -> str:
    """保留时区的时间，金额按十进制字符串。"""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, 'f')
    raise TypeError


def _dump_estimate(data: GetMePayrollEstimate) -> str:
    return json.dumps(data.model_dump(), ensure_ascii=False, default=_estimate_json_default)


async def _cached_estimate(rider_id: int, *, period_range: str, period_status: str) -> GetMePayrollEstimate | None:
    """命中且仍对应当前周期时返回预估，否则当作未命中。"""
    raw = await get_cached_text(estimate_cache_key(rider_id))
    if raw is None:
        return None
    try:
        data = GetMePayrollEstimate.model_validate_json(raw)
    except (ValidationError, ValueError):
        return None
    if not data.is_estimate or data.period_range != period_range or data.period_status != period_status:
        return None
    return data


async def _store_estimate(rider_id: int, data: GetMePayrollEstimate) -> None:
    """只缓存实时预估。已落库的薪资单每次仍以库为准。"""
    if not data.is_estimate:
        return
    await set_cached_text(
        estimate_cache_key(rider_id),
        _dump_estimate(data),
        ttl_seconds=ESTIMATE_CACHE_TTL_SECONDS,
    )


def _estimate_draft_kind(period: object) -> str:
    """与算薪覆盖草稿的类型一致：补发中看补发草稿，其余看正常草稿。"""
    if getattr(period, 'status', None) == PeriodStatus.reopened.value:
        return PayrollKind.supplement.value
    return PayrollKind.normal.value


def _latest_stale_draft(rows: list[object], kind: str) -> object | None:
    """本期需重算、且会被覆盖的那张草稿。"""
    matched = [
        row
        for row in rows
        if getattr(row, 'status', None) == PayrollStatus.draft.value
        and bool(getattr(row, 'stale', False))
        and getattr(row, 'kind', None) == kind
        and int(getattr(row, 'deleted', 0) or 0) == 0
    ]
    if not matched:
        return None
    matched.sort(key=lambda row: int(getattr(row, 'id', 0) or 0), reverse=True)
    return matched[0]


_SETTLED_STATUS = {PayrollStatus.finalized.value, PayrollStatus.paid.value}
_STAGE_ORDER = {
    CalcStage.per_order.value: 0,
    CalcStage.daily.value: 1,
    CalcStage.period.value: 2,
}


def _enum_label(enum_cls: type[LabeledStrEnum], value: object) -> str:
    """枚举中文名。无法识别时退回原值。"""
    text = '' if value is None else str(value)
    if not text:
        return '—'
    try:
        return enum_cls(text).label
    except ValueError:
        return text


def settled_effective_views(
    payrolls: Sequence[object],
    details: Sequence[object] | None = None,
) -> list[RiderPayrollView]:
    """有效单读层里，只留下已定稿或已发薪的那张。

    :param payrolls: 同一骑手的薪资单
    :param details: 这些薪资单的明细
    :return:
    """
    chosen: list[RiderPayrollView] = []
    for view in build_rider_views(payrolls, details):
        payroll = view.effective
        if payroll is None or getattr(payroll, 'status', None) not in _SETTLED_STATUS:
            continue
        chosen.append(view)
    return chosen


@dataclass
class _LineDraft:
    """合并前的明细行，科目名稍后补上。"""

    stage: str
    subject_id: int
    source: str
    amount: Decimal
    line_count: int
    subject_name: str = ''


def aggregate_slip_lines(details: Sequence[object]) -> list[_LineDraft]:
    """按阶段、科目、来源合并有效单明细。不读取计算过程。

    :param details: 有效单上的明细
    :return:
    """
    buckets: dict[tuple[str, int, str], _LineDraft] = {}
    for row in details:
        if int(getattr(row, 'deleted', 0) or 0):
            continue
        stage = str(getattr(row, 'stage', '') or '')
        source = str(getattr(row, 'source', '') or '')
        subject_id = int(getattr(row, 'subject_id', 0) or 0)
        amount = q2(getattr(row, 'amount', ZERO) or ZERO)
        key = (stage, subject_id, source)
        found = buckets.get(key)
        if found is None:
            buckets[key] = _LineDraft(
                stage=stage,
                subject_id=subject_id,
                source=source,
                amount=amount,
                line_count=1,
            )
        else:
            found.amount = q2(found.amount + amount)
            found.line_count += 1
    lines = list(buckets.values())
    lines.sort(key=lambda line: (_STAGE_ORDER.get(line.stage, 9), line.subject_id, line.source))
    return lines


def _slip_sort_key(view: RiderPayrollView, period: object | None) -> tuple[date, date, int, int]:
    end = getattr(period, 'end_date', None)
    start = getattr(period, 'start_date', None)
    if not isinstance(end, date):
        end = date.min
    if not isinstance(start, date):
        start = date.min
    payroll = view.effective
    payroll_id = int(getattr(payroll, 'id', 0) or 0)
    return end, start, view.period_id, payroll_id


def _period_text(period: object | None) -> tuple[str, str, str]:
    """周期区间、状态、状态中文。"""
    if period is None:
        return '周期资料缺失', '', '—'
    status = str(getattr(period, 'status', '') or '')
    return period_range_text(period.start_date, period.end_date), status, _enum_label(PeriodStatus, status)


def _slip_item(view: RiderPayrollView, period: object | None) -> GetMePayslipItem:
    payroll = view.effective
    if payroll is None:
        raise errors.NotFoundError(msg='工资条不存在或已失效')
    period_range, period_status, period_status_label = _period_text(period)
    return GetMePayslipItem(
        id=int(payroll.id),
        period_id=view.period_id,
        period_range=period_range,
        period_status=period_status,
        period_status_label=period_status_label,
        kind=str(payroll.kind),
        kind_label=_enum_label(PayrollKind, payroll.kind),
        status=str(payroll.status),
        status_label=_enum_label(PayrollStatus, payroll.status),
        order_count=int(getattr(payroll, 'order_count', 0) or 0),
        gross=q2(payroll.gross),
        deduction_total=q2(payroll.deduction_total),
        advance_deduction=q2(payroll.advance_deduction),
        net=q2(payroll.net),
        calc_time=getattr(payroll, 'calc_time', None),
    )


def _to_slip_lines(lines: Sequence[_LineDraft]) -> list[GetMePayslipLine]:
    return [
        GetMePayslipLine(
            stage=line.stage,
            stage_label=_enum_label(CalcStage, line.stage),
            subject_name=line.subject_name or f'科目{line.subject_id}',
            source=line.source,
            source_label=_enum_label(DetailSource, line.source),
            amount=line.amount,
            line_count=line.line_count,
        )
        for line in lines
    ]


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
        try:
            status_label = RiderStatus(rider.status).label
        except ValueError:
            status_label = rider.status
        read_only = is_resigned(rider)
        return GetMeProfile(
            rider_id=rider.id,
            job_no=rider.job_no,
            name=rider.name,
            site_id=rider.site_id,
            site_name=getattr(site, 'name', '') or '',
            employ_type=rider.employ_type,
            employ_type_label=employ_label,
            hire_date=rider.hire_date,
            status=rider.status,
            status_label=status_label,
            leave_date=rider.leave_date,
            read_only=read_only,
            read_until=resigned_read_until(rider.leave_date) if read_only else None,
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
        rows: list[RiderSalaryPayroll] = []
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
        cached = await _cached_estimate(rider.id, period_range=range_text, period_status=period.status)
        if cached is not None:
            return cached
        result = await calculate_rider_period(db, rider_id=rider.id, period=period, persist=False)
        gross = q2(result.gross)
        deduction_total = q2(result.deduction_total)
        advance = q2(result.advance_deductible)
        net = q2(result.net)
        if rows and any(row.status == PayrollStatus.draft.value and row.stale for row in rows):
            occupied = await self._stale_draft_advance_estimate(
                db,
                rider_id=rider.id,
                period=period,
                rows=rows,
                cap=q2(max(gross - deduction_total, ZERO)),
            )
            if occupied is not None:
                advance = occupied
                net = q2(gross - deduction_total - advance)
        estimate = GetMePayrollEstimate(
            period_range=range_text,
            period_status=period.status,
            order_count=result.order_count,
            gross=gross,
            deduction_total=deduction_total,
            advance_deduction_estimate=advance,
            net_estimate=net,
            is_estimate=True,
            updated_at=timezone.now(),
        )
        await _store_estimate(rider.id, estimate)
        return estimate

    async def _stale_draft_advance_estimate(
        self,
        db: AsyncSession,
        *,
        rider_id: int,
        period: object,
        rows: list[RiderSalaryPayroll],
        cap: Decimal,
    ) -> Decimal | None:
        """内存预估把本草稿已占用的预支加回后再抵扣，不修改库里的 remaining_amount。"""
        draft = _latest_stale_draft(list(rows), _estimate_draft_kind(period))
        if draft is None or not getattr(draft, 'id', None):
            return None
        details = await payroll_detail_dao.list_by_payroll(db, int(draft.id))
        occupied = [row for row in details if getattr(row, 'source', None) == DetailSource.advance.value]
        if not occupied:
            return None
        advances = list(
            (
                await db.scalars(
                    select(RiderSalaryAdvance).where(
                        RiderSalaryAdvance.rider_id == rider_id,
                        RiderSalaryAdvance.status == AdvanceStatus.paid.value,
                        RiderSalaryAdvance.deleted == 0,
                    )
                )
            ).all()
        )
        return preview_advance_deduction(advances, occupied, cap)

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
                    .order_by(*notice_list_order_by())
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
        assert_rider_can_write(rider, action='advance')
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
        assert_rider_can_write(rider, action='cancel')
        await advance_service.cancel_for_rider(db=db, request=request, rider=rider, pk=pk)

    async def payslips(self, *, db: AsyncSession, rider: RiderSalaryRider) -> list[GetMePayslipItem]:
        """按周期列出已定稿或已发薪的有效工资条。只读，不预估、不写周期。

        :param db: 数据库会话
        :param rider: 当前骑手
        :return:
        """
        payrolls = list(
            (
                await db.scalars(
                    select(RiderSalaryPayroll).where(
                        RiderSalaryPayroll.rider_id == rider.id,
                        RiderSalaryPayroll.deleted == 0,
                    )
                )
            ).all()
        )
        views = settled_effective_views(payrolls)
        if not views:
            return []
        periods = await self._periods_by_id(db, {view.period_id for view in views})
        ordered = sorted(
            views,
            key=lambda view: _slip_sort_key(view, periods.get(view.period_id)),
            reverse=True,
        )
        return [_slip_item(view, periods.get(view.period_id)) for view in ordered]

    async def payslip(self, *, db: AsyncSession, rider: RiderSalaryRider, pk: int) -> GetMePayslipDetail:
        """下钻一张有效且已定稿或已发薪的工资条。明细来自有效单读层，不含计算过程。

        :param db: 数据库会话
        :param rider: 当前骑手
        :param pk: 薪资单 ID
        :return:
        """
        target = await db.scalar(
            select(RiderSalaryPayroll).where(
                RiderSalaryPayroll.id == pk,
                RiderSalaryPayroll.rider_id == rider.id,
                RiderSalaryPayroll.deleted == 0,
            )
        )
        if target is None:
            raise errors.NotFoundError(msg='工资条不存在')
        payrolls = list(
            (
                await db.scalars(
                    select(RiderSalaryPayroll).where(
                        RiderSalaryPayroll.period_id == target.period_id,
                        RiderSalaryPayroll.rider_id == rider.id,
                        RiderSalaryPayroll.deleted == 0,
                    )
                )
            ).all()
        )
        payroll_ids = [int(row.id) for row in payrolls if getattr(row, 'id', None) is not None]
        details: list[RiderSalaryPayrollDetail] = []
        if payroll_ids:
            details = list(
                (
                    await db.scalars(
                        select(RiderSalaryPayrollDetail).where(
                            RiderSalaryPayrollDetail.payroll_id.in_(payroll_ids),
                            RiderSalaryPayrollDetail.deleted == 0,
                        )
                    )
                ).all()
            )
        view = next(
            (
                item
                for item in settled_effective_views(payrolls, details)
                if int(getattr(item.effective, 'id', 0) or 0) == pk
            ),
            None,
        )
        if view is None or view.effective is None:
            raise errors.NotFoundError(msg='工资条不存在或已失效')
        period = await db.scalar(
            select(RiderSalarySettlePeriod).where(
                RiderSalarySettlePeriod.id == view.period_id,
                RiderSalarySettlePeriod.deleted == 0,
            )
        )
        lines = aggregate_slip_lines(view.details)
        await self._fill_subject_names(db, lines)
        item = _slip_item(view, period)
        return GetMePayslipDetail(**item.model_dump(), lines=_to_slip_lines(lines))

    async def _periods_by_id(self, db: AsyncSession, period_ids: set[int]) -> dict[int, RiderSalarySettlePeriod]:
        if not period_ids:
            return {}
        rows = list(
            (
                await db.scalars(
                    select(RiderSalarySettlePeriod).where(
                        RiderSalarySettlePeriod.id.in_(period_ids),
                        RiderSalarySettlePeriod.deleted == 0,
                    )
                )
            ).all()
        )
        return {int(row.id): row for row in rows}

    async def _fill_subject_names(self, db: AsyncSession, lines: list[_LineDraft]) -> None:
        subject_ids = {line.subject_id for line in lines if line.subject_id}
        if not subject_ids:
            return
        rows = list(
            (
                await db.scalars(
                    select(RiderSalarySubject).where(
                        RiderSalarySubject.id.in_(subject_ids),
                        RiderSalarySubject.deleted == 0,
                    )
                )
            ).all()
        )
        names = {int(row.id): row.name for row in rows}
        for line in lines:
            line.subject_name = names.get(line.subject_id) or f'科目{line.subject_id}'

    async def change_password(self, *, db: AsyncSession, rider: RiderSalaryRider, obj: ChangeMePasswordParam) -> None:
        """修改本人密码并清除必须改密标记。保留当前登录，方便改密后继续访问。"""
        if rider.user_id is None:
            raise errors.RequestError(msg='该骑手尚未开通账号')
        if obj.new_password != obj.confirm_password:
            raise errors.RequestError(msg='两次密码输入不一致')
        if obj.new_password == obj.old_password:
            raise errors.RequestError(msg='新密码不能与当前密码相同')
        user = await user_dao.get(db, rider.user_id)
        if user is None or not user.password or not password_verify(obj.old_password, user.password):
            raise errors.RequestError(msg='原密码错误')
        await validate_new_password(db, int(user.id), obj.new_password)
        previous_hash = user.password
        await user_dao.reset_password(db, int(user.id), obj.new_password)
        await password_security_service.save_password_history(
            db,
            CreateUserPasswordHistoryParam(user_id=int(user.id), password=previous_hash),
        )
        await user_dao.update_password_changed_time(db, int(user.id))
        await rider_dao.update(db, rider.id, UpdateRiderParam(), must_change_password=False)


me_service: MeService = MeService()
