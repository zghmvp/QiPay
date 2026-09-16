from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.core.conf import settings
from backend.database.redis import redis_client
from backend.plugin.rider_salary.crud.payroll import payroll_dao
from backend.plugin.rider_salary.crud.payroll_daily import payroll_daily_dao
from backend.plugin.rider_salary.crud.payroll_detail import payroll_detail_dao
from backend.plugin.rider_salary.engine.context import (
    build_day_context,
    build_order_context,
    build_period_context,
    build_segment_context,
    iter_dates,
    trace_variables,
)
from backend.plugin.rider_salary.engine.evaluator import EvalError, evaluate_amount, evaluate_condition
from backend.plugin.rider_salary.engine.segments import PlanItemView, Segment, resolve_segments
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
from backend.plugin.rider_salary.model.day_flag import RiderSalaryDayFlag
from backend.plugin.rider_salary.model.import_batch import RiderSalaryImportBatch
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_daily import RiderSalaryPayrollDaily
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.rider_employ_history import RiderSalaryRiderEmployHistory
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.service.payroll_service import (
    ADVANCE_SUBJECT_ID,
    compute_advance_deduction,
    payroll_service,
)
from backend.plugin.rider_salary.utils.audit import audit_service
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

ZERO = Decimal('0.00')
CALC_LOCK_TTL = 120
SITE_LEVEL_RIDER_ID = 0


@dataclass
class CalcDetail:
    """内存明细"""

    rider_id: int
    subject_id: int
    amount: Decimal
    stage: str
    include_in_gross: bool
    source: str
    biz_date: date | None = None
    plan_version_id: int | None = None
    plan_item_id: int | None = None
    order_id: int | None = None
    calc_trace: dict[str, Any] = field(default_factory=dict)
    direction: str = SubjectDirection.bonus.value
    name: str = ''
    order_no: str | None = None


@dataclass
class CalcDaily:
    """内存日汇总"""

    rider_id: int
    biz_date: date
    plan_version_id: int | None
    order_count: int
    valid_order_count: int
    formula_amount: Decimal
    manual_bonus: Decimal
    manual_penalty: Decimal
    net_adjust: Decimal
    day_status: str
    period_id: int | None = None


@dataclass
class SegmentOrderCount:
    """方案段内有效单量（对照「周期有效单量」）"""

    plan_version_id: int
    start_date: date
    end_date: date
    plan_order_count: int


@dataclass
class CalcResult:
    """算薪结果"""

    rider_id: int
    period_id: int | None
    payroll_id: int | None
    order_count: int
    valid_order_count: int
    per_order_total: Decimal
    daily_total: Decimal
    period_total: Decimal
    bonus_total: Decimal
    penalty_total: Decimal
    gross: Decimal
    deduction_total: Decimal
    advance_deduction: Decimal
    advance_deductible: Decimal
    net: Decimal
    plan_version_ids: list[int]
    warnings: list[str]
    details: list[CalcDetail]
    dailies: list[CalcDaily]
    calc_version: int = 0
    stale: bool = False
    plan_order_count: int = 0
    segment_order_counts: list[SegmentOrderCount] | None = None


@dataclass
class CalcInput:
    """内存流水线入参"""

    rider_id: int
    site_id: int
    period_start: date
    period_end: date
    hire_date: date | None
    leave_date: date | None
    employ_type: str
    segments: list[Segment]
    orders: list[Any]
    day_flags: dict[date, Any]
    employ_history: list[Any]
    adjustments: list[Any]
    advances: list[Any]
    covered_dates: set[date]
    site_order_dates: set[date]
    persist_advance: bool = False
    period_id: int | None = None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    return value


def _trace(
    condition_expr: str,
    formula_expr: str,
    names: dict[str, Any],
    amount: Decimal,
    *,
    hit: bool,
) -> dict[str, Any]:
    variables = {
        key: _json_safe(val) for key, val in trace_variables(f'{condition_expr} {formula_expr}', names).items()
    }
    return {
        '条件': condition_expr,
        '条件结果': hit,
        '公式': formula_expr,
        '变量': variables,
        '结果': float(amount),
    }


