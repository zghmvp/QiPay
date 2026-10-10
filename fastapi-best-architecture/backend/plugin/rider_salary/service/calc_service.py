import asyncio
import json
import uuid

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.util import await_only

from backend.common.exception import errors
from backend.core.conf import settings
from backend.database.redis import redis_client
from backend.plugin.rider_salary.crud.payroll import payroll_dao
from backend.plugin.rider_salary.crud.payroll_daily import payroll_daily_dao
from backend.plugin.rider_salary.crud.payroll_detail import payroll_detail_dao
from backend.plugin.rider_salary.engine.context import (
    batch_overlap_dates,
    build_day_context,
    build_order_context,
    build_period_context,
    build_segment_context,
    clip_date_range,
    iter_dates,
    trace_variables,
)
from backend.plugin.rider_salary.engine.evaluator import EvalError, evaluate_amount, evaluate_condition
from backend.plugin.rider_salary.engine.segments import (
    PlanItemView,
    Segment,
    employ_type_on,
    resolve_segments,
    split_segments_by_employ,
)
from backend.plugin.rider_salary.enums import (
    CalcStage,
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
from backend.plugin.rider_salary.service.audit_service import snapshot
from backend.plugin.rider_salary.service.payroll_service import (
    ADVANCE_SUBJECT_ID,
    compute_advance_deduction,
    payroll_service,
)
from backend.plugin.rider_salary.utils.audit import audit_service
from backend.plugin.rider_salary.utils.day_status import resolve_day_status
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

ZERO = Decimal('0.00')
_PAYROLL_CALC_FIELDS = (
    'id',
    'period_id',
    'rider_id',
    'kind',
    'status',
    'calc_version',
    'stale',
    'gross',
    'net',
    'advance_deduction',
    'deduction_total',
    'order_count',
    'valid_order_count',
    'per_order_total',
    'daily_total',
    'period_total',
    'bonus_total',
    'penalty_total',
    'plan_version_ids',
    'warnings',
    'calc_by',
)
CALC_LOCK_TTL = 120
CALC_LOCK_RENEW_SECONDS = 30
PERIOD_CALC_TTL = 120
SITE_LEVEL_RIDER_ID = 0
PERIOD_CALCULATING_LOCK_MSG = '正在算薪，请稍后再试'
CALC_BUSY_MSG = '正在计算，请稍后'
DRAFT_UNIQUE_INDEX = 'uq_rs_payroll_one_draft'
_TEST_REDIS_RUN_PREFIX = 'fba:it:'
_WRITABLE_PERIOD_STATUS = frozenset({PeriodStatus.open.value, PeriodStatus.reopened.value})


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
    rider_job_no: str = ''


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
    rider_job_no: str = ''
    rider_name: str = ''


@dataclass(frozen=True)
class SitePeriodCoverage:
    """一个站点在一个结算周期内共用的导入覆盖日和已有订单日。"""

    covered_dates: set[date]
    site_order_dates: set[date]


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
    """按日从用工历史取值。没有覆盖记录时回退到当前快照。"""
    return employ_type_on(history, default, day)


def _is_completed(order: Any) -> bool:
    return getattr(order, 'status', None) == OrderStatus.completed.value


def _after_leave(leave_date: date | None, day: date) -> bool:
    return leave_date is not None and day > leave_date


def _employed_on(hire_date: date | None, leave_date: date | None, day: date) -> bool:
    """日期是否落在在职闭区间内。入职日、离职日为空表示该端不限制。"""
    if hire_date is not None and day < hire_date:
        return False
    return not _after_leave(leave_date, day)


def _leave_unpaid_order_warning(leave_date: date, biz_date: date) -> str:
    """离职日之后某日有已完成订单时的告警。文案带上该日，同一天只应出现一次。"""
    return f'{biz_date.isoformat()} 骑手已于 {leave_date.isoformat()} 离职，该日订单未计薪'


def _warn_completed_orders_after_leave(data: CalcInput, orders: list[Any], warnings: list[str]) -> None:
    """周期内、离职日之后的已完成订单不计薪。

    每个未计薪日期写一条，带上该日和离职日。同一天多笔订单只留一条，不按天重复同一句。
    与有没有方案段无关。绑定被截到离职日后，次月可能没有任何方案段，仍然要告警。
    """
    if data.leave_date is None:
        return
    unpaid_days: set[date] = set()
    for row in orders:
        biz_date = getattr(row, 'biz_date', None)
        if not isinstance(biz_date, date):
            continue
        if biz_date < data.period_start or biz_date > data.period_end:
            continue
        if _is_completed(row) and _after_leave(data.leave_date, biz_date):
            unpaid_days.add(biz_date)
    for biz_date in sorted(unpaid_days):
        message = _leave_unpaid_order_warning(data.leave_date, biz_date)
        if message not in warnings:
            warnings.append(message)


def _resign_before_period_without_facts(
    leave_date: date | None,
    period_start: date,
    *,
    has_orders: bool,
    has_adjustments: bool,
) -> bool:
    """离职日早于周期起始日，且本期没有订单、没有奖惩时，不进入算薪名单。

    离职日当天仍在职。骑手级周期不走这里，离职结算仍会算这个人。
    """
    if leave_date is None or leave_date >= period_start:
        return False
    return not has_orders and not has_adjustments


def _plan_version_ids(segments: list[Segment]) -> list[int]:
    """本期用过的方案版本，按首次出现保留。

    同一版本中间断开后再出现也不重复。用工类型切段用的是切段前的原段，这里再去一次。
    """
    seen: set[int] = set()
    version_ids: list[int] = []
    for segment in segments:
        version_id = segment.plan_version_id
        if version_id in seen:
            continue
        seen.add(version_id)
        version_ids.append(version_id)
    return version_ids


def _enabled_items(segment: Segment, stage: str) -> list[PlanItemView]:
    items = [item for item in segment.items if item.enabled and item.stage == stage]
    items.sort(key=lambda item: (item.sort_order, item.id or 0))
    return items


EVAL_FAILURE_MARK = '求值失败'


def format_eval_failure_warning(
    item_name: str,
    *,
    order_no: str | None = None,
    job_no: str = '',
    rider_name: str = '',
) -> str:
    """按骑手、项名、订单号生成求值失败告警。相同文案只保留一条。

    :param item_name: 方案项名称
    :param order_no: 订单号；按日、周期项为空
    :param job_no: 工号
    :param rider_name: 骑手姓名
    :return: 中文告警
    """
    if rider_name and job_no:
        head = f'骑手{rider_name}（{job_no}）'
    elif job_no:
        head = f'骑手工号{job_no}'
    elif rider_name:
        head = f'骑手{rider_name}'
    else:
        head = ''
    body = f'方案项「{item_name}」'
    if order_no:
        body += f'订单「{order_no}」'
    return f'{head}{body}公式求值失败，已按 0 计算'


def is_eval_failure_warning(text: str) -> bool:
    """是否为公式或条件求值失败告警。"""
    return EVAL_FAILURE_MARK in text


def eval_failure_item_name(text: str) -> str:
    """从告警里取出方案项名称。"""
    marker = '方案项「'
    start = text.find(marker)
    if start < 0:
        return '未命名'
    rest = text[start + len(marker) :]
    end = rest.find('」')
    if end <= 0:
        return '未命名'
    return rest[:end]


def eval_failure_job_no(text: str) -> str | None:
    """从告警里取出括号中的工号。"""
    head = text.split('方案项「', 1)[0]
    start = head.rfind('（')
    end = head.rfind('）')
    if start < 0 or end <= start:
        return None
    job_no = head[start + 1 : end].strip()
    return job_no or None


def warning_mentions_job_no(text: str, job_no: str) -> bool:
    """告警是否属于这名骑手。"""
    if not job_no:
        return False
    return f'（{job_no}）' in text or text.startswith(f'骑手工号{job_no}')


def _remember_eval_warning(
    warnings: list[str],
    item_name: str,
    *,
    order_no: str | None,
    job_no: str,
    rider_name: str,
) -> None:
    """按项名和订单号去重后写入告警。"""
    message = format_eval_failure_warning(item_name, order_no=order_no, job_no=job_no, rider_name=rider_name)
    if message not in warnings:
        warnings.append(message)


def _eval_item(
    item: PlanItemView,
    names: dict[str, Any],
    warnings: list[str],
    *,
    order_no: str | None = None,
    job_no: str = '',
    rider_name: str = '',
) -> tuple[bool, Decimal, dict[str, Any]]:
    """求值一个方案项。失败时金额按 0，并留下可去重的告警。"""
    condition_expr = item.condition_expr or 'True'
    formula_text = (item.formula_expr or '').strip()
    formula_expr = formula_text or '0'
    try:
        hit = evaluate_condition(condition_expr, names)
    except EvalError:
        _remember_eval_warning(warnings, item.name, order_no=order_no, job_no=job_no, rider_name=rider_name)
        return False, ZERO, _trace(condition_expr, formula_expr, names, ZERO, hit=False)
    if not hit:
        return False, ZERO, _trace(condition_expr, formula_expr, names, ZERO, hit=False)
    if not formula_text:
        _remember_eval_warning(warnings, item.name, order_no=order_no, job_no=job_no, rider_name=rider_name)
        return True, ZERO, _trace(condition_expr, formula_expr, names, ZERO, hit=True)
    try:
        unsigned = evaluate_amount(formula_expr, names)
    except EvalError:
        _remember_eval_warning(warnings, item.name, order_no=order_no, job_no=job_no, rider_name=rider_name)
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
    completed_all = [
        row for row in orders if _is_completed(row) and _employed_on(data.hire_date, data.leave_date, row.biz_date)
    ]
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

    _warn_completed_orders_after_leave(data, orders, warnings)
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
    # 用工类型月中变化时切开方案段。版本列表仍用切段前的原段，避免同一版本因切段重复。
    segments = split_segments_by_employ(data.segments, data.employ_history, data.employ_type)
    for segment in segments:
        window = clip_date_range(segment.start_date, segment.end_date, data.hire_date, data.leave_date)
        for day in iter_dates(segment.start_date, segment.end_date):
            covered[day] = segment.plan_version_id
            in_employment = window is not None and window[0] <= day <= window[1]
            if not in_employment:
                continue
            employ = _employ_on(data.employ_history, data.employ_type, day)
            day_ctx = build_day_context(data.site_id, day, data.day_flags.get(day), employ)
            day_orders = [row for row in orders if row.biz_date == day]
            completed = [
                row for row in day_orders if _is_completed(row) and _employed_on(data.hire_date, data.leave_date, day)
            ]
            day_per_order = ZERO
            for order in completed:
                ctx = build_order_context(order, day_ctx)
                if ctx.pop('_missing_deliver', False):
                    msg = '字段「配送时长」为空，已按 0 计算'
                    if msg not in warnings:
                        warnings.append(msg)
                for item in _enabled_items(segment, CalcStage.per_order.value):
                    hit, amount, trace = _eval_item(
                        item,
                        ctx,
                        warnings,
                        order_no=getattr(order, 'order_no', None),
                        job_no=data.rider_job_no,
                        rider_name=data.rider_name,
                    )
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
                hit, amount, trace = _eval_item(
                    item,
                    day_agg,
                    warnings,
                    job_no=data.rider_job_no,
                    rider_name=data.rider_name,
                )
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
        if window is None:
            continue
        plan_orders = [row for row in completed_all if window[0] <= row.biz_date <= window[1]]
        segment_days = (window[1] - window[0]).days + 1
        seg_ctx = build_segment_context(
            period_ctx,
            plan_order_count=len(plan_orders),
            segment_days=segment_days,
            accrued_gross=accrued,
            per_order_total=per_order_total,
            employ_type=_employ_on(data.employ_history, data.employ_type, segment.end_date),
        )
        for item in _enabled_items(segment, CalcStage.period.value):
            # Q-01 方案 B：本期已计金额不含手工奖惩，保底不会把扣罚补回去。
            seg_ctx['本期已计金额'] = float(q2(accrued))
            seg_ctx['本期逐单金额'] = float(q2(per_order_total))
            hit, amount, trace = _eval_item(
                item,
                seg_ctx,
                warnings,
                job_no=data.rider_job_no,
                rider_name=data.rider_name,
            )
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
            if row.biz_date == day and _is_completed(row) and _employed_on(data.hire_date, data.leave_date, day)
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
        completed = [
            row for row in day_orders if _is_completed(row) and _employed_on(data.hire_date, data.leave_date, day)
        ]
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
        status = resolve_day_status(
            has_plan=day in covered and day not in no_plan_days,
            order_count=len(day_orders),
            valid_order_count=len(completed),
            imported=imported,
        )
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
        plan_version_ids=_plan_version_ids(data.segments),
        warnings=warnings,
        details=details,
        dailies=dailies,
        rider_job_no=data.rider_job_no,
    )


