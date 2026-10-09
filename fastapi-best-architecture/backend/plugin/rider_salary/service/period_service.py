from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.database.db import async_db_session
from backend.plugin.rider_salary.crud.payroll import payroll_dao
from backend.plugin.rider_salary.crud.payroll_detail import payroll_detail_dao
from backend.plugin.rider_salary.crud.settle_period import SITE_LEVEL_RIDER_ID, settle_period_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.enums import (
    CycleType,
    DeductStatus,
    DetailSource,
    PayrollKind,
    PayrollStatus,
    PeriodStatus,
    RiderStatus,
)
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.schema.period import (
    CalculatePeriodParam,
    CalculatePeriodResult,
    CarryForwardResult,
    GeneratePeriodParam,
    GeneratePeriodResult,
    GetGeneratedPeriodItem,
    GetLockCheckResult,
    GetPeriodDetail,
    GetPeriodForDateResult,
    GetPeriodListItem,
    GetPeriodPayrollItem,
    GetPeriodWithPayrolls,
    LeaveSettlementResult,
    LockCheckRiderItem,
    MarkPaidPeriodResult,
    ReversePeriodResult,
)
from backend.plugin.rider_salary.service.audit_service import audit_service, snapshot
from backend.plugin.rider_salary.service.calc_service import (
    PERIOD_CALCULATING_LOCK_MSG,
    append_period_calc_warning,
    eval_failure_item_name,
    eval_failure_job_no,
    is_eval_failure_warning,
    is_period_calculating,
    lock_period_row,
    read_period_calc_warnings,
    riders_for_period,
)
from backend.plugin.rider_salary.service.payroll_service import payroll_service
from backend.plugin.rider_salary.service.payroll_view import summarize_period_stats
from backend.plugin.rider_salary.utils.audit import operator_display_name, require_reason
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.lock_check import is_status_locked
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.periods import compute_period_range
from backend.utils.timezone import timezone

ZERO = Decimal('0.00')
_PERIOD_FIELDS = (
    'id',
    'site_id',
    'rider_id',
    'cycle_type',
    'start_date',
    'end_date',
    'status',
    'remark',
)
_KIND_KEYS = (PayrollKind.normal.value, PayrollKind.reversal.value, PayrollKind.supplement.value)
_ALLOWED_TRANSITIONS: dict[tuple[str, str], str] = {
    (PeriodStatus.open.value, PeriodStatus.locked.value): '锁账',
    (PeriodStatus.reopened.value, PeriodStatus.locked.value): '锁账',
    (PeriodStatus.locked.value, PeriodStatus.paid.value): '标记发薪',
    (PeriodStatus.locked.value, PeriodStatus.reopened.value): '反冲补发',
    (PeriodStatus.paid.value, PeriodStatus.reopened.value): '反冲补发',
}
_REASON_REQUIRED_TARGETS = {PeriodStatus.locked.value, PeriodStatus.reopened.value}


def covering_period_ranges(
    cycle_type: CycleType | str,
    cycle_config: dict | None,
    year: int,
    month: int,
) -> list[tuple[date, date]]:
    """
    计算某自然月被覆盖的全部结算区间

    :param cycle_type: 周期类型
    :param cycle_config: 周期配置
    :param year: 年
    :param month: 月
    :return:
    """
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    ranges: list[tuple[date, date]] = []
    seen: set[tuple[date, date]] = set()
    cursor = month_start
    while cursor <= month_end:
        start, end = compute_period_range(cycle_type, cycle_config, cursor)
        key = (start, end)
        if key not in seen:
            seen.add(key)
            ranges.append(key)
        cursor = end + timedelta(days=1)
    return ranges


def ranges_overlap(start_a: date, end_a: date, start_b: date, end_b: date) -> bool:
    """两个闭区间是否相交。首尾相接的相邻周期不算相交。"""
    return start_a <= end_b and start_b <= end_a


_PeriodSlot = tuple[int, date, date]
_SiteSpan = tuple[date, date, RiderSalarySettlePeriod | None]
_OVERLAP_FALLBACK = '结算周期与同一范围内的已有周期相交。请先删除开放且没有薪资单的旧周期'
_EXCLUSION_SQLSTATE = '23P01'


def span_is_covered(span_start: date, span_end: date, ranges: list[tuple[date, date]]) -> bool:
    """区间列表是否盖住整个闭区间。区间可以伸出两端，缺任何一天都不算盖住。"""
    clipped: list[tuple[date, date]] = []
    for start, end in ranges:
        if end < span_start or start > span_end:
            continue
        clipped.append((max(start, span_start), min(end, span_end)))
    clipped.sort()
    cursor = span_start
    for start, end in clipped:
        if start > cursor:
            return False
        nxt = end + timedelta(days=1)
        if nxt > cursor:
            cursor = nxt
        if cursor > span_end:
            return True
    return cursor > span_end


def period_overlap_message(period: RiderSalarySettlePeriod) -> str:
    """同一范围内相交时的中文提示。"""
    if int(period.rider_id) == SITE_LEVEL_RIDER_ID:
        kind = '站点级'
        scope = '同一站点的站点级周期不能重叠'
    else:
        kind = '骑手级'
        scope = '同一骑手的骑手级周期不能重叠'
    return (
        f'与已有{kind}结算周期相交（{period.start_date}至{period.end_date}，{status_label(period.status)}）。'
        f'{scope}。请先删除开放且没有薪资单的旧周期'
    )


def _mutual_overlap_message() -> str:
    return '即将生成的结算周期在同一范围内彼此相交。同一站点的站点级周期不能重叠，同一骑手的骑手级周期也不能重叠'


def _partial_cover_message(start: date, end: date) -> str:
    return (
        f'骑手级周期部分覆盖了站点级周期（{start}至{end}）。'
        f'只要和站点级周期相交，该骑手的骑手级周期合起来就必须正好覆盖整个站点级周期'
    )


def _next_cycle_message(start: date, end: date, reason: str) -> str:
    return f'站点级周期（{start}至{end}）{reason}，不能再生成与之相交的骑手级周期。周期配置从下一个完整周期起生效'


def _same_period_slot(period: RiderSalarySettlePeriod, rider_id: int, start_date: date, end_date: date) -> bool:
    return int(period.rider_id) == int(rider_id) and period.start_date == start_date and period.end_date == end_date


def _same_scope_conflict(left: _PeriodSlot, right: _PeriodSlot) -> bool:
    """同 rider_id 的两个区间相交才冲突。不同骑手、站点级和骑手级之间不算。"""
    if left[0] != right[0] or left == right:
        return False
    return ranges_overlap(left[1], left[2], right[1], right[2])


def _is_period_exclusion(exc: IntegrityError) -> bool:
    orig = getattr(exc, 'orig', None)
    state = None if orig is None else getattr(orig, 'sqlstate', None) or getattr(orig, 'pgcode', None)
    if str(state or '') == _EXCLUSION_SQLSTATE:
        return True
    text = str(orig or exc)
    return 'ex_rs_settle_period_no_overlap' in text


async def _periods_at_site(db: AsyncSession, site_id: int) -> list[RiderSalarySettlePeriod]:
    rows = await db.scalars(
        select(RiderSalarySettlePeriod)
        .where(RiderSalarySettlePeriod.site_id == site_id, RiderSalarySettlePeriod.deleted == 0)
        .order_by(RiderSalarySettlePeriod.id.asc())
    )
    return list(rows.all())


async def _first_same_scope_conflict(
    db: AsyncSession,
    *,
    site_id: int,
    rider_id: int,
    start_date: date,
    end_date: date,
) -> RiderSalarySettlePeriod | None:
    """同一站点、同一 rider_id 上相交的未删除周期。完全相同的一条视为已存在。"""
    rows = await db.scalars(
        select(RiderSalarySettlePeriod)
        .where(
            RiderSalarySettlePeriod.site_id == site_id,
            RiderSalarySettlePeriod.rider_id == rider_id,
            RiderSalarySettlePeriod.deleted == 0,
            RiderSalarySettlePeriod.start_date <= end_date,
            RiderSalarySettlePeriod.end_date >= start_date,
        )
        .order_by(RiderSalarySettlePeriod.id.asc())
    )
    for row in rows.all():
        if _same_period_slot(row, rider_id, start_date, end_date):
            continue
        return row
    return None


def _assert_planned_same_scope(planned: list[_PeriodSlot]) -> None:
    for index, left in enumerate(planned):
        for right in planned[index + 1 :]:
            if _same_scope_conflict(left, right):
                raise errors.RequestError(msg=_mutual_overlap_message())


def _collect_ranges(
    existing: list[RiderSalarySettlePeriod],
    planned: list[_PeriodSlot],
) -> tuple[list[_SiteSpan], dict[int, list[tuple[date, date]]]]:
    """已有周期加上本次新区间。完全相同的已有周期不重复计入。"""
    site_spans: list[_SiteSpan] = []
    rider_ranges: dict[int, list[tuple[date, date]]] = {}
    seen: set[_PeriodSlot] = set()
    for period in existing:
        slot = (int(period.rider_id), period.start_date, period.end_date)
        seen.add(slot)
        if slot[0] == SITE_LEVEL_RIDER_ID:
            site_spans.append((period.start_date, period.end_date, period))
        else:
            rider_ranges.setdefault(slot[0], []).append((period.start_date, period.end_date))
    for rider_id, start, end in planned:
        slot = (int(rider_id), start, end)
        if slot in seen:
            continue
        seen.add(slot)
        if slot[0] == SITE_LEVEL_RIDER_ID:
            site_spans.append((start, end, None))
        else:
            rider_ranges.setdefault(slot[0], []).append((start, end))
    return site_spans, rider_ranges


def _assert_cross_scope_cover(
    site_spans: list[_SiteSpan],
    rider_ranges: dict[int, list[tuple[date, date]]],
) -> None:
    """骑手级只要和某个站点级相交，就必须正好盖住该站点级的每一天。"""
    for start, end, _period in site_spans:
        for ranges in rider_ranges.values():
            hits = ranges_overlap_any(ranges, start, end)
            if hits and not span_is_covered(start, end, ranges):
                raise errors.RequestError(msg=_partial_cover_message(start, end))