def _sign(direction: str) -> Decimal:
    return Decimal(1) if direction == SubjectDirection.bonus.value else Decimal(-1)


def _employ_on(history: list[Any], default: str, day: date) -> str:
    matched = [
        row
        for row in history
        if getattr(row, 'start_date', day) <= day and (getattr(row, 'end_date', None) is None or day <= row.end_date)
    ]
    if not matched:
        return default
    matched.sort(key=lambda row: row.start_date, reverse=True)
    return matched[0].employ_type


def _is_completed(order: Any) -> bool:
    return getattr(order, 'status', None) == OrderStatus.completed.value


def _after_leave(leave_date: date | None, day: date) -> bool:
    return leave_date is not None and day > leave_date


def _enabled_items(segment: Segment, stage: str) -> list[PlanItemView]:
    items = [item for item in segment.items if item.enabled and item.stage == stage]
    items.sort(key=lambda item: (item.sort_order, item.id or 0))
    return items


def _eval_item(
    item: PlanItemView,
    names: dict[str, Any],
    warnings: list[str],
) -> tuple[bool, Decimal, dict[str, Any]]:
    condition_expr = item.condition_expr or 'True'
    formula_expr = item.formula_expr or '0'
    hit = evaluate_condition(condition_expr, names)
    if not hit:
        return False, ZERO, _trace(condition_expr, formula_expr, names, ZERO, hit=False)
    try:
        unsigned = evaluate_amount(formula_expr, names)
    except EvalError:
        warnings.append(f'方案项「{item.name}」公式求值失败，已按 0 计算')
        unsigned = ZERO
    signed = q2(unsigned * _sign(item.direction))
    return True, signed, _trace(condition_expr, formula_expr, names, unsigned, hit=True)