def trial_max_orders() -> int:
    """试算订单上限"""
    return int(getattr(settings, 'RIDER_SALARY_TRIAL_MAX_ORDERS', 5000) or 5000)


class CalcPersistSkippedError(Exception):
    """周期已不是开放或补发中，本次算薪不落库。"""

    def __init__(self, status: str) -> None:
        self.status = status
        self.warning = closed_period_calc_warning(status)
        super().__init__(self.warning)


def scoped_redis_key(key: str) -> str:
    """集成测试把 Redis 前缀换成 ``fba:it:…`` 时，算薪键跟着隔离，避免写入开发库 0 号库。

    :param key: 生产环境使用的键，例如 ``rs:calc:period:1``
    :return: 测试会话中的带前缀键；生产环境原样返回
    """
    sample = str(getattr(settings, 'JWT_USER_REDIS_PREFIX', '') or '')
    if not sample.startswith(_TEST_REDIS_RUN_PREFIX):
        return key
    split_at = sample.find(':', len(_TEST_REDIS_RUN_PREFIX))
    if split_at <= 0:
        return key
    return f'{sample[:split_at]}:{key}'


def period_calculating_key(period_id: int) -> str:
    """周期「计算中」标记。短期用 Redis，作业表落地后由 P5-01 接替。

    :param period_id: 结算周期 ID
    :return: Redis 键
    """
    return scoped_redis_key(f'rs:calc:period:{period_id}')