def ranges_overlap_any(ranges: list[tuple[date, date]], start: date, end: date) -> bool:
    """任一区间与目标闭区间相交。"""
    return any(ranges_overlap(range_start, range_end, start, end) for range_start, range_end in ranges)


def expand_leave_settlement_span(
    *,
    cycle_start: date,
    cycle_end: date,
    site_spans: list[tuple[date, date]],
) -> tuple[date, date]:
    """
    把离职日所在的站点周期扩成能整段盖住所碰站点级周期的闭区间

    月中离职时，结束日可能晚于离职日，这样以后生成站点级周期才不会变成部分覆盖。
    算薪仍只计到离职日。相邻但不相交的周期不会被扩进来。

    :param cycle_start: 离职日所在站点周期的开始日期
    :param cycle_end: 离职日所在站点周期的结束日期
    :param site_spans: 已有站点级周期的起止
    :return:
    """
    if cycle_end < cycle_start:
        raise ValueError('站点周期结束日不能早于开始日')
    start, end = cycle_start, cycle_end
    progressed = True
    while progressed:
        progressed = False
        for span_start, span_end in site_spans:
            if span_end < span_start:
                continue
            if not ranges_overlap(start, end, span_start, span_end):
                continue
            if span_is_covered(span_start, span_end, [(start, end)]):
                continue
            new_start = min(start, span_start)
            new_end = max(end, span_end)
            if new_start != start or new_end != end:
                start, end = new_start, new_end
                progressed = True
    return start, end


def leave_settlement_remark(leave_date: date) -> str:
    """离职结算周期备注。"""
    return f'离职结算，计薪截至{leave_date.isoformat()}'


def leave_settlement_hint(leave_date: date, start_date: date, end_date: date, *, reused: bool) -> str:
    """告诉管理员计薪截止到哪一天，以及周期为何可能长于离职日。"""
    span = f'{start_date.isoformat()}至{end_date.isoformat()}'
    prefix = f'离职日已在骑手级结算周期（{span}）内，沿用该周期' if reused else f'已生成离职结算周期（{span}）'
    if end_date > leave_date:
        return f'{prefix}。计薪截至{leave_date.isoformat()}。为整段覆盖碰到的站点级周期，周期结束日晚于离职日'
    return f'{prefix}。计薪截至{leave_date.isoformat()}'


def leave_settlement_result(
    period: RiderSalarySettlePeriod,
    leave_date: date,
    *,
    created: bool,
) -> LeaveSettlementResult:
    """组装离职结算周期返回值。"""
    return LeaveSettlementResult(
        period_id=int(period.id),
        site_id=int(period.site_id),
        rider_id=int(period.rider_id),
        start_date=period.start_date,
        end_date=period.end_date,
        status=period.status,
        leave_date=leave_date,
        created=created,
        remark=period.remark,
        hint=leave_settlement_hint(leave_date, period.start_date, period.end_date, reused=not created),
    )


def _new_rider_slots(existing: list[RiderSalarySettlePeriod], planned: list[_PeriodSlot]) -> list[_PeriodSlot]:
    existing_keys = {(int(period.rider_id), period.start_date, period.end_date) for period in existing}
    return [
        (int(rider_id), start, end)
        for rider_id, start, end in planned
        if int(rider_id) != SITE_LEVEL_RIDER_ID and (int(rider_id), start, end) not in existing_keys
    ]


async def _site_payroll_riders(db: AsyncSession, period_ids: list[int]) -> set[tuple[int, int]]:
    if not period_ids:
        return set()
    rows = await db.execute(
        select(RiderSalaryPayroll.period_id, RiderSalaryPayroll.rider_id)
        .where(RiderSalaryPayroll.period_id.in_(period_ids), RiderSalaryPayroll.deleted == 0)
        .distinct()
    )
    return {(int(period_id), int(rider_id)) for period_id, rider_id in rows.all()}


async def _assert_next_full_cycle(
    db: AsyncSession,
    *,
    new_slots: list[_PeriodSlot],
    site_spans: list[_SiteSpan],
) -> None:
    """已锁账或已有该骑手薪资单的站点级周期，不能再被新的骑手级周期盖住。"""
    persisted = [period for _start, _end, period in site_spans if period is not None]
    if not new_slots or not persisted:
        return
    payrolls = await _site_payroll_riders(db, [int(period.id) for period in persisted])
    for rider_id, start, end in new_slots:
        for period in persisted:
            if not ranges_overlap(start, end, period.start_date, period.end_date):
                continue
            if is_status_locked(period.status):
                raise errors.RequestError(msg=_next_cycle_message(period.start_date, period.end_date, '已锁账'))
            if (int(period.id), rider_id) in payrolls:
                raise errors.RequestError(
                    msg=_next_cycle_message(period.start_date, period.end_date, '已有该骑手的薪资单')
                )


async def assert_period_plan(
    db: AsyncSession,
    *,
    site_id: int,
    planned: list[_PeriodSlot],
) -> None:
    """
    校验即将生成的周期

    同一站点的站点级之间、同一骑手的骑手级之间不得相交。
    骑手级与站点级相交时必须正好盖住整个站点级周期。
    被盖住的站点级周期若已锁账，或该骑手已有未删除薪资单，则拒绝，配置从下一个完整周期起生效。
    完全相同的已有周期可以重复生成。

    :param db: 数据库会话
    :param site_id: 站点 ID
    :param planned: (骑手 ID, 开始日期, 结束日期)，0 表示站点级
    :return:
    """
    _assert_planned_same_scope(planned)
    existing = await _periods_at_site(db, site_id)
    for rider_id, start_date, end_date in planned:
        conflict = await _first_same_scope_conflict(
            db,
            site_id=site_id,
            rider_id=rider_id,
            start_date=start_date,
            end_date=end_date,
        )
        if conflict is not None:
            raise errors.RequestError(msg=period_overlap_message(conflict))
    site_spans, rider_ranges = _collect_ranges(existing, planned)
    _assert_cross_scope_cover(site_spans, rider_ranges)
    await _assert_next_full_cycle(db, new_slots=_new_rider_slots(existing, planned), site_spans=site_spans)


def parse_year_month(month: str) -> tuple[int, int]:
    """
    解析 YYYY-MM

    :param month: 年月
    :return:
    """
    text = (month or '').strip()
    parts = text.split('-')
    if len(parts) != 2:
        raise errors.RequestError(msg='月份格式应为 YYYY-MM')
    try:
        year = int(parts[0])
        mon = int(parts[1])
    except ValueError as exc:
        raise errors.RequestError(msg='月份格式应为 YYYY-MM') from exc
    if mon < 1 or mon > 12:
        raise errors.RequestError(msg='月份格式应为 YYYY-MM')
    return year, mon


def status_label(status: str) -> str:
    """周期状态中文"""
    try:
        return PeriodStatus(status).label
    except ValueError:
        return status


def action_for_target(target_status: str) -> str:
    """目标状态对应动作名"""
    mapping = {
        PeriodStatus.locked.value: '锁账',
        PeriodStatus.paid.value: '标记发薪',
        PeriodStatus.reopened.value: '反冲补发',
    }
    return mapping.get(target_status, target_status)


def assert_can_transition(current_status: str, target_status: str) -> str:
    """
    校验周期状态迁移，返回动作名

    :param current_status: 当前状态
    :param target_status: 目标状态
    :return:
    """
    action = _ALLOWED_TRANSITIONS.get((current_status, target_status))
    if action is None:
        raise errors.RequestError(
            msg=f'结算周期当前状态为{status_label(current_status)}，不允许执行{action_for_target(target_status)}'
        )
    return action


PERIOD_STATUS_CHANGED_MSG = '结算周期状态已变化，请刷新后重试'


def normalize_expected_status(expected_status: str | None) -> str | None:
    """空白的期望状态视为未传。"""
    if expected_status is None:
        return None
    text = expected_status.strip()
    return text or None


def assert_expected_period_status(current_status: str, expected_status: str | None) -> None:
    """
    期望状态与当前状态不一致时返回 409，调用方不得继续迁移或写审计

    :param current_status: 库中当前状态
    :param expected_status: 客户端看到的状态，空表示不校验
    :return:
    """
    expected = normalize_expected_status(expected_status)
    if expected is not None and expected != current_status:
        raise errors.ConflictError(msg=PERIOD_STATUS_CHANGED_MSG)


def _period_transition_values(target_status: str, operator: Request) -> dict[str, Any]:
    """本次迁移要写入的列。不修改入参对象。"""
    now = timezone.now()
    user_id = _operator_id(operator)
    values: dict[str, Any] = {'status': target_status, 'updated_time': now}
    if target_status == PeriodStatus.locked.value:
        values['locked_by'] = user_id
        values['locked_time'] = now
    elif target_status == PeriodStatus.paid.value:
        values['paid_by'] = user_id
        values['paid_time'] = now
    elif target_status == PeriodStatus.reopened.value:
        values['reopened_by'] = user_id
        values['reopened_time'] = now
    return values


def stale_lock_message(job_nos: list[str]) -> str:
    """锁账 stale 前置错误文案"""
    return f'存在需重算的薪资结果：工号 {"、".join(job_nos)}，请先重算'


def current_payroll_kind(period_status: str) -> str:
    """锁账要求的当前薪资单类型：补发中为补发，其余为正常"""
    if period_status == PeriodStatus.reopened.value:
        return PayrollKind.supplement.value
    return PayrollKind.normal.value


def uncalculated_lock_message(job_nos: list[str]) -> str:
    """锁账缺少当前类型草稿时的错误文案"""
    return f'存在未算薪骑手：工号 {"、".join(job_nos)}，请先算薪'


EMPTY_PERIOD_MARK_PAID_HINT = '本期没有薪资单'
CARRY_FORWARD_REASON = '金额无需变化，沿用反冲前原单'
CARRY_FORWARD_NOTE = '沿用原单'
_COPY_MONEY_FIELDS = (
    'per_order_total',
    'daily_total',
    'period_total',
    'bonus_total',
    'penalty_total',
    'gross',
    'deduction_total',
    'advance_deduction',
    'net',
)
_COPY_COUNT_FIELDS = ('order_count', 'valid_order_count')