def run_calc_pipeline(data: CalcInput) -> CalcResult:  # ruff: ignore[complex-structure]
    """
    纲要 §3 算薪流水线（纯内存，供正式算薪与单测共用）
    """
    warnings: list[str] = []
    details: list[CalcDetail] = []
    rider_id = data.rider_id
    orders = list(data.orders)
    completed_all = [row for row in orders if _is_completed(row) and not _after_leave(data.leave_date, row.biz_date)]
    period_days = (data.period_end - data.period_start).days + 1
    attendance = {row.biz_date for row in completed_all}
    manual_bonus = ZERO
    manual_penalty = ZERO
    for adj in data.adjustments:
        signed = q2(getattr(adj, 'signed_amount', None) or ZERO)
        if signed == ZERO:
            amount = q2(getattr(adj, 'amount', ZERO) or ZERO)
            subject = getattr(adj, 'subject', None)
            direction = getattr(subject, 'direction', None) or getattr(adj, 'direction', SubjectDirection.bonus.value)
            include = bool(
                getattr(subject, 'include_in_gross', True)
                if subject is not None
                else getattr(adj, 'include_in_gross', True)
            )
            signed = amount if direction == SubjectDirection.bonus.value else q2(-amount)
            adj.signed_amount = signed
            adj.include_in_gross = include
            adj.direction = direction
        include = bool(getattr(adj, 'include_in_gross', True))
        direction = getattr(adj, 'direction', SubjectDirection.bonus.value)
        if include and direction == SubjectDirection.bonus.value:
            manual_bonus += signed
        elif include and direction == SubjectDirection.penalty.value:
            manual_penalty += signed

    period_ctx = build_period_context(
        period_days=period_days,
        order_count=len(orders),
        valid_order_count=len(completed_all),
        attendance_days=len(attendance),
        hire_date=data.hire_date,
        period_end=data.period_end,
        manual_bonus=q2(manual_bonus),
        manual_penalty=q2(manual_penalty),
        employ_type=data.employ_type,
    )
    accrued = ZERO
    per_order_total = ZERO
    daily_total = ZERO
    period_total = ZERO
    covered: dict[date, int] = {}
    segment_order_counts: list[SegmentOrderCount] = []
    for segment in data.segments:
        for day in iter_dates(segment.start_date, segment.end_date):
            covered[day] = segment.plan_version_id
            employ = _employ_on(data.employ_history, data.employ_type, day)
            day_ctx = build_day_context(data.site_id, day, data.day_flags.get(day), employ)
            day_orders = [row for row in orders if row.biz_date == day]
            completed = [row for row in day_orders if _is_completed(row) and not _after_leave(data.leave_date, day)]
            if _after_leave(data.leave_date, day) and any(_is_completed(row) for row in day_orders):
                warnings.append(f'骑手已于 {data.leave_date} 离职，该日订单未计薪')
            day_per_order = ZERO
            for order in completed:
                ctx = build_order_context(order, day_ctx)
                if ctx.pop('_missing_deliver', False):
                    msg = '字段「配送时长」为空，已按 0 计算'
                    if msg not in warnings:
                        warnings.append(msg)
                for item in _enabled_items(segment, CalcStage.per_order.value):
                    hit, amount, trace = _eval_item(item, ctx, warnings)
                    if not hit:
                        continue
                    details.append(
                        CalcDetail(
                            rider_id=rider_id,
                            subject_id=item.subject_id,
                            amount=amount,
                            stage=CalcStage.per_order.value,
                            include_in_gross=item.include_in_gross,
                            source=DetailSource.formula.value,
                            biz_date=day,
                            plan_version_id=segment.plan_version_id,
                            plan_item_id=item.id,
                            order_id=getattr(order, 'id', None),
                            calc_trace=trace,
                            direction=item.direction,
                            name=item.name,
                            order_no=getattr(order, 'order_no', None),
                        )
                    )
                    if item.include_in_gross:
                        accrued += amount
                        day_per_order += amount
                        per_order_total += amount
            day_agg = {
                **day_ctx,
                '日单量': float(len(completed)),
                '日有效单量': float(len(completed)),
                '日总单量': float(len(day_orders)),
                '日逐单金额': float(q2(day_per_order)),
                '用工类型': employ,
            }
            for item in _enabled_items(segment, CalcStage.daily.value):
                hit, amount, trace = _eval_item(item, day_agg, warnings)
                if not hit:
                    continue
                details.append(
                    CalcDetail(
                        rider_id=rider_id,
                        subject_id=item.subject_id,
                        amount=amount,
                        stage=CalcStage.daily.value,
                        include_in_gross=item.include_in_gross,
                        source=DetailSource.formula.value,
                        biz_date=day,
                        plan_version_id=segment.plan_version_id,
                        plan_item_id=item.id,
                        calc_trace=trace,
                        direction=item.direction,
                        name=item.name,
                    )
                )
                if item.include_in_gross:
                    accrued += amount
                    daily_total += amount
        plan_orders = [row for row in completed_all if segment.start_date <= row.biz_date <= segment.end_date]
        segment_order_counts.append(
            SegmentOrderCount(
                plan_version_id=segment.plan_version_id,
                start_date=segment.start_date,
                end_date=segment.end_date,
                plan_order_count=len(plan_orders),
            )
        )
        segment_days = (segment.end_date - segment.start_date).days + 1
        seg_ctx = build_segment_context(
            period_ctx,
            plan_order_count=len(plan_orders),
            segment_days=segment_days,
            accrued_gross=accrued,
            per_order_total=per_order_total,
        )
        for item in _enabled_items(segment, CalcStage.period.value):
            seg_ctx['本期已计金额'] = float(q2(accrued))
            seg_ctx['本期逐单金额'] = float(q2(per_order_total))
            hit, amount, trace = _eval_item(item, seg_ctx, warnings)
            if not hit:
                continue
            details.append(
                CalcDetail(
                    rider_id=rider_id,
                    subject_id=item.subject_id,
                    amount=amount,
                    stage=CalcStage.period.value,
                    include_in_gross=item.include_in_gross,
                    source=DetailSource.formula.value,
                    plan_version_id=segment.plan_version_id,
                    plan_item_id=item.id,
                    calc_trace=trace,
                    direction=item.direction,
                    name=item.name,
                )
            )
            if item.include_in_gross:
                accrued += amount
                period_total += amount

    no_plan_days: set[date] = set()
    for day in iter_dates(data.period_start, data.period_end):
        if day in covered:
            continue
        day_completed = [
            row
            for row in orders
            if row.biz_date == day and _is_completed(row) and not _after_leave(data.leave_date, day)
        ]
        if day_completed:
            no_plan_days.add(day)
            warnings.append(f'{day.isoformat()} 无生效方案，{len(day_completed)} 单未计薪')

    for adj in data.adjustments:
        signed = q2(getattr(adj, 'signed_amount', ZERO) or ZERO)
        include = bool(getattr(adj, 'include_in_gross', True))
        direction = getattr(adj, 'direction', SubjectDirection.bonus.value)
        details.append(
            CalcDetail(
                rider_id=rider_id,
                subject_id=int(getattr(adj, 'subject_id', 0) or 0),
                amount=signed,
                stage=CalcStage.daily.value if getattr(adj, 'biz_date', None) else CalcStage.period.value,
                include_in_gross=include,
                source=DetailSource.manual.value,
                biz_date=getattr(adj, 'biz_date', None),
                calc_trace={
                    '条件': 'True',
                    '条件结果': True,
                    '公式': '手工录入',
                    '变量': {},
                    '结果': float(signed),
                },
                direction=direction,
                name=getattr(getattr(adj, 'subject', None), 'name', None) or '手工奖惩',
            )
        )

    gross = q2(sum((row.amount for row in details if row.include_in_gross), ZERO))
    deduction_total = q2(
        sum(
            (
                abs(row.amount)
                for row in details
                if (not row.include_in_gross)
                and row.direction == SubjectDirection.penalty.value
                and row.source != DetailSource.advance.value
            ),
            ZERO,
        )
    )
    cap = q2(max(gross - deduction_total, ZERO))
    deductible, lines = compute_advance_deduction(data.advances, cap, persist=data.persist_advance)
    advance_deduction = ZERO
    if data.persist_advance:
        advance_deduction = deductible
        details.extend(
            CalcDetail(
                rider_id=rider_id,
                subject_id=ADVANCE_SUBJECT_ID,
                amount=q2(-line.amount),
                stage=CalcStage.period.value,
                include_in_gross=False,
                source=DetailSource.advance.value,
                calc_trace=line.calc_trace,
                direction=SubjectDirection.penalty.value,
                name='预支抵扣',
            )
            for line in lines
        )

    net = q2(gross - deduction_total - advance_deduction)
    bonus_total = q2(
        sum(
            (
                row.amount
                for row in details
                if row.source == DetailSource.manual.value
                and row.include_in_gross
                and row.direction == SubjectDirection.bonus.value
            ),
            ZERO,
        )
    )
    penalty_total = q2(
        sum(
            (
                row.amount
                for row in details
                if row.source == DetailSource.manual.value
                and row.include_in_gross
                and row.direction == SubjectDirection.penalty.value
            ),
            ZERO,
        )
    )

    dailies: list[CalcDaily] = []
    for day in iter_dates(data.period_start, data.period_end):
        day_orders = [row for row in orders if row.biz_date == day]
        completed = [row for row in day_orders if _is_completed(row) and not _after_leave(data.leave_date, day)]
        formula_amount = q2(
            sum(
                (
                    row.amount
                    for row in details
                    if row.source == DetailSource.formula.value
                    and row.biz_date == day
                    and row.stage in {CalcStage.per_order.value, CalcStage.daily.value}
                ),
                ZERO,
            )
        )
        day_bonus = q2(
            sum(
                (
                    row.amount
                    for row in details
                    if row.source == DetailSource.manual.value
                    and row.biz_date == day
                    and row.include_in_gross
                    and row.direction == SubjectDirection.bonus.value
                ),
                ZERO,
            )
        )
        day_penalty = q2(
            sum(
                (
                    row.amount
                    for row in details
                    if row.source == DetailSource.manual.value
                    and row.biz_date == day
                    and row.include_in_gross
                    and row.direction == SubjectDirection.penalty.value
                ),
                ZERO,
            )
        )
        imported = day in data.covered_dates or day in data.site_order_dates
        if day in no_plan_days:
            status = DayStatus.no_plan.value
        elif completed or day_orders:
            status = DayStatus.has_data.value
        elif imported:
            status = DayStatus.no_orders.value
        else:
            status = DayStatus.not_imported.value
        dailies.append(
            CalcDaily(
                rider_id=rider_id,
                biz_date=day,
                plan_version_id=covered.get(day),
                order_count=len(day_orders),
                valid_order_count=len(completed),
                formula_amount=formula_amount,
                manual_bonus=day_bonus,
                manual_penalty=day_penalty,
                net_adjust=q2(day_bonus + day_penalty),
                day_status=status,
                period_id=data.period_id,
            )
        )

    # 单段（含试算强制全程生效）取该段；多段取各段之和（无方案日不计）
    plan_order_total = (
        segment_order_counts[0].plan_order_count
        if len(segment_order_counts) == 1
        else sum(item.plan_order_count for item in segment_order_counts)
    )
    return CalcResult(
        rider_id=rider_id,
        period_id=data.period_id,
        payroll_id=None,
        order_count=len(orders),
        valid_order_count=len(completed_all),
        per_order_total=q2(per_order_total),
        daily_total=q2(daily_total),
        period_total=q2(period_total),
        bonus_total=bonus_total,
        penalty_total=penalty_total,
        gross=gross,
        deduction_total=deduction_total,
        advance_deduction=q2(advance_deduction),
        advance_deductible=q2(deductible),
        net=net,
        plan_version_ids=[segment.plan_version_id for segment in data.segments],
        warnings=warnings,
        details=details,
        dailies=dailies,
        plan_order_count=plan_order_total,
        segment_order_counts=segment_order_counts,
    )