def period_calc_warnings_key(period_id: int) -> str:
    """后台算薪告警。周期详情接口读取后展示。

    :param period_id: 结算周期 ID
    :return: Redis 键
    """
    return scoped_redis_key(f'rs:calc:period:{period_id}:warnings')


def closed_period_calc_warning(status: str) -> str:
    """周期不可写时的告警文案。

    :param status: 周期状态
    :return: 中文告警
    """
    try:
        label = PeriodStatus(status).label
    except ValueError:
        label = status
    return f'结算周期当前状态为{label}，后台算薪已跳过，未新增草稿'


async def _add_period_calc_token(period_id: int, token: str) -> None:
    """给周期计算中标记加一个持有者。键是集合，并发算薪各自删自己的成员。

    :param period_id: 结算周期 ID
    :param token: 本次算薪的标记
    """
    key = period_calculating_key(period_id)
    try:
        await redis_client.sadd(key, token)
    except Exception as exc:
        if 'WRONGTYPE' not in str(exc).upper():
            raise
        await redis_client.delete(key)
        await redis_client.sadd(key, token)
    await redis_client.expire(key, PERIOD_CALC_TTL)


async def _remove_period_calc_token(period_id: int, token: str) -> None:
    """去掉本次算薪的标记。集合空了才删键，避免并发的另一方被提前清掉。

    :param period_id: 结算周期 ID
    :param token: 本次算薪的标记
    """
    key = period_calculating_key(period_id)
    try:
        await redis_client.srem(key, token)
        left = int(await redis_client.scard(key) or 0)
    except Exception as exc:
        if 'WRONGTYPE' not in str(exc).upper():
            raise
        await redis_client.delete(key)
        return
    if left <= 0:
        await redis_client.delete(key)


async def _refresh_period_calculating(period_id: int) -> None:
    """计算还在进行时续上周期标记的过期时间。

    :param period_id: 结算周期 ID
    """
    await redis_client.expire(period_calculating_key(period_id), PERIOD_CALC_TTL)


async def mark_period_calculating(period_id: int) -> None:
    """挂上或续期周期「计算中」标记。锁账看到该标记会直接拒绝。

    :param period_id: 结算周期 ID
    """
    await _add_period_calc_token(period_id, '1')
    await _refresh_period_calculating(period_id)