def missing_supplement_lock_message(job_nos: list[str]) -> str:
    """补发中的周期缺少补发草稿时的错误文案"""
    return f'存在缺补发单的骑手：工号 {"、".join(job_nos)}，请先补算或沿用原单'


def is_reversed_original(payroll: Any) -> bool:
    """已反冲、且本身不是反冲单的原单（含上一轮补发单）"""
    if int(getattr(payroll, 'deleted', 0) or 0):
        return False
    if getattr(payroll, 'kind', None) == PayrollKind.reversal.value:
        return False
    if getattr(payroll, 'status', None) == PayrollStatus.voided.value:
        return False
    return bool(getattr(payroll, 'reversed', False))


def fresh_supplement_rider_ids(drafts: list[Any]) -> set[int]:
    """已有非 stale 补发草稿的骑手"""
    rider_ids: set[int] = set()
    for row in drafts:
        if int(getattr(row, 'deleted', 0) or 0):
            continue
        if getattr(row, 'status', PayrollStatus.draft.value) != PayrollStatus.draft.value:
            continue
        if bool(getattr(row, 'stale', False)):
            continue
        if getattr(row, 'kind', None) != PayrollKind.supplement.value:
            continue
        rider_ids.add(int(row.rider_id))
    return rider_ids


def latest_reversed_originals(payrolls: list[Any]) -> dict[int, Any]:
    """每个骑手保留 id 最大的已反冲原单"""
    latest: dict[int, Any] = {}
    for payroll in payrolls:
        if not is_reversed_original(payroll):
            continue
        rider_id = int(payroll.rider_id)
        current = latest.get(rider_id)
        if current is None or int(getattr(payroll, 'id', 0) or 0) >= int(getattr(current, 'id', 0) or 0):
            latest[rider_id] = payroll
    return latest


def missing_supplement_rider_ids(payrolls: list[Any], drafts: list[Any]) -> list[int]:
    """
    有已反冲原单、且没有非 stale 补发草稿的骑手

    按原单 id 升序，保证锁账错误里的工号顺序稳定。

    :param payrolls: 周期内全部薪资单
    :param drafts: 周期内草稿
    :return:
    """
    latest = latest_reversed_originals(payrolls)
    covered = fresh_supplement_rider_ids(drafts)
    ordered = sorted(latest.values(), key=lambda row: int(getattr(row, 'id', 0) or 0))
    return [int(row.rider_id) for row in ordered if int(row.rider_id) not in covered]


def supplement_draft_for(drafts: list[Any], rider_id: int) -> Any | None:
    """该骑手已有的补发草稿（含 stale），没有则返回空"""
    for row in drafts:
        if int(getattr(row, 'deleted', 0) or 0):
            continue
        if getattr(row, 'status', None) != PayrollStatus.draft.value:
            continue
        if getattr(row, 'kind', None) != PayrollKind.supplement.value:
            continue
        if int(row.rider_id) == rider_id:
            return row
    return None


def period_net_total(payrolls: list[Any]) -> Decimal:
    """未删除、非作废薪资单的实发合计。原单与反冲单抵消后，净额等于仍有效的补发单。"""
    total = ZERO
    for payroll in payrolls:
        if int(getattr(payroll, 'deleted', 0) or 0):
            continue
        if getattr(payroll, 'status', None) == PayrollStatus.voided.value:
            continue
        total += q2(getattr(payroll, 'net', ZERO) or ZERO)
    return q2(total)


def active_supplement_net_total(payrolls: list[Any]) -> Decimal:
    """未被反冲、未作废的补发单实发合计"""
    total = ZERO
    for payroll in payrolls:
        if int(getattr(payroll, 'deleted', 0) or 0):
            continue
        if getattr(payroll, 'status', None) == PayrollStatus.voided.value:
            continue
        if getattr(payroll, 'kind', None) != PayrollKind.supplement.value:
            continue
        if bool(getattr(payroll, 'reversed', False)):
            continue
        total += q2(getattr(payroll, 'net', ZERO) or ZERO)
    return q2(total)


def supplement_amounts_from_original(original: Any) -> dict[str, Any]:
    """沿用原单时要写到补发草稿上的金额，与原单相同"""
    data: dict[str, Any] = {name: q2(getattr(original, name, ZERO) or ZERO) for name in _COPY_MONEY_FIELDS}
    for name in _COPY_COUNT_FIELDS:
        data[name] = int(getattr(original, name, 0) or 0)
    versions = getattr(original, 'plan_version_ids', None)
    data['plan_version_ids'] = list(versions) if versions else None
    warnings = [str(item) for item in (getattr(original, 'warnings', None) or []) if str(item) != CARRY_FORWARD_NOTE]
    warnings.append(CARRY_FORWARD_NOTE)
    data['warnings'] = warnings
    return data


def apply_supplement_from_original(payroll: Any, original: Any) -> None:
    """把原单金额写到补发草稿上，并清掉 stale"""
    for key, value in supplement_amounts_from_original(original).items():
        setattr(payroll, key, value)
    payroll.kind = PayrollKind.supplement.value
    payroll.status = PayrollStatus.draft.value
    payroll.stale = False
    payroll.reversed = False
    payroll.reversed_of_id = None
    payroll.calc_version = int(getattr(original, 'calc_version', 0) or 0) + 1


def reapply_advance_amount(advance: Any, amount: Decimal | float | str) -> Decimal:
    """
    把反冲时退回的预支按原单明细再次抵扣

    余额不够时只扣到 0，返回实际扣到的金额。

    :param advance: 预支单
    :param amount: 原单明细金额（通常为负）
    :return:
    """
    need = q2(abs(q2(amount)))
    remaining = q2(getattr(advance, 'remaining_amount', None) or ZERO)
    applied = q2(min(remaining, need)) if remaining > 0 else ZERO
    if applied <= 0:
        return ZERO
    new_remaining = q2(remaining - applied)
    new_deducted = q2((getattr(advance, 'deducted_amount', None) or ZERO) + applied)
    advance.remaining_amount = new_remaining
    advance.deducted_amount = new_deducted
    if new_remaining <= 0:
        advance.deduct_status = DeductStatus.done.value
    elif new_deducted > 0:
        advance.deduct_status = DeductStatus.partial.value
    else:
        advance.deduct_status = DeductStatus.none.value
    return applied


def align_carried_advance(payroll: Any, details: list[Any]) -> None:
    """按实际再次抵扣的明细回写预支抵扣和实发，使台账与明细一致。"""
    applied = ZERO
    for detail in details:
        if getattr(detail, 'source', None) != DetailSource.advance.value:
            continue
        applied += q2(abs(q2(getattr(detail, 'amount', ZERO) or ZERO)))
    applied = q2(applied)
    payroll.advance_deduction = applied
    payroll.net = q2(
        q2(getattr(payroll, 'gross', ZERO) or ZERO) - q2(getattr(payroll, 'deduction_total', ZERO) or ZERO) - applied
    )


def _carry_forward_net_clause(original: Any, supplement: Any) -> str:
    """沿用原单审计里的实发说明。余额够时与原单相同，不够时写明差额。"""
    carried_net = q2(getattr(supplement, 'net', ZERO) or ZERO)
    original_net = q2(getattr(original, 'net', ZERO) or ZERO)
    if carried_net == original_net:
        return f'补发实发{carried_net}，与反冲前原单相同'
    return f'补发实发{carried_net}，原单实发{original_net}，因预支余额不足未全额抵扣'


def classify_lock_gaps(
    expected_rider_ids: list[int],
    drafts: list[Any],
    *,
    kind: str,
) -> tuple[list[int], list[int]]:
    """
    对照应算骑手与草稿，返回（未算薪，需重算）

    有当前类型且非 stale 的草稿视为已算薪。没有任何这类草稿、且也没有 stale 草稿，视为未算薪。
    只要存在 stale 草稿（含应算集合之外的人）就列入需重算，因为锁账会把全部草稿定稿。
    作废单、非草稿不计入。

    :param expected_rider_ids: 应算骑手，顺序保留
    :param drafts: 周期内草稿
    :param kind: 当前薪资单类型
    :return:
    """
    fresh_current: set[int] = set()
    stale_seen: set[int] = set()
    stale_order: list[int] = []
    for row in drafts:
        if int(getattr(row, 'deleted', 0) or 0):
            continue
        if getattr(row, 'status', PayrollStatus.draft.value) != PayrollStatus.draft.value:
            continue
        rider_id = int(row.rider_id)
        if bool(getattr(row, 'stale', False)):
            if rider_id not in stale_seen:
                stale_seen.add(rider_id)
                stale_order.append(rider_id)
            continue
        if getattr(row, 'kind', None) == kind:
            fresh_current.add(rider_id)
    expected_set = set(expected_rider_ids)
    uncalculated = [
        rider_id for rider_id in expected_rider_ids if rider_id not in fresh_current and rider_id not in stale_seen
    ]
    needs_recalc = [rider_id for rider_id in expected_rider_ids if rider_id in stale_seen]
    needs_recalc.extend(rider_id for rider_id in stale_order if rider_id not in expected_set)
    return uncalculated, needs_recalc


def lock_block_message(
    *,
    uncalculated_job_nos: list[str],
    recalc_job_nos: list[str],
    missing_supplement_job_nos: list[str] | None = None,
) -> str | None:
    """把缺补发单、未算薪、需重算拼成一条锁账错误；都没有则返回空"""
    parts: list[str] = []
    if missing_supplement_job_nos:
        parts.append(missing_supplement_lock_message(missing_supplement_job_nos))
    if uncalculated_job_nos:
        parts.append(uncalculated_lock_message(uncalculated_job_nos))
    if recalc_job_nos:
        parts.append(stale_lock_message(recalc_job_nos))
    if not parts:
        return None
    return '；'.join(parts)