def trial_max_orders() -> int:
    """试算订单上限"""
    return int(getattr(settings, 'RIDER_SALARY_TRIAL_MAX_ORDERS', 5000) or 5000)


async def _acquire_calc_lock(period_id: int, rider_id: int) -> Any:
    lock = redis_client.lock(f'rs:calc:{period_id}:{rider_id}', timeout=CALC_LOCK_TTL)
    acquired = await lock.acquire(blocking=False)
    if not acquired:
        raise errors.ConflictError(msg='该骑手薪资正在计算中，请稍后再试')
    return lock


async def calculate_rider_period(
    db: AsyncSession,
    *,
    rider_id: int,
    period: RiderSalarySettlePeriod,
    persist: bool = True,
    forced_plan_version: RiderSalaryPlanVersion | None = None,
    operator: Request | None = None,
) -> CalcResult:
    """
    计算骑手周期薪资。persist=True 写库并抵扣预支；False 为试算/预估。
    """
    rider = await db.scalar(
        select(RiderSalaryRider).where(RiderSalaryRider.id == rider_id, RiderSalaryRider.deleted == 0)
    )
    if rider is None:
        raise errors.NotFoundError(msg='骑手不存在')

    lock = None
    if persist:
        lock = await _acquire_calc_lock(period.id, rider_id)
    try:
        return await _calculate_rider_period_inner(
            db,
            rider=rider,
            period=period,
            persist=persist,
            forced_plan_version=forced_plan_version,
            operator=operator,
        )
    finally:
        if lock is not None and await lock.owned():
            await lock.release()