async def clear_period_calculating(period_id: int) -> None:
    """算薪结束（含失败）后去掉「计算中」标记。

    :param period_id: 结算周期 ID
    """
    await redis_client.delete(period_calculating_key(period_id))


async def is_period_calculating(period_id: int, db: AsyncSession | None = None) -> bool:
    """周期是否有排队中或计算中的算薪作业。

    锁账用作业表，不再读 Redis 临时标记。传入当前会话，避免集成测试里再开一条连接。
    事件循环已经关掉时视为没有活动作业，避免锁账单测被连接状态拖垮。

    :param period_id: 结算周期 ID
    :param db: 调用方会话
    :return: 有活动作业则为真
    """
    from backend.database.db import async_db_session
    from backend.plugin.rider_salary.service.calc_job_service import period_has_active_job

    try:
        if db is not None:
            return await period_has_active_job(db, period_id)
        async with async_db_session() as session:
            return await period_has_active_job(session, period_id)
    except RuntimeError as exc:
        if 'loop' not in str(exc).lower():
            raise
        return False


async def read_period_calc_warnings(period_id: int) -> list[str]:
    """读取后台算薪告警。Redis 不可用时返回空列表，避免周期详情打不开。

    :param period_id: 结算周期 ID
    :return: 告警文案
    """
    try:
        raw = await redis_client.get(period_calc_warnings_key(period_id))
    except Exception:
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [str(raw)]
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item)]


async def append_period_calc_warning(period_id: int, message: str) -> None:
    """追加一条周期级算薪告警，相同文案不重复。

    :param period_id: 结算周期 ID
    :param message: 中文告警
    """
    text = message.strip()
    if not text:
        return
    current = await read_period_calc_warnings(period_id)
    if text in current:
        return
    current.append(text)
    await redis_client.set(period_calc_warnings_key(period_id), json.dumps(current, ensure_ascii=False))


async def clear_period_calc_warnings(period_id: int) -> None:
    """成功落库后清掉「已跳过」之类的过期告警。

    :param period_id: 结算周期 ID
    """
    await redis_client.delete(period_calc_warnings_key(period_id))