def _append_eval_failure_label(
    labels: list[str],
    seen: set[tuple[str, str]],
    job_no: str,
    rider_name: str | None,
    item_name: str,
) -> None:
    """同一骑手同一方案项只记一次。"""
    key = (job_no, item_name)
    if key in seen:
        return
    seen.add(key)
    if rider_name:
        labels.append(f'{rider_name}（工号{job_no}）方案项「{item_name}」')
    elif job_no:
        labels.append(f'工号{job_no}方案项「{item_name}」')
    else:
        labels.append(f'方案项「{item_name}」')


def _draft_eval_identity(payroll: Any, rider_map: dict[int, Any]) -> tuple[str, str | None]:
    rider = rider_map.get(int(payroll.rider_id))
    job_no = getattr(rider, 'job_no', None) if rider is not None else None
    rider_name = getattr(rider, 'name', None) if rider is not None else None
    return (str(job_no) if job_no else str(payroll.rider_id), str(rider_name) if rider_name else None)


def _labels_from_payroll_warnings(
    drafts: list[Any],
    rider_map: dict[int, Any],
    labels: list[str],
    seen: set[tuple[str, str]],
) -> None:
    for payroll in drafts:
        raw_warnings = [str(item) for item in (getattr(payroll, 'warnings', None) or []) if item]
        hits = [item for item in raw_warnings if is_eval_failure_warning(item)]
        if not hits:
            continue
        job_no, rider_name = _draft_eval_identity(payroll, rider_map)
        for warning in hits:
            _append_eval_failure_label(labels, seen, job_no, rider_name, eval_failure_item_name(warning))


def _rider_name_for_job(rider_map: dict[int, Any], job_no: str) -> str | None:
    if not job_no:
        return None
    for rider in rider_map.values():
        if getattr(rider, 'job_no', None) == job_no:
            name = getattr(rider, 'name', None)
            return str(name) if name else None
    return None


def _labels_from_redis_warnings(
    redis_warnings: list[str],
    rider_map: dict[int, Any],
    labels: list[str],
    seen: set[tuple[str, str]],
) -> None:
    for warning in redis_warnings:
        if not is_eval_failure_warning(warning):
            continue
        job_no = eval_failure_job_no(warning) or ''
        _append_eval_failure_label(
            labels,
            seen,
            job_no,
            _rider_name_for_job(rider_map, job_no),
            eval_failure_item_name(warning),
        )


def collect_eval_failure_labels(
    drafts: list[Any],
    rider_map: dict[int, Any],
    redis_warnings: list[str],
) -> list[str]:
    """从草稿告警和周期告警里列出骑手与方案项，同一人同一项只出现一次。"""
    labels: list[str] = []
    seen: set[tuple[str, str]] = set()
    _labels_from_payroll_warnings(drafts, rider_map, labels, seen)
    _labels_from_redis_warnings(redis_warnings, rider_map, labels, seen)
    return labels


def eval_failure_lock_message(labels: list[str]) -> str | None:
    """把求值失败清单拼成锁账错误。"""
    if not labels:
        return None
    return f'存在公式求值失败：{"、".join(labels)}，请先修正公式后重算'


def _merge_lock_message(message: str | None, extra: str | None) -> str | None:
    """把多条锁账原因拼成一条。"""
    parts = [item for item in (message, extra) if item]
    if not parts:
        return None
    return '；'.join(parts)


def _job_no_list(rider_ids: list[int], rider_map: dict[int, Any]) -> list[str]:
    job_nos: list[str] = []
    seen: set[str] = set()
    for rider_id in rider_ids:
        rider = rider_map.get(rider_id)
        job_no = rider.job_no if rider is not None and getattr(rider, 'job_no', None) else str(rider_id)
        if job_no not in seen:
            seen.add(job_no)
            job_nos.append(job_no)
    return job_nos


def _rider_items(rider_ids: list[int], rider_map: dict[int, Any]) -> list[LockCheckRiderItem]:
    items: list[LockCheckRiderItem] = []
    for rider_id in rider_ids:
        rider = rider_map.get(rider_id)
        job_no = rider.job_no if rider is not None and getattr(rider, 'job_no', None) else str(rider_id)
        name = rider.name if rider is not None else None
        items.append(LockCheckRiderItem(rider_id=rider_id, job_no=job_no, rider_name=name))
    return items


def site_level_lock_excluded_rider_ids(overlapping_periods: list[Any]) -> set[int]:
    """站点级锁账/解锁时，跳过已被骑手级周期覆盖的骑手"""
    excluded: set[int] = set()
    for row in overlapping_periods:
        rider_id = int(getattr(row, 'rider_id', 0) or 0)
        if rider_id and rider_id != SITE_LEVEL_RIDER_ID:
            excluded.add(rider_id)
    return excluded


def reversible_payrolls(payrolls: list[Any]) -> list[Any]:
    """筛选需要生成反冲单的薪资结果"""
    result: list[Any] = []
    for payroll in payrolls:
        if getattr(payroll, 'kind', None) == PayrollKind.reversal.value:
            continue
        if getattr(payroll, 'reversed', False):
            continue
        if getattr(payroll, 'status', None) not in {PayrollStatus.finalized.value, PayrollStatus.paid.value}:
            continue
        result.append(payroll)
    return result


def empty_kind_counts() -> dict[str, int]:
    """空的 kind 分布"""
    return dict.fromkeys(_KIND_KEYS, 0)


def _operator_id(request: Request) -> int:
    return int(getattr(getattr(request, 'user', None), 'id', 0) or 0)


def _operator_name(request: Request) -> str:
    user = getattr(request, 'user', None)
    return getattr(user, 'nickname', None) or getattr(user, 'username', None) or '未知'


def _now_str() -> str:
    return timezone.to_str(timezone.now())


def _period_label(site: RiderSalarySite | None, period: RiderSalarySettlePeriod) -> str:
    site_name = site.name if site is not None else str(period.site_id)
    return f'周期{site_name} {period.start_date}~{period.end_date}'


def _existing_generated_periods(items: list[GetGeneratedPeriodItem]) -> dict[str, Any]:
    """生成前已经存在、本次跳过的周期。只用内存清单，不再查库。"""
    existing = [
        {
            'id': item.id,
            'rider_id': item.rider_id,
            'cycle_type': item.cycle_type,
            'start_date': item.start_date.isoformat(),
            'end_date': item.end_date.isoformat(),
            'status': item.status,
        }
        for item in items
        if not item.created
    ]
    return {'existing_count': len(existing), 'existing': existing}


def _append_unique(target: list[str], items: list[str] | None) -> None:
    """把告警追加进列表，空文案和重复项跳过。"""
    for item in items or []:
        text = str(item)
        if text and text not in target:
            target.append(text)


def _cycle_value(cycle_type: CycleType | str | None, fallback: str) -> str:
    if cycle_type is None:
        return fallback
    if isinstance(cycle_type, CycleType):
        return cycle_type.value
    return str(cycle_type)


async def _calculate_period_background(*, period_id: int, rider_ids: list[int] | None) -> None:
    """在当前会话里执行算薪作业。失败写入周期告警，供周期详情展示。"""
    from backend.common.log import log
    from backend.plugin.rider_salary.service.calc_job_service import run_period_calc_in_session

    try:
        async with async_db_session.begin() as db:
            await run_period_calc_in_session(db, period_id=period_id, rider_ids=rider_ids, operator=None)
    except Exception as exc:
        log.exception('后台算薪失败 period_id=%s', period_id)
        await append_period_calc_warning(period_id, f'后台算薪失败：{exc}')