async def _load_calc_input(
    db: AsyncSession,
    *,
    rider: RiderSalaryRider,
    period: RiderSalarySettlePeriod,
    forced_plan_version: RiderSalaryPlanVersion | None,
    persist_advance: bool,
) -> CalcInput:
    start, end = period.start_date, period.end_date
    site_id = period.site_id
    segments = await resolve_segments(db, rider.id, start, end, forced=forced_plan_version)
    orders = list(
        (
            await db.scalars(
                select(RiderSalaryOrder).where(
                    RiderSalaryOrder.rider_id == rider.id,
                    RiderSalaryOrder.site_id == site_id,
                    RiderSalaryOrder.biz_date >= start,
                    RiderSalaryOrder.biz_date <= end,
                    RiderSalaryOrder.deleted == 0,
                )
            )
        ).all()
    )
    flags = list(
        (
            await db.scalars(
                select(RiderSalaryDayFlag).where(
                    RiderSalaryDayFlag.site_id == site_id,
                    RiderSalaryDayFlag.biz_date >= start,
                    RiderSalaryDayFlag.biz_date <= end,
                    RiderSalaryDayFlag.deleted == 0,
                )
            )
        ).all()
    )
    history = list(
        (
            await db.scalars(
                select(RiderSalaryRiderEmployHistory).where(
                    RiderSalaryRiderEmployHistory.rider_id == rider.id,
                    RiderSalaryRiderEmployHistory.deleted == 0,
                )
            )
        ).all()
    )
    adjustments = list(
        (
            await db.scalars(
                select(RiderSalaryAdjustment).where(
                    RiderSalaryAdjustment.rider_id == rider.id,
                    RiderSalaryAdjustment.site_id == site_id,
                    RiderSalaryAdjustment.biz_date >= start,
                    RiderSalaryAdjustment.biz_date <= end,
                    RiderSalaryAdjustment.deleted == 0,
                )
            )
        ).all()
    )
    subject_ids = {row.subject_id for row in adjustments}
    subjects: dict[int, RiderSalarySubject] = {}
    if subject_ids:
        subject_rows = await db.scalars(
            select(RiderSalarySubject).where(RiderSalarySubject.id.in_(subject_ids), RiderSalarySubject.deleted == 0)
        )
        subjects = {row.id: row for row in subject_rows.all()}
    for adj in adjustments:
        subject = subjects.get(adj.subject_id)
        adj.subject = subject
        if subject is not None:
            adj.direction = subject.direction
            adj.include_in_gross = subject.include_in_gross
            if adj.signed_amount is None:
                amount = q2(adj.amount)
                adj.signed_amount = amount if subject.direction == SubjectDirection.bonus.value else q2(-amount)

    batches = list(
        (
            await db.scalars(
                select(RiderSalaryImportBatch).where(
                    RiderSalaryImportBatch.site_id == site_id,
                    RiderSalaryImportBatch.deleted == 0,
                )
            )
        ).all()
    )
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
    advances = await payroll_service.load_paid_advances(db, rider.id)
    return CalcInput(
        rider_id=rider.id,
        site_id=site_id,
        period_start=start,
        period_end=end,
        hire_date=rider.hire_date,
        leave_date=rider.leave_date,
        employ_type=rider.employ_type,
        segments=segments,
        orders=orders,
        day_flags={row.biz_date: row for row in flags},
        employ_history=history,
        adjustments=adjustments,
        advances=advances,
        covered_dates=covered,
        site_order_dates=set(site_dates),
        persist_advance=persist_advance,
        period_id=period.id,
    )