async def lock_period_row(db: AsyncSession, period_id: int) -> RiderSalarySettlePeriod | None:
    """对周期行加 ``FOR UPDATE``，并读到当前已提交的状态。

    真库查不到行时抛不存在。单测用的假会话不会返回 ORM 实例，这时返回空，
    调用方继续用已经加载的周期对象。

    :param db: 数据库会话
    :param period_id: 结算周期 ID
    :return: 已加行锁的周期；假会话时为空
    """
    loaded = await db.scalar(
        select(RiderSalarySettlePeriod)
        .where(
            RiderSalarySettlePeriod.id == period_id,
            RiderSalarySettlePeriod.deleted == 0,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if isinstance(loaded, RiderSalarySettlePeriod):
        return loaded
    if isinstance(db, AsyncSession):
        raise errors.NotFoundError(msg='结算周期不存在')
    return None


async def _lock_period_for_calc(
    db: AsyncSession,
    period_id: int,
    *,
    fallback: RiderSalarySettlePeriod | None = None,
) -> RiderSalarySettlePeriod:
    """写库前锁周期并确认仍可算薪。已锁账或已发薪则跳过，不新建草稿。

    :param db: 数据库会话
    :param period_id: 结算周期 ID
    :param fallback: 假会话锁不到行时沿用的周期对象
    :return: 可写的周期
    """
    loaded = await lock_period_row(db, period_id)
    period = loaded if loaded is not None else fallback
    if period is None:
        raise errors.NotFoundError(msg='结算周期不存在')
    if period.status not in _WRITABLE_PERIOD_STATUS:
        raise CalcPersistSkippedError(period.status)
    return period


@dataclass
class _HeldCalcLock:
    """一把已拿到的骑手算薪锁，计算过程中续租，事务结束后释放。"""

    lock: Any
    stop: asyncio.Event
    loop: asyncio.AbstractEventLoop
    period_id: int
    renew_task: asyncio.Task[None] | None = None
    finished: bool = False
    bound: bool = False


async def _renew_calc_lock(held: _HeldCalcLock) -> None:
    """在锁过期前续租，并顺手延长周期计算中标记。"""
    while not held.stop.is_set():
        if await _renew_tick_elapsed(held):
            extended = await _extend_held_lock(held)
            if not extended:
                return
            continue
        return


async def _renew_tick_elapsed(held: _HeldCalcLock) -> bool:
    """等到续租间隔。期间收到停止信号则返回假。"""
    try:
        await asyncio.wait_for(held.stop.wait(), timeout=CALC_LOCK_RENEW_SECONDS)
    except TimeoutError:
        return True
    return False


async def _extend_held_lock(held: _HeldCalcLock) -> bool:
    """续租一次。锁已经不属于本次计算时返回假。"""
    try:
        if not await held.lock.owned():
            return False
        await held.lock.extend(CALC_LOCK_TTL, replace_ttl=True)
        await _refresh_period_calculating(held.period_id)
    except Exception:
        return False
    return True


async def _finish_held(held: _HeldCalcLock) -> None:
    """停掉续租并释放骑手算薪锁。重复调用无效果。"""
    if held.finished:
        return
    held.finished = True
    held.stop.set()
    task = held.renew_task
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    try:
        if await held.lock.owned():
            await held.lock.release()
    except Exception:
        return


def _bind_calc_lock(db: AsyncSession, held: _HeldCalcLock) -> bool:
    """把释放动作挂到当前会话事务结束之后，避免锁在提交前被放开。

    :param db: 数据库会话
    :param held: 已持有的算薪锁
    :return: 已挂上则为真；假会话没有事务时为假
    """
    sync = getattr(db, 'sync_session', None)
    if sync is None or not hasattr(sync, 'get_transaction'):
        return False
    root = sync.get_transaction()
    if root is None or held.bound:
        return False
    held.bound = True
    # 回调执行期间不能增删同一事件的监听器，否则遍历 deque 会报错。
    # 会话随请求结束，监听留在会话上；用标记保证根事务只释放一次。
    state = {'done': False}

    def _end(_session: object, transaction: object) -> None:
        if state['done'] or transaction is not root or held.finished:
            return
        state['done'] = True
        _release_held_after_commit(held)

    event.listen(sync, 'after_transaction_end', _end)
    return True


def _release_held_after_commit(held: _HeldCalcLock) -> None:
    """根事务结束后立刻放开锁，避免下一笔请求还看到计算中。"""
    try:
        await_only(_finish_held(held))
    except Exception:
        if not held.finished:
            held.loop.call_soon_threadsafe(lambda: held.loop.create_task(_finish_held(held)))


async def _acquire_calc_lock(period_id: int, rider_id: int) -> _HeldCalcLock:
    """非阻塞获取骑手算薪锁。拿不到时返回 409。

    :param period_id: 结算周期 ID
    :param rider_id: 骑手 ID
    :return: 已续租的锁
    """
    lock = redis_client.lock(scoped_redis_key(f'rs:calc:{period_id}:{rider_id}'), timeout=CALC_LOCK_TTL)
    acquired = await lock.acquire(blocking=False)
    if not acquired:
        raise errors.ConflictError(msg=CALC_BUSY_MSG)
    loop = asyncio.get_running_loop()
    held = _HeldCalcLock(
        lock=lock,
        stop=asyncio.Event(),
        loop=loop,
        period_id=period_id,
    )
    held.renew_task = loop.create_task(_renew_calc_lock(held))
    return held


async def _acquire_rider_calc_locks(period_id: int, rider_ids: list[int]) -> list[_HeldCalcLock]:
    """按骑手依次拿锁。中途失败时放开已经拿到的锁。

    :param period_id: 结算周期 ID
    :param rider_ids: 要算的骑手
    :return: 与骑手顺序一致的锁
    """
    held: list[_HeldCalcLock] = []
    try:
        for rider_id in rider_ids:
            await _refresh_period_calculating(period_id)
            held.append(await _acquire_calc_lock(period_id, rider_id))
    except Exception:
        for item in held:
            await _finish_held(item)
        raise
    return held


async def calculate_rider_period(
    db: AsyncSession,
    *,
    rider_id: int,
    period: RiderSalarySettlePeriod,
    persist: bool = True,
    forced_plan_version: RiderSalaryPlanVersion | None = None,
    operator: Request | None = None,
    held_lock: _HeldCalcLock | None = None,
    site_coverage: SitePeriodCoverage | None = None,
) -> CalcResult:
    """
    计算骑手周期薪资。persist=True 写库并抵扣预支；False 为试算/预估。

    传入 held_lock 时沿用调用方已经拿到的锁，本函数不释放。
    传入 site_coverage 时复用整期预取的覆盖日，不再按骑手重复查询。
    """
    rider = await db.scalar(
        select(RiderSalaryRider).where(RiderSalaryRider.id == rider_id, RiderSalaryRider.deleted == 0)
    )
    if rider is None:
        raise errors.NotFoundError(msg='骑手不存在')

    release_here = False
    if persist and held_lock is None:
        held_lock = await _acquire_calc_lock(period.id, rider_id)
        release_here = not _bind_calc_lock(db, held_lock)
    try:
        return await _calculate_rider_period_inner(
            db,
            rider=rider,
            period=period,
            persist=persist,
            forced_plan_version=forced_plan_version,
            operator=operator,
            site_coverage=site_coverage,
        )
    finally:
        if release_here and held_lock is not None:
            await _finish_held(held_lock)


async def load_site_period_coverage(
    db: AsyncSession,
    *,
    site_id: int,
    start: date,
    end: date,
) -> SitePeriodCoverage:
    """读取站点在周期内的导入覆盖日和已有订单日。

    同一周期算薪只调用一次，再传给每个骑手。批次按区间相交过滤：
    ``date_from <= end`` 且 ``date_to >= start``。任一端为空的批次没有可用范围，不参与。

    :param db: 数据库会话
    :param site_id: 站点 ID
    :param start: 周期开始
    :param end: 周期结束
    :return: 覆盖日与站点订单日
    """
    batches = (
        await db.scalars(
            select(RiderSalaryImportBatch).where(
                RiderSalaryImportBatch.site_id == site_id,
                RiderSalaryImportBatch.deleted == 0,
                RiderSalaryImportBatch.date_from.is_not(None),
                RiderSalaryImportBatch.date_to.is_not(None),
                RiderSalaryImportBatch.date_from <= end,
                RiderSalaryImportBatch.date_to >= start,
            )
        )
    ).all()
    covered: set[date] = set()
    for batch in batches:
        covered.update(batch_overlap_dates(batch.date_from, batch.date_to, start, end))
    site_rows = (
        await db.scalars(
            select(RiderSalaryOrder.biz_date)
            .where(
                RiderSalaryOrder.site_id == site_id,
                RiderSalaryOrder.biz_date >= start,
                RiderSalaryOrder.biz_date <= end,
                RiderSalaryOrder.deleted == 0,
            )
            .distinct()
        )
    ).all()
    site_order_dates = {day for day in site_rows if isinstance(day, date) and not isinstance(day, datetime)}
    return SitePeriodCoverage(covered_dates=covered, site_order_dates=site_order_dates)


async def _load_calc_input(
    db: AsyncSession,
    *,
    rider: RiderSalaryRider,
    period: RiderSalarySettlePeriod,
    forced_plan_version: RiderSalaryPlanVersion | None,
    persist_advance: bool,
    site_coverage: SitePeriodCoverage | None = None,
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
                derived = amount if subject.direction == SubjectDirection.bonus.value else q2(-amount)
                # 只改本次加载的内存值。直接赋值会把空的 signed_amount 回写进 rs_adjustment。
                set_committed_value(adj, 'signed_amount', derived)

    if site_coverage is None:
        site_coverage = await _load_site_period_coverage(db, site_id=site_id, start=start, end=end)
    advances = await payroll_service.load_paid_advances(db, rider.id, for_update=persist_advance)
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
        covered_dates=site_coverage.covered_dates,
        site_order_dates=site_coverage.site_order_dates,
        persist_advance=persist_advance,
        period_id=period.id,
        rider_job_no=rider.job_no or '',
        rider_name=rider.name or '',
    )


def _recalc_payroll_kind(period: RiderSalarySettlePeriod) -> str:
    """补发中的周期写补发单，其余写正常单"""
    if period.status == PeriodStatus.reopened.value:
        return PayrollKind.supplement.value
    return PayrollKind.normal.value


_ORIGINAL_NOT_REVERSED_MSG = '该骑手原单尚未反冲，不能生成补发单'


def _is_open_original(payroll: Any) -> bool:
    """已定稿或已发薪、尚未反冲的正常单。补发单和反冲单不算原单。"""
    if int(getattr(payroll, 'deleted', 0) or 0):
        return False
    if getattr(payroll, 'kind', None) != PayrollKind.normal.value:
        return False
    if bool(getattr(payroll, 'reversed', False)):
        return False
    return getattr(payroll, 'status', None) in {PayrollStatus.finalized.value, PayrollStatus.paid.value}


async def _reject_supplement_if_original_open(
    db: AsyncSession,
    *,
    period_id: int,
    rider_id: int,
) -> None:
    """补发中新建补发单前，原单必须已经反冲。

    只拦截尚未反冲的正常单。同类型补发单是否可重算仍由 _draft_for_recalc 决定，
    这样第二轮反冲后仍能新建下一张补发单。
    """
    rows = list(await payroll_dao.select_models(db, period_id=period_id, deleted=0))
    for row in rows:
        if int(getattr(row, 'rider_id', 0) or 0) != int(rider_id):
            continue
        if _is_open_original(row):
            raise errors.RequestError(msg=_ORIGINAL_NOT_REVERSED_MSG)


async def _draft_for_recalc(
    db: AsyncSession,
    *,
    period_id: int,
    rider_id: int,
    kind: str,
) -> RiderSalaryPayroll | None:
    """
    取本次重算要覆盖的草稿

    没有草稿时：补发单已被反冲则返回空，由调用方新建下一张；
    同类型仍有未反冲的定稿单则拒绝。已反冲的正常单不会因此再开一张正常单。

    :param db: 数据库会话
    :param period_id: 结算周期 ID
    :param rider_id: 骑手 ID
    :param kind: 本次要写的薪资单类型
    :return: 可覆盖的草稿；没有则返回空
    """
    draft = await payroll_dao.get_draft(db, period_id, rider_id, kind)
    if draft is not None:
        return draft
    current = await payroll_dao.get_current(db, period_id, rider_id, kind)
    if current is not None and not (current.reversed and kind == PayrollKind.supplement.value):
        raise errors.RequestError(msg='已定稿结果不可重算，请走反冲补发')
    return None


async def _prepare_payroll_for_persist(
    db: AsyncSession,
    *,
    rider: RiderSalaryRider,
    period: RiderSalarySettlePeriod,
) -> tuple[RiderSalarySettlePeriod, RiderSalaryPayroll]:
    """锁周期行并取出可覆盖的草稿。已锁账时不新建、不覆盖；已有定稿仍按原规则拒绝。"""
    loaded = await lock_period_row(db, period.id)
    if loaded is not None:
        period = loaded
    closed = period.status not in _WRITABLE_PERIOD_STATUS
    kind = _recalc_payroll_kind(period)
    payroll = await _draft_for_recalc(db, period_id=period.id, rider_id=rider.id, kind=kind)
    if payroll is None and kind == PayrollKind.supplement.value:
        await _reject_supplement_if_original_open(db, period_id=period.id, rider_id=rider.id)
    if closed:
        raise CalcPersistSkippedError(period.status)
    if payroll is None:
        payroll = await _insert_draft_payroll(db, period_id=period.id, rider_id=rider.id, kind=kind)
    return period, payroll


def _is_draft_unique_violation(exc: BaseException) -> bool:
    """是否撞上草稿部分唯一索引。"""
    if DRAFT_UNIQUE_INDEX in str(exc):
        return True
    orig = getattr(exc, 'orig', None)
    if orig is None:
        return False
    return getattr(orig, 'constraint_name', None) == DRAFT_UNIQUE_INDEX or DRAFT_UNIQUE_INDEX in str(orig)


async def _insert_draft_payroll(
    db: AsyncSession,
    *,
    period_id: int,
    rider_id: int,
    kind: str,
) -> RiderSalaryPayroll:
    """新建草稿。唯一索引冲突说明另一笔算薪已写入，返回 409。

    :param db: 数据库会话
    :param period_id: 结算周期 ID
    :param rider_id: 骑手 ID
    :param kind: 薪资单类型
    :return: 新草稿
    """
    payroll = RiderSalaryPayroll(period_id=period_id, rider_id=rider_id, kind=kind)
    nested = getattr(db, 'begin_nested', None)
    if nested is None:
        db.add(payroll)
        await db.flush()
        return payroll
    try:
        async with db.begin_nested():
            db.add(payroll)
            await db.flush()
    except IntegrityError as exc:
        if _is_draft_unique_violation(exc):
            raise errors.ConflictError(msg=CALC_BUSY_MSG) from exc
        raise
    return payroll


async def _existing_dailies(
    db: AsyncSession,
    rider_id: int,
    dailies: list[CalcDaily],
) -> dict[date, RiderSalaryPayrollDaily]:
    """按日汇总的最小到最大业务日一次取出，不再逐日查询。"""
    if not dailies:
        return {}
    start = min(item.biz_date for item in dailies)
    end = max(item.biz_date for item in dailies)
    rows = await payroll_daily_dao.list_by_rider_range(db, rider_id, start, end)
    return {row.biz_date: row for row in rows}


async def _persist_result(
    db: AsyncSession,
    *,
    rider: RiderSalaryRider,
    period: RiderSalarySettlePeriod,
    result: CalcResult,
    operator: Request | None,
) -> CalcResult:
    period, payroll = await _prepare_payroll_for_persist(db, rider=rider, period=period)
    before = snapshot(payroll, _PAYROLL_CALC_FIELDS)
    await payroll_detail_dao.logical_delete_by_payroll(db, payroll.id)
    if result.details:
        db.add_all([
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
            for detail in result.details
        ])
    existing_dailies = await _existing_dailies(db, rider.id, result.dailies)
    for daily in result.dailies:
        row = existing_dailies.get(daily.biz_date)
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
    await audit_service.record(
        db,
        operator,
        module='结算周期',
        action='重算',
        target_type='payroll',
        target_id=payroll.id,
        target_label=(f'周期{getattr(period, "start_date", "")}~{getattr(period, "end_date", "")} 骑手{rider.job_no}'),
        site_id=getattr(period, 'site_id', None),
        before=before,
        after=snapshot(payroll, _PAYROLL_CALC_FIELDS),
    )
    return result


async def _restore_draft_advances(
    db: AsyncSession,
    *,
    rider_id: int,
    period: RiderSalarySettlePeriod,
) -> None:
    """覆盖重算前先回滚本草稿已抵扣的预支，避免 remaining=0 导致二次算薪丢抵扣。

    只处理草稿。已反冲的定稿单在反冲时已经退回预支，这里再退一次会把余额加两次。
    """
    payroll = await payroll_dao.get_draft(db, period.id, rider_id, _recalc_payroll_kind(period))
    if payroll is None:
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
    site_coverage: SitePeriodCoverage | None = None,
) -> CalcResult:
    if persist:
        period = await _lock_period_for_calc(db, period.id, fallback=period)
        await _restore_draft_advances(db, rider_id=rider.id, period=period)
    data = await _load_calc_input(
        db,
        rider=rider,
        period=period,
        forced_plan_version=forced_plan_version,
        persist_advance=persist,
        site_coverage=site_coverage,
    )
    result = await asyncio.get_running_loop().run_in_executor(None, run_calc_pipeline, data)
    if persist:
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
    order_count = int(
        await db.scalar(
            select(func.count())
            .select_from(RiderSalaryOrder)
            .where(
                RiderSalaryOrder.rider_id == rider_id,
                RiderSalaryOrder.site_id == rider.site_id,
                RiderSalaryOrder.biz_date >= start,
                RiderSalaryOrder.biz_date <= end,
                RiderSalaryOrder.deleted == 0,
            )
        )
        or 0
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


async def read_period_for_calc(db: AsyncSession, period_id: int) -> RiderSalarySettlePeriod:
    """先读周期状态，不锁行。已锁账则跳过，避免占着行锁才发现不能算。

    :param db: 数据库会话
    :param period_id: 结算周期 ID
    :return: 仍可算薪的周期
    """
    loaded = await db.scalar(
        select(RiderSalarySettlePeriod)
        .where(
            RiderSalarySettlePeriod.id == period_id,
            RiderSalarySettlePeriod.deleted == 0,
        )
        .execution_options(populate_existing=True)
    )
    if not isinstance(loaded, RiderSalarySettlePeriod):
        raise errors.NotFoundError(msg='结算周期不存在')
    if loaded.status not in _WRITABLE_PERIOD_STATUS:
        raise CalcPersistSkippedError(loaded.status)
    return loaded


async def calculate_period(
    db: AsyncSession,
    *,
    period_id: int,
    rider_ids: list[int] | None = None,
    operator: Request | None = None,
) -> list[CalcResult]:
    """计算周期内骑手薪资（站点级跳过有骑手级周期覆盖的人）。

    写库前锁周期行。状态不是开放或补发中时跳过该周期，不新增草稿，并写入可见告警。
    计算中标记按本次调用单独计数，并发的另一笔结束时不会把它清掉。
    """
    token = uuid.uuid4().hex
    await _add_period_calc_token(period_id, token)
    try:
        return await _calculate_period_body(
            db,
            period_id=period_id,
            rider_ids=rider_ids,
            operator=operator,
        )
    finally:
        await _remove_period_calc_token(period_id, token)


async def _calculate_period_body(
    db: AsyncSession,
    *,
    period_id: int,
    rider_ids: list[int] | None,
    operator: Request | None,
) -> list[CalcResult]:
    period = await _open_period_or_warn(db, period_id)
    if period is None:
        return []
    targets = await _riders_for_period(db, period, rider_ids)
    locked = await _lock_riders_then_period(db, period_id=period.id, rider_ids=targets)
    if locked is None:
        return []
    period, held = locked
    results, skipped = await _calc_held_riders(db, period=period, rider_ids=targets, held=held, operator=operator)
    await _record_rider_skips(period_id, results, skipped)
    return results


async def _open_period_or_warn(db: AsyncSession, period_id: int) -> RiderSalarySettlePeriod | None:
    """周期已锁账时写告警并返回空，不拿骑手锁。"""
    try:
        return await _read_period_for_calc(db, period_id)
    except CalcPersistSkippedError as exc:
        await append_period_calc_warning(period_id, exc.warning)
        return None


async def _lock_riders_then_period(
    db: AsyncSession,
    *,
    period_id: int,
    rider_ids: list[int],
) -> tuple[RiderSalarySettlePeriod, list[_HeldCalcLock]] | None:
    """先拿骑手锁再锁周期行。并发的第二笔在拿锁时直接 409。

    :return: 可写周期和锁；期间变成不可写时返回空
    """
    held = await _acquire_rider_calc_locks(period_id, rider_ids)
    try:
        period = await _lock_period_for_calc(db, period_id)
    except CalcPersistSkippedError as exc:
        for item in held:
            await _finish_held(item)
        await append_period_calc_warning(period_id, exc.warning)
        return None
    except Exception:
        for item in held:
            await _finish_held(item)
        raise
    return period, held


async def _calc_held_riders(
    db: AsyncSession,
    *,
    period: RiderSalarySettlePeriod,
    rider_ids: list[int],
    held: list[_HeldCalcLock],
    operator: Request | None,
) -> tuple[list[CalcResult], list[str]]:
    """用已经拿到的锁逐个算薪。没挂到事务上的锁在本函数结束时释放。"""
    release_now = [item for item in held if not _bind_calc_lock(db, item)]
    results: list[CalcResult] = []
    skipped: list[str] = []
    try:
        site_coverage = None
        if rider_ids:
            site_coverage = await _load_site_period_coverage(
                db,
                site_id=period.site_id,
                start=period.start_date,
                end=period.end_date,
            )
        for rider_id, item in zip(rider_ids, held, strict=True):
            await _refresh_period_calculating(period.id)
            try:
                results.append(
                    await calculate_rider_period(
                        db,
                        rider_id=rider_id,
                        period=period,
                        persist=True,
                        operator=operator,
                        held_lock=item,
                        site_coverage=site_coverage,
                    )
                )
            except CalcPersistSkippedError as exc:
                skipped.append(exc.warning)
    finally:
        for item in release_now:
            await _finish_held(item)
    return results, skipped


def _eval_warnings_of(results: list[CalcResult]) -> list[str]:
    """收集本次算薪的求值失败告警，按完整文案去重。"""
    found: list[str] = []
    for result in results:
        for warning in result.warnings:
            if is_eval_failure_warning(warning) and warning not in found:
                found.append(warning)
    return found


async def _publish_eval_failure_warnings(period_id: int, results: list[CalcResult], *, replace_run: bool) -> None:
    """把求值失败写入周期告警。成功算薪时换掉本批骑手的旧告警，保留其他人的。

    :param period_id: 结算周期 ID
    :param results: 本次算薪结果
    :param replace_run: 为真时先清掉过期告警，再写回未参与本次的求值失败
    """
    fresh = _eval_warnings_of(results)
    job_nos = {result.rider_job_no for result in results if result.rider_job_no}
    if replace_run:
        previous = await read_period_calc_warnings(period_id)
        kept = [
            item
            for item in previous
            if is_eval_failure_warning(item) and not any(warning_mentions_job_no(item, job_no) for job_no in job_nos)
        ]
        await clear_period_calc_warnings(period_id)
        for warning in [*kept, *fresh]:
            await append_period_calc_warning(period_id, warning)
        return
    for warning in fresh:
        await append_period_calc_warning(period_id, warning)


async def record_rider_skips(period_id: int, results: list[CalcResult], skipped: list[str]) -> None:
    """有人被跳过就留下告警；全部写成功则清掉过期告警，但保留公式求值失败。"""
    if skipped:
        for warning in skipped:
            await append_period_calc_warning(period_id, warning)
        await _publish_eval_failure_warnings(period_id, results, replace_run=False)
        return
    if results:
        await _publish_eval_failure_warnings(period_id, results, replace_run=True)


async def riders_for_period(
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
    resigned = (
        await db.execute(
            select(RiderSalaryRider.id, RiderSalaryRider.leave_date).where(
                RiderSalaryRider.site_id == period.site_id,
                RiderSalaryRider.deleted == 0,
                RiderSalaryRider.leave_date.is_not(None),
                RiderSalaryRider.leave_date < period.start_date,
            )
        )
    ).all()
    ids = current | from_orders | from_adj
    ids.difference_update(
        rider_id
        for rider_id, leave_date in resigned
        if _resign_before_period_without_facts(
            leave_date,
            period.start_date,
            has_orders=rider_id in from_orders,
            has_adjustments=rider_id in from_adj,
        )
    )
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


# 同模块和既有测试仍可按旧名调用，行为与公开函数相同。
_load_site_period_coverage = load_site_period_coverage
_read_period_for_calc = read_period_for_calc
_record_rider_skips = record_rider_skips
_riders_for_period = riders_for_period