class PeriodService:
    """结算周期服务"""

    async def get_or_create_period(
        self,
        db: AsyncSession,
        site_id: int,
        rider_id: int | None,
        any_date: date,
    ) -> RiderSalarySettlePeriod:
        """
        按站点/骑手配置获取或创建覆盖该日的周期。骑手有 settle_cycle_override 时返回骑手级。

        :param db: 数据库会话
        :param site_id: 站点 ID
        :param rider_id: 骑手 ID，空则站点级
        :param any_date: 周期内任意日期
        :return:
        """
        site = await site_dao.get(db, site_id)
        if site is None:
            raise errors.NotFoundError(msg='站点不存在')
        rider = None
        if rider_id:
            rider = await db.scalar(
                select(RiderSalaryRider).where(RiderSalaryRider.id == rider_id, RiderSalaryRider.deleted == 0)
            )
            if rider is None:
                raise errors.NotFoundError(msg='骑手不存在')
        period_rider_id, cycle_type, cycle_config = self._resolve_cycle(site, rider)
        covering = await settle_period_dao.get_covering(
            db, site_id=site_id, rider_id=period_rider_id, any_date=any_date
        )
        if covering is not None:
            return covering
        try:
            start, end = compute_period_range(cycle_type, cycle_config, any_date)
        except ValueError as exc:
            raise errors.RequestError(msg=str(exc)) from exc
        return await self._create_if_absent(
            db,
            site_id=site_id,
            rider_id=period_rider_id,
            cycle_type=cycle_type,
            start_date=start,
            end_date=end,
        )

    @staticmethod
    def _resolve_cycle(
        site: RiderSalarySite,
        rider: RiderSalaryRider | None,
    ) -> tuple[int, str, dict | None]:
        if rider is not None and rider.settle_cycle_override:
            return (
                rider.id,
                _cycle_value(rider.settle_cycle_override, site.settle_cycle),
                rider.cycle_config_override,
            )
        return SITE_LEVEL_RIDER_ID, _cycle_value(site.settle_cycle, CycleType.month.value), site.cycle_config

    async def _create_if_absent(
        self,
        db: AsyncSession,
        *,
        site_id: int,
        rider_id: int,
        cycle_type: str,
        start_date: date,
        end_date: date,
        plan_checked: bool = False,
        remark: str | None = None,
    ) -> RiderSalarySettlePeriod:
        existing = await settle_period_dao.get_by_unique(db, site_id=site_id, rider_id=rider_id, start_date=start_date)
        if existing is not None and existing.end_date == end_date:
            return existing
        if plan_checked:
            conflict = await _first_same_scope_conflict(
                db,
                site_id=site_id,
                rider_id=rider_id,
                start_date=start_date,
                end_date=end_date,
            )
            if conflict is not None:
                raise errors.RequestError(msg=period_overlap_message(conflict))
        else:
            await assert_period_plan(db, site_id=site_id, planned=[(rider_id, start_date, end_date)])
        try:
            async with db.begin_nested():
                return await settle_period_dao.create(
                    db,
                    site_id=site_id,
                    rider_id=rider_id,
                    cycle_type=cycle_type,
                    start_date=start_date,
                    end_date=end_date,
                    remark=remark,
                )
        except IntegrityError as exc:
            if _is_period_exclusion(exc):
                raced = await _first_same_scope_conflict(
                    db,
                    site_id=site_id,
                    rider_id=rider_id,
                    start_date=start_date,
                    end_date=end_date,
                )
                message = period_overlap_message(raced) if raced is not None else _OVERLAP_FALLBACK
                raise errors.RequestError(msg=message) from exc
            existed = await settle_period_dao.get_by_unique(
                db, site_id=site_id, rider_id=rider_id, start_date=start_date
            )
            if existed is not None and existed.end_date == end_date:
                return existed
            if existed is not None:
                raise errors.RequestError(msg=period_overlap_message(existed)) from exc
            raise

    def transition(
        self,
        period: RiderSalarySettlePeriod,
        target_status: str,
        operator: Request,
        reason: str | None,
    ) -> str:
        """
        集中状态迁移。非法迁移抛 400。

        :param period: 周期
        :param target_status: 目标状态
        :param operator: 操作人
        :param reason: 原因
        :return: 动作名
        """
        action = assert_can_transition(period.status, target_status)
        if target_status in _REASON_REQUIRED_TARGETS:
            require_reason(action, reason)
        for key, value in _period_transition_values(target_status, operator).items():
            if key == 'updated_time':
                continue
            setattr(period, key, value)
        return action

    async def _commit_period_transition(
        self,
        db: AsyncSession,
        period: Any,
        target_status: str,
        operator: Request,
        reason: str | None,
    ) -> None:
        """
        条件更新周期状态。``UPDATE … WHERE id=? AND status=?``，抢不到行返回 409。

        假会话没有真实行锁，仍改内存对象，供既有单测使用。

        :param db: 数据库会话
        :param period: 周期
        :param target_status: 目标状态
        :param operator: 操作人
        :param reason: 原因
        :return:
        """
        if not isinstance(period, RiderSalarySettlePeriod) or not isinstance(db, AsyncSession):
            self.transition(period, target_status, operator, reason)
            return
        current = period.status
        assert_can_transition(current, target_status)
        if target_status in _REASON_REQUIRED_TARGETS:
            require_reason(action_for_target(target_status), reason)
        values = _period_transition_values(target_status, operator)
        result = await db.execute(
            update(RiderSalarySettlePeriod)
            .where(
                RiderSalarySettlePeriod.id == period.id,
                RiderSalarySettlePeriod.status == current,
                RiderSalarySettlePeriod.deleted == 0,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if int(result.rowcount or 0) != 1:
            raise errors.ConflictError(msg=PERIOD_STATUS_CHANGED_MSG)
        for key, value in values.items():
            set_committed_value(period, key, value)

    async def get_list(
        self,
        *,
        db: AsyncSession,
        request: Request,
        site_id: int | None,
        rider_id: int | None,
        status: str | None,
        month: str | None,
        stale: bool | None = None,
    ) -> dict[str, Any]:
        """
        分页周期列表

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID
        :param rider_id: 骑手 ID
        :param status: 状态，多个用英文逗号分隔
        :param month: 年月 YYYY-MM
        :param stale: 是否存在需重算草稿；None 表示不按此项筛选
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        if site_id is not None:
            assert_site_visible(visible, site_id)
        month_start = month_end = None
        if month:
            year, mon = parse_year_month(month)
            month_start = date(year, mon, 1)
            month_end = date(year, mon, monthrange(year, mon)[1])
        stmt = await settle_period_dao.get_select(
            site_id=site_id,
            rider_id=rider_id,
            status=status,
            month_start=month_start,
            month_end=month_end,
            site_ids=visible,
            stale=stale,
        )
        page = await paging_data(db, stmt)
        items = page.get('items') or []
        period_ids = [item['id'] for item in items]
        stats = await self._payroll_stats(db, period_ids)
        names = await self._period_names(db, items)
        enriched: list[dict[str, Any]] = []
        for item in items:
            pk = item['id']
            extra = stats.get(pk, self._empty_stats())
            extra.update(names.get(pk, {}))
            enriched.append({**item, **extra})
        page['items'] = [GetPeriodListItem.model_validate(row) for row in enriched]
        return page

    async def get(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
    ) -> GetPeriodWithPayrolls:
        """
        周期详情 + 全部 payroll 摘要

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :return:
        """
        period, site, rider = await self._load_visible(db, request, pk)
        payrolls = await payroll_dao.select_models_order(db, 'id', 'asc', period_id=period.id, deleted=0)
        rider_map = await self._rider_map(db, [row.rider_id for row in payrolls])
        items: list[GetPeriodPayrollItem] = []
        for row in payrolls:
            data = GetPeriodPayrollItem.model_validate(row)
            info = rider_map.get(row.rider_id)
            if info is not None:
                data.job_no = info.job_no
                data.rider_name = info.name
            items.append(data)
        stats = (await self._payroll_stats(db, [period.id])).get(period.id, self._empty_stats())
        detail = self._to_detail(period, site, rider)
        payload = detail.model_dump()
        payload.update(stats)
        result = GetPeriodWithPayrolls.model_validate(payload)
        result.payrolls = items
        result.calc_warnings = await read_period_calc_warnings(period.id)
        return result

    async def get_for_date(
        self,
        *,
        db: AsyncSession,
        request: Request,
        site_id: int,
        rider_id: int | None,
        biz_date: date,
    ) -> GetPeriodForDateResult:
        """
        查询覆盖该日的周期；不存在则按配置计算区间并 exists=false

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID
        :param rider_id: 骑手 ID
        :param biz_date: 业务日期
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, site_id)
        site = await site_dao.get(db, site_id)
        if site is None:
            raise errors.NotFoundError(msg='站点不存在')
        rider = None
        if rider_id:
            rider = await db.scalar(
                select(RiderSalaryRider).where(RiderSalaryRider.id == rider_id, RiderSalaryRider.deleted == 0)
            )
            if rider is None:
                raise errors.NotFoundError(msg='骑手不存在')
        period_rider_id, cycle_type, cycle_config = self._resolve_cycle(site, rider)
        covering = await settle_period_dao.get_covering(
            db, site_id=site_id, rider_id=period_rider_id, any_date=biz_date
        )
        if covering is not None:
            rider_obj = rider if covering.rider_id else None
            if covering.rider_id and (rider is None or rider.id != covering.rider_id):
                rider_obj = await db.scalar(
                    select(RiderSalaryRider).where(
                        RiderSalaryRider.id == covering.rider_id, RiderSalaryRider.deleted == 0
                    )
                )
            return GetPeriodForDateResult(
                exists=True,
                site_id=site_id,
                rider_id=covering.rider_id,
                cycle_type=covering.cycle_type,
                start_date=covering.start_date,
                end_date=covering.end_date,
                period=self._to_detail(covering, site, rider_obj),
            )
        try:
            start, end = compute_period_range(cycle_type, cycle_config, biz_date)
        except ValueError as exc:
            raise errors.RequestError(msg=str(exc)) from exc
        return GetPeriodForDateResult(
            exists=False,
            site_id=site_id,
            rider_id=period_rider_id,
            cycle_type=cycle_type,
            start_date=start,
            end_date=end,
            period=None,
        )

    async def generate(
        self,
        *,
        db: AsyncSession,
        request: Request,
        obj: GeneratePeriodParam,
    ) -> GeneratePeriodResult:
        """
        按站点配置生成该月覆盖的周期，并为有周期覆盖的骑手生成骑手级周期

        :param db: 数据库会话
        :param request: 请求对象
        :param obj: 参数
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, obj.site_id)
        site = await site_dao.get(db, obj.site_id)
        if site is None:
            raise errors.NotFoundError(msg='站点不存在')
        year, month = parse_year_month(obj.month)
        planned: list[tuple[int, str, date, date]] = []
        site_cycle = _cycle_value(site.settle_cycle, CycleType.month.value)
        for start, end in covering_period_ranges(site.settle_cycle, site.cycle_config, year, month):
            planned.append((SITE_LEVEL_RIDER_ID, site_cycle, start, end))
        riders = list(
            (
                await db.scalars(
                    select(RiderSalaryRider).where(
                        RiderSalaryRider.site_id == site.id,
                        RiderSalaryRider.settle_cycle_override.is_not(None),
                        RiderSalaryRider.deleted == 0,
                    )
                )
            ).all()
        )
        for rider in riders:
            if not rider.settle_cycle_override:
                continue
            rider_cycle = _cycle_value(rider.settle_cycle_override, site.settle_cycle)
            for start, end in covering_period_ranges(
                rider.settle_cycle_override,
                rider.cycle_config_override,
                year,
                month,
            ):
                planned.append((rider.id, rider_cycle, start, end))
        await assert_period_plan(
            db,
            site_id=site.id,
            planned=[(rider_id, start, end) for rider_id, _cycle, start, end in planned],
        )
        items: list[GetGeneratedPeriodItem] = []
        for rider_id, cycle_type, start, end in planned:
            item = await self._ensure_listed(
                db,
                site_id=site.id,
                rider_id=rider_id,
                cycle_type=cycle_type,
                start_date=start,
                end_date=end,
            )
            items.append(item)
        created_count = sum(1 for item in items if item.created)
        skipped_count = len(items) - created_count
        await audit_service.record(
            db,
            request,
            module='结算周期',
            action='生成周期',
            target_type='period',
            target_id=site.id,
            target_label=f'站点{site.code}/{site.name} {obj.month}',
            before=_existing_generated_periods(items),
            after={'created': created_count, 'skipped': skipped_count},
            description=(
                f'{operator_display_name(request)} 于 {_now_str()} 对 站点{site.name} {obj.month} 执行了生成周期，'
                f'新建{created_count}个，跳过{skipped_count}个'
            ),
        )
        return GeneratePeriodResult(
            site_id=site.id,
            month=obj.month,
            items=items,
            created_count=created_count,
            skipped_count=skipped_count,
        )

    async def create_leave_settlement(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
    ) -> LeaveSettlementResult:
        """
        为已离职骑手生成骑手级结算周期

        周期覆盖离职日所在的站点周期。若这样会部分盖住已有站点级周期，就扩到整段覆盖。
        因此结束日可能晚于离职日；算薪仍只计到离职日。已有覆盖离职日的骑手级周期则直接沿用。
        锁账和标记发薪仍走周期上的 expected_status。

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 骑手 ID
        :return:
        """
        rider = await db.scalar(
            select(RiderSalaryRider).where(RiderSalaryRider.id == pk, RiderSalaryRider.deleted == 0)
        )
        if rider is None:
            raise errors.NotFoundError(msg='骑手不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, rider.site_id)
        if rider.status != RiderStatus.resigned or rider.leave_date is None:
            raise errors.RequestError(msg='请先办理离职，再生成离职结算周期')
        site = await site_dao.get(db, rider.site_id)
        if site is None:
            raise errors.NotFoundError(msg='站点不存在')
        try:
            cycle_start, cycle_end = compute_period_range(site.settle_cycle, site.cycle_config, rider.leave_date)
        except ValueError as exc:
            raise errors.RequestError(msg=str(exc)) from exc
        existing = await _periods_at_site(db, site.id)
        site_spans = [
            (period.start_date, period.end_date) for period in existing if int(period.rider_id) == SITE_LEVEL_RIDER_ID
        ]
        start, end = expand_leave_settlement_span(
            cycle_start=cycle_start,
            cycle_end=cycle_end,
            site_spans=site_spans,
        )
        own = [period for period in existing if int(period.rider_id) == int(rider.id)]
        exact = next((period for period in own if period.start_date == start and period.end_date == end), None)
        if exact is not None:
            return leave_settlement_result(exact, rider.leave_date, created=False)
        covering = next(
            (period for period in own if period.start_date <= rider.leave_date <= period.end_date),
            None,
        )
        if covering is not None:
            return leave_settlement_result(covering, rider.leave_date, created=False)
        cycle_type = _cycle_value(site.settle_cycle, CycleType.month.value)
        await assert_period_plan(db, site_id=site.id, planned=[(rider.id, start, end)])
        existing_period = await settle_period_dao.get_by_unique(
            db, site_id=site.id, rider_id=rider.id, start_date=start
        )
        period = await self._create_if_absent(
            db,
            site_id=site.id,
            rider_id=rider.id,
            cycle_type=cycle_type,
            start_date=start,
            end_date=end,
            plan_checked=True,
            remark=leave_settlement_remark(rider.leave_date),
        )
        created = existing_period is None
        if created:
            await audit_service.record(
                db,
                request,
                module='结算周期',
                action='生成离职结算周期',
                target_type='period',
                target_id=period.id,
                target_label=f'{rider.job_no} {rider.name} {period.start_date}~{period.end_date}',
                before={'exists': False, 'rider_id': rider.id, 'start_date': start.isoformat()},
                after={
                    **snapshot(period, _PERIOD_FIELDS),
                    'leave_date': rider.leave_date.isoformat(),
                },
                description=(
                    f'{operator_display_name(request)} 于 {_now_str()} 为 {rider.job_no} {rider.name} '
                    f'生成离职结算周期 {period.start_date}~{period.end_date}，计薪截至{rider.leave_date}'
                ),
            )
        return leave_settlement_result(period, rider.leave_date, created=created)

    async def _ensure_listed(
        self,
        db: AsyncSession,
        *,
        site_id: int,
        rider_id: int,
        cycle_type: str,
        start_date: date,
        end_date: date,
    ) -> GetGeneratedPeriodItem:
        before = await settle_period_dao.get_by_unique(db, site_id=site_id, rider_id=rider_id, start_date=start_date)
        period = await self._create_if_absent(
            db,
            site_id=site_id,
            rider_id=rider_id,
            cycle_type=cycle_type,
            start_date=start_date,
            end_date=end_date,
            plan_checked=True,
        )
        return GetGeneratedPeriodItem(
            id=period.id,
            site_id=period.site_id,
            rider_id=period.rider_id,
            cycle_type=period.cycle_type,
            start_date=period.start_date,
            end_date=period.end_date,
            status=period.status,
            created=before is None,
        )

    async def calculate(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        obj: CalculatePeriodParam,
    ) -> CalculatePeriodResult:
        """
        触发周期算薪。作业写入 rs_calc_job，按批提交；根事务在提交后后台执行。

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :param obj: 参数
        :return:
        """
        from backend.plugin.rider_salary.service.calc_job_service import enqueue_period_calc

        period, site, _rider = await self._load_visible(db, request, pk)
        if period.status not in {PeriodStatus.open.value, PeriodStatus.reopened.value}:
            raise errors.RequestError(msg=f'结算周期当前状态为{status_label(period.status)}，不允许执行算薪')
        before = snapshot(period, _PERIOD_FIELDS)
        targets = await riders_for_period(db, period, obj.rider_ids)
        outcome = await enqueue_period_calc(db, period=period, rider_ids=obj.rider_ids, operator=request)
        warnings = list(outcome.warnings)
        _append_unique(warnings, await read_period_calc_warnings(period.id))
        where = '已转入后台' if outcome.queued else '已完成'
        await audit_service.record(
            db,
            request,
            module='结算周期',
            action='算薪',
            target_type='period',
            target_id=period.id,
            target_label=_period_label(site, period),
            before=before,
            after={
                **snapshot(period, _PERIOD_FIELDS),
                'job_id': outcome.job_id,
                'queued': outcome.queued,
                'calculated': outcome.calculated,
                'rider_count': len(targets),
            },
            description=(
                f'{operator_display_name(request)} 于 {_now_str()} 对 {_period_label(site, period)} 执行了算薪，'
                f'作业{outcome.job_id}，骑手{len(targets)}人{where}'
            ),
        )
        return CalculatePeriodResult(
            calculated=outcome.calculated,
            warnings=warnings,
            queued=outcome.queued,
            job_id=outcome.job_id,
        )

    async def lock(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        reason: str,
        expected_status: str | None = None,
    ) -> None:
        """
        锁账

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :param reason: 原因
        :param expected_status: 期望的当前状态。不一致，或周期已经锁账时返回 409，不写审计
        :return:
        """
        period, site, _rider = await self._load_visible(db, request, pk)
        if await is_period_calculating(period.id, db):
            raise errors.ConflictError(msg=PERIOD_CALCULATING_LOCK_MSG)
        refreshed = await lock_period_row(db, period.id)
        if refreshed is not None:
            period = refreshed
        if await is_period_calculating(period.id, db):
            raise errors.ConflictError(msg=PERIOD_CALCULATING_LOCK_MSG)
        assert_expected_period_status(period.status, expected_status)
        if period.status == PeriodStatus.locked.value:
            raise errors.ConflictError(msg=PERIOD_STATUS_CHANGED_MSG)
        assert_can_transition(period.status, PeriodStatus.locked.value)
        await self._assert_lock_ready(db, period)
        before = snapshot(period, _PERIOD_FIELDS)
        await self._commit_period_transition(db, period, PeriodStatus.locked.value, request, reason)
        await self.set_locked_flags(db, period, locked=True)
        await db.execute(
            update(RiderSalaryPayroll)
            .where(
                RiderSalaryPayroll.period_id == period.id,
                RiderSalaryPayroll.status == PayrollStatus.draft.value,
                RiderSalaryPayroll.deleted == 0,
            )
            .values(status=PayrollStatus.finalized.value)
        )
        await self._mark_plan_versions_used(db, period.id)
        await db.flush()
        await audit_service.record(
            db,
            request,
            module='结算周期',
            action='锁账',
            target_type='period',
            target_id=period.id,
            target_label=_period_label(site, period),
            reason=reason,
            before=before,
            after=snapshot(period, _PERIOD_FIELDS),
            description=(
                f'{_operator_name(request)} 于 {_now_str()} 对 {_period_label(site, period)} 执行了锁账，原因：{reason}'
            ),
        )

    async def mark_paid(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        reason: str | None,
        expected_status: str | None = None,
    ) -> MarkPaidPeriodResult:
        """
        标记发薪（不涉及实际打款）

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :param reason: 原因
        :param expected_status: 期望的当前状态。不一致，或已经标记发薪时返回 409，不写审计
        :return: 空周期时带「本期没有薪资单」提示
        """
        period, site, _rider = await self._load_visible(db, request, pk)
        refreshed = await lock_period_row(db, period.id)
        if refreshed is not None:
            period = refreshed
        assert_expected_period_status(period.status, expected_status)
        if period.status == PeriodStatus.paid.value:
            raise errors.ConflictError(msg=PERIOD_STATUS_CHANGED_MSG)
        assert_can_transition(period.status, PeriodStatus.paid.value)
        finalized_count = await self._count_finalized_payrolls(db, period.id)
        before = snapshot(period, _PERIOD_FIELDS)
        await self._commit_period_transition(db, period, PeriodStatus.paid.value, request, reason)
        await db.execute(
            update(RiderSalaryPayroll)
            .where(
                RiderSalaryPayroll.period_id == period.id,
                RiderSalaryPayroll.status == PayrollStatus.finalized.value,
                RiderSalaryPayroll.deleted == 0,
            )
            .values(status=PayrollStatus.paid.value)
        )
        await db.flush()
        warning = EMPTY_PERIOD_MARK_PAID_HINT if finalized_count == 0 else None
        desc = (
            f'{_operator_name(request)} 于 {_now_str()} 对 {_period_label(site, period)} 执行了标记发薪，'
            f'已标记发薪，不涉及实际打款'
        )
        if reason and reason.strip():
            desc = f'{desc}，原因：{reason.strip()}'
        if warning:
            desc = f'{desc}。{warning}'
        await audit_service.record(
            db,
            request,
            module='结算周期',
            action='标记发薪',
            target_type='period',
            target_id=period.id,
            target_label=_period_label(site, period),
            reason=reason,
            before=before,
            after=snapshot(period, _PERIOD_FIELDS),
            description=desc,
        )
        return MarkPaidPeriodResult(warning=warning)

    async def lock_check(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
    ) -> GetLockCheckResult:
        """
        锁账预检，只读

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :return:
        """
        period, _site, _rider = await self._load_visible(db, request, pk)
        try:
            assert_can_transition(period.status, PeriodStatus.locked.value)
        except errors.RequestError as exc:
            return GetLockCheckResult(can_lock=False, empty=False, message=exc.msg)
        expected, uncalculated, needs_recalc, missing_supplement, rider_map = await self._lock_readiness(db, period)
        uncalculated_items = _rider_items(uncalculated, rider_map)
        recalc_items = _rider_items(needs_recalc, rider_map)
        missing_items = _rider_items(missing_supplement, rider_map)
        message = lock_block_message(
            uncalculated_job_nos=[item.job_no for item in uncalculated_items],
            recalc_job_nos=[item.job_no for item in recalc_items],
            missing_supplement_job_nos=[item.job_no for item in missing_items],
        )
        message = _merge_lock_message(message, await self._eval_failure_lock_message(db, period))
        return GetLockCheckResult(
            can_lock=message is None,
            empty=len(expected) == 0 and not missing_supplement,
            uncalculated=uncalculated_items,
            needs_recalc=recalc_items,
            missing_supplement=missing_items,
            message=message,
        )

    async def reverse(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        reason: str,
        expected_status: str | None = None,
    ) -> ReversePeriodResult:
        """
        反冲补发：生成反冲单并解除锁账

        期望状态与当前状态不一致时返回 409，不生成反冲单、不写审计。
        周期已经处于补发中时，仍由状态机返回 400，避免改掉「已被反冲」的既有拒绝。

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :param reason: 原因
        :param expected_status: 期望的当前状态
        :return:
        """
        period, site, _rider = await self._load_visible(db, request, pk)
        assert_expected_period_status(period.status, expected_status)
        before = snapshot(period, _PERIOD_FIELDS)
        self.transition(period, PeriodStatus.reopened.value, request, reason)
        payrolls = list(await payroll_dao.select_models(db, period_id=period.id, deleted=0))
        targets = reversible_payrolls(payrolls)
        reversal_net = ZERO
        for payroll in targets:
            reversal = await payroll_service.create_reversal(db, payroll, request, reason)
            reversal_net += q2(reversal.net)
        await self.set_locked_flags(db, period, locked=False)
        await db.flush()
        count = len(targets)
        desc = (
            f'{_operator_name(request)} 于 {_now_str()} 对 {_period_label(site, period)} 执行了反冲补发，'
            f'原因：{reason}；反冲单{count}张，金额合计{reversal_net}'
        )
        await audit_service.record(
            db,
            request,
            module='结算周期',
            action='反冲补发',
            target_type='period',
            target_id=period.id,
            target_label=_period_label(site, period),
            reason=reason,
            before=before,
            after=snapshot(period, _PERIOD_FIELDS),
            description=desc,
        )
        return ReversePeriodResult(reversal_count=count, reversal_net_total=q2(reversal_net))

    async def delete(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
    ) -> None:
        """
        删除开放且无薪资结果的周期

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :return:
        """
        period, site, _rider = await self._load_visible(db, request, pk)
        if period.status != PeriodStatus.open.value:
            raise errors.RequestError(msg='仅开放且没有任何薪资结果的周期可以删除')
        payroll_id = await db.scalar(
            select(RiderSalaryPayroll.id)
            .where(RiderSalaryPayroll.period_id == period.id, RiderSalaryPayroll.deleted == 0)
            .limit(1)
        )
        if payroll_id is not None:
            raise errors.RequestError(msg='仅开放且没有任何薪资结果的周期可以删除')
        before = snapshot(period, _PERIOD_FIELDS)
        await settle_period_dao.delete(db, pk)
        await audit_service.record(
            db,
            request,
            module='结算周期',
            action='删除周期',
            target_type='period',
            target_id=pk,
            target_label=_period_label(site, period),
            before=before,
            after={**before, 'deleted': True},
        )

    async def _draft_payrolls(self, db: AsyncSession, period_id: int) -> list[RiderSalaryPayroll]:
        rows = await db.scalars(
            select(RiderSalaryPayroll).where(
                RiderSalaryPayroll.period_id == period_id,
                RiderSalaryPayroll.status == PayrollStatus.draft.value,
                RiderSalaryPayroll.deleted == 0,
            )
        )
        return list(rows.all())

    async def _count_finalized_payrolls(self, db: AsyncSession, period_id: int) -> int:
        count = await db.scalar(
            select(func.count(RiderSalaryPayroll.id)).where(
                RiderSalaryPayroll.period_id == period_id,
                RiderSalaryPayroll.status == PayrollStatus.finalized.value,
                RiderSalaryPayroll.deleted == 0,
            )
        )
        return int(count or 0)

    async def carry_forward(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        rider_ids: list[int] | None,
        reason: str | None,
    ) -> CarryForwardResult:
        """
        沿用原单：为已反冲且没有新鲜补发草稿的骑手生成金额相同的补发草稿，并写审计

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :param rider_ids: 指定骑手，空表示全部缺补发单的骑手
        :param reason: 原因
        :return:
        """
        period, site, _rider = await self._load_visible(db, request, pk)
        if period.status != PeriodStatus.reopened.value:
            raise errors.RequestError(msg=f'结算周期当前状态为{status_label(period.status)}，不允许沿用原单')
        reason_text = (reason or '').strip() or CARRY_FORWARD_REASON
        payrolls = await self._period_payrolls(db, period.id)
        drafts = await self._draft_payrolls(db, period.id)
        missing = missing_supplement_rider_ids(payrolls, drafts)
        selected = list(missing)
        if rider_ids:
            missing_set = set(missing)
            unknown = [rider_id for rider_id in rider_ids if rider_id not in missing_set]
            if unknown:
                unknown_map = await self._rider_map(db, unknown)
                job_nos = '、'.join(_job_no_list(unknown, unknown_map))
                raise errors.RequestError(msg=f'以下骑手无需沿用原单：工号 {job_nos}')
            chosen = set(rider_ids)
            selected = [rider_id for rider_id in missing if rider_id in chosen]
        if not selected:
            raise errors.RequestError(msg='没有需要沿用原单的骑手')
        originals = latest_reversed_originals(payrolls)
        rider_map = await self._rider_map(db, selected)
        created_ids: list[int] = []
        net_total = ZERO
        for rider_id in selected:
            original = originals[rider_id]
            supplement = await self._write_carry_forward_supplement(
                db,
                period=period,
                original=original,
                drafts=drafts,
                request=request,
            )
            created_ids.append(rider_id)
            net_total += q2(supplement.net)
            rider = rider_map.get(rider_id)
            job_no = rider.job_no if rider is not None and getattr(rider, 'job_no', None) else str(rider_id)
            await audit_service.record(
                db,
                request,
                module='结算周期',
                action='沿用原单',
                target_type='payroll',
                target_id=supplement.id,
                target_label=f'{_period_label(site, period)} 骑手{job_no}',
                reason=reason_text,
                before={
                    'source_payroll_id': original.id,
                    'gross': str(q2(original.gross)),
                    'net': str(q2(original.net)),
                    'advance_deduction': str(q2(original.advance_deduction)),
                },
                after={
                    'payroll_id': supplement.id,
                    'kind': PayrollKind.supplement.value,
                    'gross': str(q2(supplement.gross)),
                    'net': str(q2(supplement.net)),
                    'advance_deduction': str(q2(supplement.advance_deduction)),
                },
                description=(
                    f'{_operator_name(request)} 于 {_now_str()} 对骑手{job_no}沿用原单，'
                    f'{_carry_forward_net_clause(original, supplement)}'
                ),
            )
        return CarryForwardResult(created_count=len(created_ids), rider_ids=created_ids, net_total=q2(net_total))

    async def _lock_readiness(
        self,
        db: AsyncSession,
        period: RiderSalarySettlePeriod,
    ) -> tuple[list[int], list[int], list[int], list[int], dict[int, RiderSalaryRider]]:
        expected = list(await riders_for_period(db, period, None))
        drafts = await self._draft_payrolls(db, period.id)
        uncalculated, needs_recalc = classify_lock_gaps(
            expected,
            drafts,
            kind=current_payroll_kind(period.status),
        )
        missing_supplement: list[int] = []
        if period.status == PeriodStatus.reopened.value:
            payrolls = await self._period_payrolls(db, period.id)
            missing_supplement = missing_supplement_rider_ids(payrolls, drafts)
            missing_set = set(missing_supplement)
            uncalculated = [rider_id for rider_id in uncalculated if rider_id not in missing_set]
        rider_map = await self._rider_map(db, [*uncalculated, *needs_recalc, *missing_supplement])
        return expected, uncalculated, needs_recalc, missing_supplement, rider_map

    async def _eval_failure_lock_message(self, db: AsyncSession, period: RiderSalarySettlePeriod) -> str | None:
        """草稿或周期告警里有公式求值失败时，返回锁账拒绝文案。"""
        drafts = await self._draft_payrolls(db, period.id)
        rider_map = await self._rider_map(db, [int(row.rider_id) for row in drafts])
        redis_warnings = await read_period_calc_warnings(period.id)
        return eval_failure_lock_message(collect_eval_failure_labels(drafts, rider_map, redis_warnings))

    async def _assert_lock_ready(self, db: AsyncSession, period: RiderSalarySettlePeriod) -> None:
        _expected, uncalculated, needs_recalc, missing_supplement, rider_map = await self._lock_readiness(db, period)
        message = lock_block_message(
            uncalculated_job_nos=_job_no_list(uncalculated, rider_map),
            recalc_job_nos=_job_no_list(needs_recalc, rider_map),
            missing_supplement_job_nos=_job_no_list(missing_supplement, rider_map),
        )
        message = _merge_lock_message(message, await self._eval_failure_lock_message(db, period))
        if message:
            raise errors.RequestError(msg=message)

    async def _period_payrolls(self, db: AsyncSession, period_id: int) -> list[RiderSalaryPayroll]:
        rows = await db.scalars(
            select(RiderSalaryPayroll).where(
                RiderSalaryPayroll.period_id == period_id,
                RiderSalaryPayroll.deleted == 0,
            )
        )
        return list(rows.all())

    async def _write_carry_forward_supplement(
        self,
        db: AsyncSession,
        *,
        period: RiderSalarySettlePeriod,
        original: Any,
        drafts: list[Any],
        request: Request,
    ) -> Any:
        """生成或覆盖补发草稿，金额与原单相同，并按原单预支明细再次抵扣"""
        rider_id = int(original.rider_id)
        payroll = supplement_draft_for(drafts, rider_id)
        if payroll is None:
            payroll = RiderSalaryPayroll(
                period_id=period.id,
                rider_id=rider_id,
                kind=PayrollKind.supplement.value,
            )
            db.add(payroll)
            await db.flush()
        elif getattr(payroll, 'id', None):
            await payroll_detail_dao.logical_delete_by_payroll(db, int(payroll.id))
        apply_supplement_from_original(payroll, original)
        payroll.calc_time = timezone.now()
        payroll.calc_by = _operator_id(request) or None
        details = await payroll_detail_dao.list_by_payroll(db, int(original.id))
        copied: list[RiderSalaryPayrollDetail] = []
        for detail in details:
            trace = getattr(detail, 'calc_trace', None)
            row = RiderSalaryPayrollDetail(
                payroll_id=int(payroll.id),
                rider_id=rider_id,
                subject_id=int(detail.subject_id),
                amount=q2(detail.amount),
                stage=detail.stage,
                include_in_gross=bool(getattr(detail, 'include_in_gross', True)),
                source=detail.source,
                biz_date=getattr(detail, 'biz_date', None),
                plan_version_id=getattr(detail, 'plan_version_id', None),
                plan_item_id=getattr(detail, 'plan_item_id', None),
                order_id=getattr(detail, 'order_id', None),
                calc_trace=dict(trace) if trace else None,
            )
            db.add(row)
            copied.append(row)
        shortfalls = await self._reapply_copied_advances(db, payroll, copied)
        if shortfalls:
            payroll.warnings = [*(payroll.warnings or []), *shortfalls]
        await db.flush()
        return payroll

    async def _reapply_copied_advances(self, db: AsyncSession, payroll: Any, details: list[Any]) -> list[str]:
        """按复制过来的预支明细再次抵扣。余额不足时明细改成实际抵扣额，并回写表头。"""
        warnings: list[str] = []
        short = False
        for detail in details:
            if getattr(detail, 'source', None) != DetailSource.advance.value:
                continue
            advance_id = (getattr(detail, 'calc_trace', None) or {}).get('advance_id')
            if not advance_id:
                warnings.append('沿用原单时有预支明细缺少预支单编号，未再次抵扣')
                continue
            advance = await db.scalar(
                select(RiderSalaryAdvance)
                .where(
                    RiderSalaryAdvance.id == int(advance_id),
                    RiderSalaryAdvance.deleted == 0,
                )
                .with_for_update()
            )
            need = q2(abs(q2(detail.amount)))
            if advance is None:
                warnings.append(f'预支单{advance_id}不存在，沿用原单未再次抵扣')
                continue
            applied = reapply_advance_amount(advance, detail.amount)
            if applied < need:
                detail.amount = q2(-applied)
                short = True
                warnings.append(f'预支单{advance_id}余额不足，沿用原单只再次抵扣了{applied}')
        if short:
            align_carried_advance(payroll, details)
        return warnings

    async def load_visible(
        self,
        db: AsyncSession,
        request: Request,
        pk: int,
    ) -> tuple[RiderSalarySettlePeriod, RiderSalarySite | None, RiderSalaryRider | None]:
        return await self._load_visible(db, request, pk)

    @staticmethod
    async def rider_map(db: AsyncSession, rider_ids: list[int]) -> dict[int, RiderSalaryRider]:
        return await PeriodService._rider_map(db, rider_ids)

    async def set_locked_flags(self, db: AsyncSession, period: RiderSalarySettlePeriod, *, locked: bool) -> None:
        order_stmt = (
            update(RiderSalaryOrder)
            .where(
                RiderSalaryOrder.site_id == period.site_id,
                RiderSalaryOrder.biz_date >= period.start_date,
                RiderSalaryOrder.biz_date <= period.end_date,
                RiderSalaryOrder.deleted == 0,
            )
            .values(is_locked=locked)
        )
        adj_stmt = (
            update(RiderSalaryAdjustment)
            .where(
                RiderSalaryAdjustment.site_id == period.site_id,
                RiderSalaryAdjustment.biz_date >= period.start_date,
                RiderSalaryAdjustment.biz_date <= period.end_date,
                RiderSalaryAdjustment.deleted == 0,
            )
            .values(is_locked=locked)
        )
        if period.rider_id and period.rider_id != SITE_LEVEL_RIDER_ID:
            order_stmt = order_stmt.where(RiderSalaryOrder.rider_id == period.rider_id)
            adj_stmt = adj_stmt.where(RiderSalaryAdjustment.rider_id == period.rider_id)
        else:
            overlapping = list(
                (
                    await db.scalars(
                        select(RiderSalarySettlePeriod).where(
                            RiderSalarySettlePeriod.site_id == period.site_id,
                            RiderSalarySettlePeriod.rider_id != SITE_LEVEL_RIDER_ID,
                            RiderSalarySettlePeriod.start_date <= period.end_date,
                            RiderSalarySettlePeriod.end_date >= period.start_date,
                            RiderSalarySettlePeriod.deleted == 0,
                        )
                    )
                ).all()
            )
            excluded = site_level_lock_excluded_rider_ids(overlapping)
            if excluded:
                order_stmt = order_stmt.where(RiderSalaryOrder.rider_id.notin_(list(excluded)))
                adj_stmt = adj_stmt.where(RiderSalaryAdjustment.rider_id.notin_(list(excluded)))
        await db.execute(order_stmt)
        await db.execute(adj_stmt)

    async def _mark_plan_versions_used(self, db: AsyncSession, period_id: int) -> None:
        payrolls = await payroll_dao.select_models(db, period_id=period_id, deleted=0)
        version_ids: set[int] = set()
        for payroll in payrolls:
            version_ids.update(int(version_id) for version_id in payroll.plan_version_ids or [])
        if not version_ids:
            return
        await db.execute(
            update(RiderSalaryPlanVersion)
            .where(
                RiderSalaryPlanVersion.id.in_(list(version_ids)),
                RiderSalaryPlanVersion.deleted == 0,
            )
            .values(is_used=True)
        )

    async def _load_visible(
        self,
        db: AsyncSession,
        request: Request,
        pk: int,
    ) -> tuple[RiderSalarySettlePeriod, RiderSalarySite | None, RiderSalaryRider | None]:
        period = await settle_period_dao.get(db, pk)
        if period is None:
            raise errors.NotFoundError(msg='结算周期不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, period.site_id)
        site = await site_dao.get(db, period.site_id)
        rider = None
        if period.rider_id and period.rider_id != SITE_LEVEL_RIDER_ID:
            rider = await db.scalar(
                select(RiderSalaryRider).where(RiderSalaryRider.id == period.rider_id, RiderSalaryRider.deleted == 0)
            )
        return period, site, rider

    @staticmethod
    def _to_detail(
        period: RiderSalarySettlePeriod,
        site: RiderSalarySite | None,
        rider: RiderSalaryRider | None,
    ) -> GetPeriodDetail:
        data = GetPeriodDetail.model_validate(period)
        if site is not None:
            data.site_name = site.name
            data.site_code = site.code
        if rider is not None:
            data.rider_job_no = rider.job_no
            data.rider_name = rider.name
        return data

    @staticmethod
    def _empty_stats() -> dict[str, Any]:
        return {
            'rider_count': 0,
            'payroll_count': 0,
            'stale_count': 0,
            'gross_total': ZERO,
            'net_total': ZERO,
            'kind_counts': empty_kind_counts(),
        }

    async def _payroll_stats(self, db: AsyncSession, period_ids: list[int]) -> dict[int, dict[str, Any]]:
        if not period_ids:
            return {}
        payrolls = list(
            (
                await db.scalars(
                    select(RiderSalaryPayroll).where(
                        RiderSalaryPayroll.period_id.in_(period_ids),
                        RiderSalaryPayroll.deleted == 0,
                    )
                )
            ).all()
        )
        stats = summarize_period_stats(payrolls)
        for item in stats.values():
            counts = empty_kind_counts()
            counts.update(item['kind_counts'])
            item['kind_counts'] = counts
        return stats

    async def _period_names(self, db: AsyncSession, items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        site_ids = {int(item['site_id']) for item in items}
        rider_ids = {int(item['rider_id']) for item in items if int(item.get('rider_id') or 0)}
        sites: dict[int, RiderSalarySite] = {}
        if site_ids:
            rows = await db.scalars(select(RiderSalarySite).where(RiderSalarySite.id.in_(list(site_ids))))
            sites = {row.id: row for row in rows.all()}
        riders = await self._rider_map(db, list(rider_ids))
        names: dict[int, dict[str, Any]] = {}
        for item in items:
            site = sites.get(int(item['site_id']))
            rider = riders.get(int(item.get('rider_id') or 0))
            names[int(item['id'])] = {
                'site_name': site.name if site is not None else None,
                'site_code': site.code if site is not None else None,
                'rider_job_no': rider.job_no if rider is not None else None,
                'rider_name': rider.name if rider is not None else None,
            }
        return names

    @staticmethod
    async def _rider_map(db: AsyncSession, rider_ids: list[int]) -> dict[int, RiderSalaryRider]:
        ids = [rid for rid in {int(item) for item in rider_ids} if rid]
        if not ids:
            return {}
        rows = await db.scalars(select(RiderSalaryRider).where(RiderSalaryRider.id.in_(ids)))
        return {row.id: row for row in rows.all()}


period_service = PeriodService()