async def _persist_result(
    db: AsyncSession,
    *,
    rider: RiderSalaryRider,
    period: RiderSalarySettlePeriod,
    result: CalcResult,
    operator: Request | None,
) -> CalcResult:
    kind = PayrollKind.supplement.value if period.status == PeriodStatus.reopened.value else PayrollKind.normal.value
    payroll = await payroll_dao.get_current(db, period.id, rider.id, kind)
    if payroll is not None and payroll.status != PayrollStatus.draft.value:
        raise errors.RequestError(msg='已定稿结果不可重算，请走反冲补发')
    if payroll is None:
        payroll = RiderSalaryPayroll(period_id=period.id, rider_id=rider.id, kind=kind)
        db.add(payroll)
        await db.flush()
    await payroll_detail_dao.logical_delete_by_payroll(db, payroll.id)
    for detail in result.details:
        db.add(
            RiderSalaryPayrollDetail(
                payroll_id=payroll.id,
                rider_id=rider.id,
                subject_id=detail.subject_id,
                amount=detail.amount,
                stage=detail.stage,
                include_in_gross=detail.include_in_gross,
                source=detail.source,
                biz_date=detail.biz_date,
                plan_version_id=detail.plan_version_id,
                plan_item_id=detail.plan_item_id,
                order_id=detail.order_id,
                calc_trace=detail.calc_trace,
            )
        )
    for daily in result.dailies:
        row = await payroll_daily_dao.get_one(db, rider.id, daily.biz_date)
        if row is None:
            db.add(
                RiderSalaryPayrollDaily(
                    rider_id=rider.id,
                    biz_date=daily.biz_date,
                    period_id=period.id,
                    plan_version_id=daily.plan_version_id,
                    order_count=daily.order_count,
                    valid_order_count=daily.valid_order_count,
                    formula_amount=daily.formula_amount,
                    manual_bonus=daily.manual_bonus,
                    manual_penalty=daily.manual_penalty,
                    net_adjust=daily.net_adjust,
                    day_status=daily.day_status,
                )
            )
        else:
            row.period_id = period.id
            row.plan_version_id = daily.plan_version_id
            row.order_count = daily.order_count
            row.valid_order_count = daily.valid_order_count
            row.formula_amount = daily.formula_amount
            row.manual_bonus = daily.manual_bonus
            row.manual_penalty = daily.manual_penalty
            row.net_adjust = daily.net_adjust
            row.day_status = daily.day_status
    payroll.calc_version = int(payroll.calc_version or 0) + 1
    payroll.stale = False
    payroll.warnings = result.warnings
    payroll.order_count = result.order_count
    payroll.valid_order_count = result.valid_order_count
    payroll.per_order_total = result.per_order_total
    payroll.daily_total = result.daily_total
    payroll.period_total = result.period_total
    payroll.bonus_total = result.bonus_total
    payroll.penalty_total = result.penalty_total
    payroll.gross = result.gross
    payroll.deduction_total = result.deduction_total
    payroll.advance_deduction = result.advance_deduction
    payroll.net = result.net
    payroll.plan_version_ids = result.plan_version_ids
    payroll.calc_time = timezone.now()
    payroll.calc_by = int(getattr(getattr(operator, 'user', None), 'id', 0) or 0) if operator else None
    for version_id in result.plan_version_ids:
        version = await db.scalar(
            select(RiderSalaryPlanVersion).where(
                RiderSalaryPlanVersion.id == version_id,
                RiderSalaryPlanVersion.deleted == 0,
            )
        )
        if version is not None:
            version.is_used = True
    await db.flush()
    result.payroll_id = payroll.id
    result.calc_version = payroll.calc_version
    result.stale = False
    if operator is not None:
        await audit_service.record(
            db,
            operator,
            module='结算周期',
            action='重算',
            target_type='payroll',
            target_id=payroll.id,
            target_label=f'周期{period.start_date}~{period.end_date} 骑手{rider.job_no}',
        )
    return result


def _backfill_adjustments(
    *,
    period: RiderSalarySettlePeriod,
    adjustments: list[Any],
) -> None:
    for adj in adjustments:
        if getattr(adj, 'id', None):
            adj.period_id = period.id


async def _restore_draft_advances(
    db: AsyncSession,
    *,
    rider_id: int,
    period: RiderSalarySettlePeriod,
) -> None:
    """覆盖重算前先回滚本 draft 已抵扣的预支，避免 remaining=0 导致二次算薪丢抵扣"""
    kind = PayrollKind.supplement.value if period.status == PeriodStatus.reopened.value else PayrollKind.normal.value
    payroll = await payroll_dao.get_current(db, period.id, rider_id, kind)
    if payroll is None or payroll.status != PayrollStatus.draft.value:
        return
    await payroll_service.restore_advances_from_payroll(db, payroll)


async def _calculate_rider_period_inner(
    db: AsyncSession,
    *,
    rider: RiderSalaryRider,
    period: RiderSalarySettlePeriod,
    persist: bool,
    forced_plan_version: RiderSalaryPlanVersion | None,
    operator: Request | None,
) -> CalcResult:
    if persist:
        await _restore_draft_advances(db, rider_id=rider.id, period=period)
    data = await _load_calc_input(
        db,
        rider=rider,
        period=period,
        forced_plan_version=forced_plan_version,
        persist_advance=persist,
    )
    result = run_calc_pipeline(data)
    if persist:
        _backfill_adjustments(period=period, adjustments=data.adjustments)
        result = await _persist_result(db, rider=rider, period=period, result=result, operator=operator)
    return result


async def trial_rider_range(
    db: AsyncSession,
    *,
    rider_id: int,
    start: date,
    end: date,
    forced_plan_version: RiderSalaryPlanVersion,
) -> CalcResult:
    """试算：假定该版本在区间内全程生效，不落库、不抵扣预支"""
    from types import SimpleNamespace

    rider = await db.scalar(
        select(RiderSalaryRider).where(RiderSalaryRider.id == rider_id, RiderSalaryRider.deleted == 0)
    )
    if rider is None:
        raise errors.NotFoundError(msg='骑手不存在')
    if start > end:
        raise errors.RequestError(msg='结束日期不能早于开始日期')
    order_count = len(
        (
            await db.scalars(
                select(RiderSalaryOrder.id).where(
                    RiderSalaryOrder.rider_id == rider_id,
                    RiderSalaryOrder.site_id == rider.site_id,
                    RiderSalaryOrder.biz_date >= start,
                    RiderSalaryOrder.biz_date <= end,
                    RiderSalaryOrder.deleted == 0,
                )
            )
        ).all()
    )
    if order_count > trial_max_orders():
        raise errors.RequestError(msg=f'试算订单数超过上限 {trial_max_orders()}')
    period_like = SimpleNamespace(
        id=None,
        site_id=rider.site_id,
        start_date=start,
        end_date=end,
        status=PeriodStatus.open.value,
        rider_id=SITE_LEVEL_RIDER_ID,
    )
    data = await _load_calc_input(
        db,
        rider=rider,
        period=period_like,  # type: ignore[arg-type]
        forced_plan_version=forced_plan_version,
        persist_advance=False,
    )
    return run_calc_pipeline(data)


async def calculate_period(
    db: AsyncSession,
    *,
    period_id: int,
    rider_ids: list[int] | None = None,
    operator: Request | None = None,
) -> list[CalcResult]:
    """计算周期内骑手薪资（站点级跳过有骑手级周期覆盖的人）"""
    period = await db.scalar(
        select(RiderSalarySettlePeriod).where(
            RiderSalarySettlePeriod.id == period_id,
            RiderSalarySettlePeriod.deleted == 0,
        )
    )
    if period is None:
        raise errors.NotFoundError(msg='结算周期不存在')
    targets = await _riders_for_period(db, period, rider_ids)
    results: list[CalcResult] = [
        await calculate_rider_period(db, rider_id=rider_id, period=period, persist=True, operator=operator)
        for rider_id in targets
    ]
    return results


async def _riders_for_period(
    db: AsyncSession,
    period: RiderSalarySettlePeriod,
    rider_ids: list[int] | None,
) -> list[int]:
    if period.rider_id and period.rider_id != SITE_LEVEL_RIDER_ID:
        if rider_ids is not None and period.rider_id not in rider_ids:
            return []
        return [period.rider_id]
    current = set(
        (
            await db.scalars(
                select(RiderSalaryRider.id).where(
                    RiderSalaryRider.site_id == period.site_id,
                    RiderSalaryRider.deleted == 0,
                )
            )
        ).all()
    )
    from_orders = set(
        (
            await db.scalars(
                select(RiderSalaryOrder.rider_id).where(
                    RiderSalaryOrder.site_id == period.site_id,
                    RiderSalaryOrder.biz_date >= period.start_date,
                    RiderSalaryOrder.biz_date <= period.end_date,
                    RiderSalaryOrder.deleted == 0,
                )
            )
        ).all()
    )
    from_adj = set(
        (
            await db.scalars(
                select(RiderSalaryAdjustment.rider_id).where(
                    RiderSalaryAdjustment.site_id == period.site_id,
                    RiderSalaryAdjustment.biz_date >= period.start_date,
                    RiderSalaryAdjustment.biz_date <= period.end_date,
                    RiderSalaryAdjustment.deleted == 0,
                )
            )
        ).all()
    )
    ids = current | from_orders | from_adj
    if rider_ids is not None:
        ids &= set(rider_ids)
    covered = set(
        (
            await db.scalars(
                select(RiderSalarySettlePeriod.rider_id).where(
                    RiderSalarySettlePeriod.site_id == period.site_id,
                    RiderSalarySettlePeriod.rider_id != SITE_LEVEL_RIDER_ID,
                    RiderSalarySettlePeriod.start_date <= period.end_date,
                    RiderSalarySettlePeriod.end_date >= period.start_date,
                    RiderSalarySettlePeriod.deleted == 0,
                )
            )
        ).all()
    )
    return sorted(rid for rid in ids if rid not in covered)
