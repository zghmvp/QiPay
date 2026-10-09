from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from re import fullmatch
from typing import Any

from fastapi import Request
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.admin.crud.crud_user import user_dao
from backend.app.admin.model import User
from backend.app.admin.schema.user import AddUserParam
from backend.app.admin.service.user_service import user_service as sys_user_service
from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.core.conf import settings
from backend.database.redis import redis_client
from backend.plugin.rider_salary.crud.plan import plan_dao
from backend.plugin.rider_salary.crud.rider import rider_dao
from backend.plugin.rider_salary.crud.rider_employ_history import rider_employ_history_dao
from backend.plugin.rider_salary.crud.rider_plan_binding import rider_plan_binding_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.enums import BindingType, PayrollStatus, PeriodStatus, RiderStatus
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.rider_employ_history import RiderSalaryRiderEmployHistory
from backend.plugin.rider_salary.model.rider_plan_binding import RiderSalaryRiderPlanBinding
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.schema.rider import (
    BatchBindingItem,
    BatchBindingResult,
    BatchIssuedPasswordItem,
    BatchIssuedPasswordResult,
    BatchOpenAccountParam,
    BatchPlanBindingParam,
    BatchResetPasswordParam,
    CreateEmployHistoryParam,
    CreatePlanBindingParam,
    CreateRiderParam,
    DisableRiderAccountParam,
    EnableRiderAccountParam,
    GetEffectivePlanSegment,
    IssuedRiderPassword,
    OpenRiderAccountParam,
    ResetRiderPasswordParam,
    RiderLeaveParam,
    RiderLeaveResult,
    UpdateEmployHistoryParam,
    UpdatePlanBindingParam,
    UpdateRiderParam,
)
from backend.plugin.rider_salary.service.advance_service import advance_service
from backend.plugin.rider_salary.service.audit_service import audit_service, snapshot
from backend.plugin.rider_salary.utils.db_errors import RIDER_USER_BOUND_MSG, client_error_from_integrity
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.initial_password import generate_initial_password
from backend.plugin.rider_salary.utils.lifecycle import (
    assert_binding_target,
    assert_rider_can_enable_account,
    assert_rider_can_open_account,
    assert_site_accepts_rider,
)
from backend.plugin.rider_salary.utils.lock_check import assert_not_locked
from backend.plugin.rider_salary.utils.recalc import mark_stale
from backend.plugin.rider_salary.utils.scope import find_rider_role
from backend.utils.timezone import timezone

_OPEN_END = date(9999, 12, 31)
_MOBILE = r'^1[3-9]\d{9}$'
_LOCKED_PERIOD_STATUSES = {PeriodStatus.locked.value, PeriodStatus.paid.value}
_RIDER_FIELDS = (
    'id',
    'job_no',
    'name',
    'phone',
    'site_id',
    'employ_type',
    'hire_date',
    'leave_date',
    'status',
    'advance_limit',
    'settle_cycle_override',
    'cycle_config_override',
    'user_id',
    'remark',
)
_HISTORY_FIELDS = ('id', 'rider_id', 'employ_type', 'start_date', 'end_date', 'remark')
_BINDING_FIELDS = ('id', 'rider_id', 'plan_version_id', 'binding_type', 'start_date', 'end_date', 'remark')


@dataclass(frozen=True)
class Segment:
    """按日解析后的连续生效方案区间"""

    plan_version_id: int | None
    start: date
    end: date


@dataclass(frozen=True)
class BindingView:
    """绑定区间视图，供重叠校验与生效解析使用"""

    binding_type: str
    start_date: date
    end_date: date | None
    plan_version_id: int
    id: int | None = None


def _as_end(value: date | None) -> date:
    return value if value is not None else _OPEN_END


def ranges_overlap(a_start: date, a_end: date | None, b_start: date, b_end: date | None) -> bool:
    """
    判断两个闭区间是否重叠（空结束日期视为至今）

    :param a_start: 区间 A 开始
    :param a_end: 区间 A 结束
    :param b_start: 区间 B 开始
    :param b_end: 区间 B 结束
    :return:
    """
    return a_start <= _as_end(b_end) and b_start <= _as_end(a_end)


def check_range_order(start_date: date, end_date: date | None) -> None:
    """
    校验结束日期不早于开始日期

    :param start_date: 开始日期
    :param end_date: 结束日期
    :return:
    """
    if end_date is not None and end_date < start_date:
        raise errors.RequestError(msg='结束日期不能早于开始日期')


def check_binding_overlap(
    existing: Sequence[BindingView],
    binding_type: str,
    start_date: date,
    end_date: date | None,
    *,
    exclude_id: int | None = None,
) -> None:
    """
    校验同类型绑定区间不重叠

    :param existing: 已有绑定
    :param binding_type: 绑定类型
    :param start_date: 开始日期
    :param end_date: 结束日期
    :param exclude_id: 更新时排除自身
    :return:
    """
    for item in existing:
        if item.binding_type != binding_type:
            continue
        if exclude_id is not None and item.id == exclude_id:
            continue
        if ranges_overlap(start_date, end_date, item.start_date, item.end_date):
            try:
                label = BindingType(binding_type).label
            except ValueError:
                label = binding_type
            raise errors.RequestError(msg=f'{label}绑定区间重叠')


def check_employ_overlap(
    existing: Sequence[RiderSalaryRiderEmployHistory],
    start_date: date,
    end_date: date | None,
    *,
    exclude_id: int | None = None,
) -> None:
    """
    校验用工类型历史区间不重叠

    :param existing: 已有历史
    :param start_date: 开始日期
    :param end_date: 结束日期
    :param exclude_id: 更新时排除自身
    :return:
    """
    for item in existing:
        if exclude_id is not None and item.id == exclude_id:
            continue
        if ranges_overlap(start_date, end_date, item.start_date, item.end_date):
            raise errors.RequestError(msg='用工类型历史区间重叠')


_RANGE_LOCKED_MSG = '该日期所属结算周期已锁账，禁止修改，请走反冲补发流程'


def union_ranges(ranges: Sequence[tuple[date, date | None]]) -> tuple[date, date | None] | None:
    """
    求若干闭区间的并集；任一端开放则并集开放

    :param ranges: 闭区间列表，结束日期为空表示长期
    :return:
    """
    if not ranges:
        return None
    start = min(item[0] for item in ranges)
    concrete = [item[1] for item in ranges if item[1] is not None]
    if len(concrete) != len(ranges):
        return start, None
    return start, max(concrete)


def _subtract_range(
    a_start: date,
    a_end: date | None,
    b_start: date,
    b_end: date | None,
) -> list[tuple[date, date | None]]:
    """A 去掉与 B 重叠的部分，剩下的仍是闭区间"""
    if not ranges_overlap(a_start, a_end, b_start, b_end):
        return [(a_start, a_end)]
    pieces: list[tuple[date, date | None]] = []
    if a_start < b_start:
        left_end = b_start - timedelta(days=1)
        if a_end is None or left_end <= a_end:
            pieces.append((a_start, left_end))
    if b_end is not None:
        right_start = b_end + timedelta(days=1)
        if a_end is None or right_start <= a_end:
            pieces.append((right_start, a_end))
    return pieces


def changed_coverage_spans(
    old_start: date,
    old_end: date | None,
    new_start: date,
    new_end: date | None,
    *,
    type_changed: bool,
) -> list[tuple[date, date | None]]:
    """
    一段用工历史从旧区间改到新区间后，用工事实发生变化的日期

    用工类型变化时，新旧并集上都变了；只改边界时取对称差，未改动的前缀不算。

    :param old_start: 旧开始
    :param old_end: 旧结束
    :param new_start: 新开始
    :param new_end: 新结束
    :param type_changed: 用工类型是否变化
    :return:
    """
    if type_changed:
        merged = union_ranges([(old_start, old_end), (new_start, new_end)])
        return [] if merged is None else [merged]
    removed = _subtract_range(old_start, old_end, new_start, new_end)
    added = _subtract_range(new_start, new_end, old_start, old_end)
    return [*removed, *added]


def stale_bounds(
    spans: Sequence[tuple[date, date | None]],
    *,
    today: date,
) -> tuple[date, date] | None:
    """
    把变化区间收成重算标记的闭区间

    开放端截止到今天、起点和具体结束日中的较晚者，不用 9999-12-31，
    避免把该日之后才开始的开放周期全部标成需重算。

    :param spans: 事实发生变化的区间
    :param today: 今天
    :return:
    """
    if not spans:
        return None
    start = min(item[0] for item in spans)
    concrete = [item[1] for item in spans if item[1] is not None]
    if len(concrete) != len(spans):
        end = max([today, start, *concrete])
    elif concrete:
        end = max(concrete)
    else:
        end = start
    if end < start:
        end = start
    return start, end


def _segments_to_close(existing: Sequence[Any], start_date: date) -> list[tuple[Any, date]]:
    """找出会被新段自动收尾的开放用工历史，以及收尾日"""
    closings: list[tuple[Any, date]] = []
    for item in existing:
        if item.end_date is not None or item.start_date >= start_date:
            continue
        close_end = start_date - timedelta(days=1)
        if close_end < item.start_date:
            continue
        closings.append((item, close_end))
    return closings


def employ_create_ranges(
    existing: Sequence[Any],
    start_date: date,
    end_date: date | None,
) -> tuple[list[tuple[Any, date]], list[tuple[date, date | None]]]:
    """
    新增用工历史时的自动收尾，以及生效用工类型发生变化的日期

    新段整段算变化。被收尾的上一段只算收尾日之后，未改类型的前缀不算。

    :param existing: 已有用工历史
    :param start_date: 新段开始
    :param end_date: 新段结束
    :return:
    """
    closings = _segments_to_close(existing, start_date)
    changed: list[tuple[date, date | None]] = [(start_date, end_date)]
    for item, close_end in closings:
        changed.extend(
            changed_coverage_spans(
                item.start_date,
                item.end_date,
                item.start_date,
                close_end,
                type_changed=False,
            )
        )
    return closings, changed


def leave_employ_touch(
    histories: Sequence[Any],
    leave_date: date,
) -> list[tuple[date, date | None]]:
    """
    离职收尾后生效用工类型发生变化的日期

    开放段收到离职日时，变化的是离职日之后；离职日当天仍沿用原类型。

    :param histories: 用工历史
    :param leave_date: 离职日期
    :return:
    """
    changed: list[tuple[date, date | None]] = []
    for item in histories:
        if item.end_date is not None:
            continue
        if leave_date >= item.start_date:
            changed.extend(
                changed_coverage_spans(
                    item.start_date,
                    None,
                    item.start_date,
                    leave_date,
                    type_changed=False,
                )
            )
        else:
            changed.append((item.start_date, None))
    return changed


def assert_leave_not_before_employment(
    hire_date: date,
    histories: Sequence[Any],
    leave_date: date,
) -> None:
    """
    离职日不能早于入职日，也不能早于最近一段用工历史的起点

    :param hire_date: 入职日期
    :param histories: 用工历史
    :param leave_date: 离职日期
    :return:
    """
    if leave_date < hire_date:
        raise errors.RequestError(msg='离职日期不能早于入职日期')
    if not histories:
        return
    last_start = max(item.start_date for item in histories)
    if leave_date < last_start:
        raise errors.RequestError(msg='离职日期不能早于最近一段用工历史的开始日期')


def open_bindings_ending_on_leave(bindings: Sequence[Any], leave_date: date) -> list[Any]:
    """
    仍开放的方案绑定收到离职日

    起点晚于离职日时无法收成合法区间，拒绝离职。

    :param bindings: 方案绑定
    :param leave_date: 离职日期
    :return:
    """
    closing: list[Any] = []
    for item in bindings:
        if item.end_date is not None:
            continue
        if item.start_date > leave_date:
            raise errors.RequestError(msg='存在离职日之后才开始的方案绑定，请先调整绑定后再离职')
        closing.append(item)
    return closing


def binding_close_spans(bindings: Sequence[Any], leave_date: date) -> list[tuple[date, date | None]]:
    """
    开放绑定收到离职日后，方案覆盖发生变化的日期

    离职日当天仍沿用原绑定，变化从次日开始。

    :param bindings: 即将截止的开放绑定
    :param leave_date: 离职日期
    :return:
    """
    changed: list[tuple[date, date | None]] = []
    for item in bindings:
        changed.extend(
            changed_coverage_spans(
                item.start_date,
                None,
                item.start_date,
                leave_date,
                type_changed=False,
            )
        )
    return changed


def leave_lock_ranges(
    employ_changed: Sequence[tuple[date, date | None]],
    binding_changed: Sequence[tuple[date, date | None]],
    leave_date: date,
) -> list[tuple[date, date | None]]:
    """
    离职锁账校验区间

    用工类型和方案绑定的变化从离职日次日开始，另外加上离职日当天。
    否则离职日恰好是已锁账周期最后一天时会被放行。Q-11 按推荐方案拒绝并走反冲。

    :param employ_changed: 用工历史变化区间
    :param binding_changed: 方案绑定变化区间
    :param leave_date: 离职日期
    :return:
    """
    return [*employ_changed, *binding_changed, (leave_date, leave_date)]


def _changed_span_filters(ranges: Sequence[tuple[date, date | None]]) -> list[Any]:
    """每个变化区间单独做成重叠条件，间隙不会被并进去"""
    filters: list[Any] = []
    for start_date, end_date in ranges:
        if end_date is not None and end_date < start_date:
            continue
        filters.append(
            and_(
                RiderSalarySettlePeriod.end_date >= start_date,
                RiderSalarySettlePeriod.start_date <= _as_end(end_date),
            )
        )
    return filters


async def assert_range_unlocked(
    db: AsyncSession,
    *,
    site_id: int,
    rider_id: int,
    ranges: Sequence[tuple[date, date | None]],
) -> None:
    """
    校验这些变化区间都不落在已锁账或已发薪周期

    只检查调用方给出的变化日期，各区间分别重叠，不把区间之间的间隙算进去。
    结束日期为空时覆盖该起点之后的全部日期。骑手级与站点级周期都计入。
    用工历史和后续方案绑定修改都复用本函数。

    :param db: 数据库会话
    :param site_id: 站点 ID
    :param rider_id: 骑手 ID
    :param ranges: 生效用工类型或绑定事实发生变化的闭区间
    :return:
    """
    filters = _changed_span_filters(ranges)
    if not filters:
        return
    locked = await db.scalar(
        select(RiderSalarySettlePeriod.id)
        .where(
            RiderSalarySettlePeriod.site_id == site_id,
            RiderSalarySettlePeriod.rider_id.in_([rider_id, 0]),
            RiderSalarySettlePeriod.status.in_(list(_LOCKED_PERIOD_STATUSES)),
            RiderSalarySettlePeriod.deleted == 0,
            or_(*filters),
        )
        .limit(1)
    )
    if locked is not None:
        raise errors.ForbiddenError(msg=_RANGE_LOCKED_MSG)


async def _mark_employ_stale(
    db: AsyncSession,
    *,
    rider_id: int,
    spans: Sequence[tuple[date, date | None]],
) -> None:
    """按每段变化日期标记重算，开放端不用 9999-12-31，也不把间隙标脏"""
    today = timezone.now().date()
    for span in spans:
        window = stale_bounds([span], today=today)
        if window is None:
            continue
        await mark_stale(db, rider_ids=[rider_id], date_from=window[0], date_to=window[1])


async def _mark_sites_open_stale(
    db: AsyncSession,
    *,
    rider_id: int,
    site_ids: Sequence[int],
) -> None:
    """把骑手在这些站点开放或补发中周期上的草稿标成需重算"""
    ids = sorted({int(site_id) for site_id in site_ids})
    if not ids:
        return
    periods = select(RiderSalarySettlePeriod.id).where(
        RiderSalarySettlePeriod.site_id.in_(ids),
        RiderSalarySettlePeriod.status.in_([PeriodStatus.open, PeriodStatus.reopened]),
        RiderSalarySettlePeriod.deleted == 0,
        RiderSalarySettlePeriod.rider_id.in_([rider_id, 0]),
    )
    await db.execute(
        update(RiderSalaryPayroll)
        .where(
            RiderSalaryPayroll.rider_id == rider_id,
            RiderSalaryPayroll.status == PayrollStatus.draft,
            RiderSalaryPayroll.deleted == 0,
            RiderSalaryPayroll.period_id.in_(periods),
        )
        .values(stale=True)
    )


async def _assert_transfer_allowed(
    db: AsyncSession,
    request: Request,
    rider: Any,
    new_site_id: int,
    reason: str | None,
) -> None:
    """换站前校验原因、站点可见，以及换站日不落在已锁账周期"""
    if not (reason and reason.strip()):
        raise errors.RequestError(msg='请填写操作原因')
    visible = await get_visible_site_ids(request, db)
    assert_site_visible(visible, new_site_id)
    site = await site_dao.get(db, new_site_id)
    if not site:
        raise errors.NotFoundError(msg='站点不存在')
    assert_site_accepts_rider(site)
    # Q-11：换站日取操作当天，落在新旧站点任一已锁账周期则拒绝
    today = timezone.now().date()
    transfer_day = [(today, today)]
    await assert_range_unlocked(db, site_id=rider.site_id, rider_id=rider.id, ranges=transfer_day)
    await assert_range_unlocked(db, site_id=new_site_id, rider_id=rider.id, ranges=transfer_day)


async def _locked_hire_change(
    db: AsyncSession,
    rider: Any,
    new_hire: date | None,
    *,
    extra_site_id: int | None,
) -> list[tuple[date, date | None]]:
    """入职日变化的日期；落在已锁账周期则拒绝"""
    if new_hire is None or new_hire == rider.hire_date:
        return []
    if rider.leave_date is not None and new_hire > rider.leave_date:
        raise errors.RequestError(msg='入职日期不能晚于离职日期')
    spans = changed_coverage_spans(
        rider.hire_date,
        rider.leave_date,
        new_hire,
        rider.leave_date,
        type_changed=False,
    )
    site_ids = [rider.site_id]
    if extra_site_id is not None and extra_site_id != rider.site_id:
        site_ids.append(extra_site_id)
    for site_id in site_ids:
        await assert_range_unlocked(db, site_id=site_id, rider_id=rider.id, ranges=spans)
    return spans


def resolve_effective_plans_from_bindings(
    bindings: Sequence[BindingView],
    start: date,
    end: date,
) -> list[Segment]:
    """
    按日解析生效方案并合并连续区间（无方案区间亦返回）

    某日优先取覆盖该日的 override，否则取 default，都无则为 None

    :param bindings: 绑定列表
    :param start: 开始日期
    :param end: 结束日期
    :return:
    """
    if end < start:
        return []
    days: list[tuple[date, int | None]] = []
    current = start
    while current <= end:
        override_id: int | None = None
        default_id: int | None = None
        for item in bindings:
            if not (item.start_date <= current <= _as_end(item.end_date)):
                continue
            if item.binding_type == BindingType.override:
                override_id = item.plan_version_id
            elif item.binding_type == BindingType.default:
                default_id = item.plan_version_id
        days.append((current, override_id if override_id is not None else default_id))
        current += timedelta(days=1)

    segments: list[Segment] = []
    for day, plan_version_id in days:
        if segments and segments[-1].plan_version_id == plan_version_id and segments[-1].end + timedelta(days=1) == day:
            last = segments[-1]
            segments[-1] = Segment(plan_version_id=last.plan_version_id, start=last.start, end=day)
        else:
            segments.append(Segment(plan_version_id=plan_version_id, start=day, end=day))
    return segments


async def resolve_effective_plans(
    db: AsyncSession,
    rider_id: int,
    start: date,
    end: date,
) -> list[Segment]:
    """
    解析骑手在日期范围内的逐日生效方案（合并连续区间）

    :param db: 数据库会话
    :param rider_id: 骑手 ID
    :param start: 开始日期
    :param end: 结束日期
    :return:
    """
    rows = await rider_plan_binding_dao.get_by_rider(db, rider_id)
    views = [
        BindingView(
            binding_type=row.binding_type,
            start_date=row.start_date,
            end_date=row.end_date,
            plan_version_id=row.plan_version_id,
            id=row.id,
        )
        for row in rows
    ]
    return resolve_effective_plans_from_bindings(views, start, end)


def _binding_views(rows: Sequence[RiderSalaryRiderPlanBinding]) -> list[BindingView]:
    return [
        BindingView(
            binding_type=row.binding_type,
            start_date=row.start_date,
            end_date=row.end_date,
            plan_version_id=row.plan_version_id,
            id=row.id,
        )
        for row in rows
    ]


def _issue_password(raw: str | None) -> tuple[str, str | None]:
    """未传密码时生成随机口令。明文只在生成时返回，指定密码不回显。"""
    supplied = (raw or '').strip()
    if supplied:
        return supplied, None
    generated = generate_initial_password()
    return generated, generated


def _user_phone(phone: str | None) -> str | None:
    if phone and fullmatch(_MOBILE, phone):
        return phone
    return None


async def _reject_if_user_bound(db: AsyncSession, user_id: int, rider_id: int) -> None:
    """同一登录账号不能同时绑到两名未删除骑手。

    :param db: 数据库会话
    :param user_id: 登录账号 ID
    :param rider_id: 当前骑手 ID
    """
    bound_id = await db.scalar(
        select(rider_dao.model.id).where(
            rider_dao.model.user_id == user_id,
            rider_dao.model.deleted == 0,
            rider_dao.model.id != rider_id,
        )
    )
    if bound_id is not None:
        raise errors.ConflictError(msg=RIDER_USER_BOUND_MSG)


def _unique_ids(ids: Sequence[int | None]) -> list[int]:
    """去重并丢掉空 ID，避免 IN ()。"""
    return list(dict.fromkeys(pk for pk in ids if pk))


async def _models_by_id(db: AsyncSession, model: Any, ids: Sequence[int | None]) -> dict[int, Any]:
    """按主键一次取出模型。"""
    unique = _unique_ids(ids)
    if not unique:
        return {}
    rows = (await db.scalars(select(model).where(model.id.in_(unique), model.deleted == 0))).all()
    return {row.id: row for row in rows}


async def _bindings_by_rider(
    db: AsyncSession,
    rider_ids: Sequence[int],
) -> dict[int, list[RiderSalaryRiderPlanBinding]]:
    """一次取出这些骑手的方案绑定，按开始日排序。"""
    unique = _unique_ids(rider_ids)
    if not unique:
        return {}
    rows = (
        await db.scalars(
            select(RiderSalaryRiderPlanBinding)
            .where(
                RiderSalaryRiderPlanBinding.rider_id.in_(unique),
                RiderSalaryRiderPlanBinding.deleted == 0,
            )
            .order_by(RiderSalaryRiderPlanBinding.start_date.asc(), RiderSalaryRiderPlanBinding.id.asc())
        )
    ).all()
    grouped: dict[int, list[RiderSalaryRiderPlanBinding]] = defaultdict(list)
    for row in rows:
        grouped[row.rider_id].append(row)
    return grouped


class RiderService:
    """骑手服务"""

    @staticmethod
    async def _get_visible_rider(*, db: AsyncSession, request: Request, pk: int) -> Any:
        rider = await rider_dao.get(db, pk)
        if not rider:
            raise errors.NotFoundError(msg='骑手不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, rider.site_id)
        return rider

    @staticmethod
    async def _plan_meta(db: AsyncSession, version_ids: set[int]) -> dict[int, tuple[str | None, str | None]]:
        if not version_ids:
            return {}
        versions = (
            await db.scalars(select(RiderSalaryPlanVersion).where(RiderSalaryPlanVersion.id.in_(list(version_ids))))
        ).all()
        plan_ids = {item.plan_id for item in versions}
        plans = (
            (await db.scalars(select(RiderSalaryPlan).where(RiderSalaryPlan.id.in_(list(plan_ids))))).all()
            if plan_ids
            else []
        )
        plan_map = {item.id: item for item in plans}
        result: dict[int, tuple[str | None, str | None]] = {}
        for version in versions:
            plan = plan_map.get(version.plan_id)
            result[version.id] = (plan.short_name if plan else None, plan.color if plan else None)
        return result

    @staticmethod
    def _present_rider(
        rider: Any,
        *,
        site: Any | None,
        plan_version_id: int | None,
        plan_meta: tuple[str | None, str | None],
        user: Any | None,
    ) -> dict[str, Any]:
        data = snapshot(rider, _RIDER_FIELDS)
        data['hire_date'] = rider.hire_date
        data['leave_date'] = rider.leave_date
        data['created_time'] = rider.created_time
        data['updated_time'] = rider.updated_time
        data['site_name'] = site.name if site else None
        data['plan_version_id'] = plan_version_id
        data['plan_short_name'] = None
        data['plan_color'] = None
        if plan_version_id:
            data['plan_short_name'], data['plan_color'] = plan_meta
        data['account_status'] = user.status if user else None
        return data

    @staticmethod
    async def _enrich_riders(db: AsyncSession, riders: Sequence[Any]) -> list[dict[str, Any]]:
        """批量补齐站点、当日方案和账号状态，查询次数不随行数增长。"""
        if not riders:
            return []
        site_map = await _models_by_id(db, RiderSalarySite, [rider.site_id for rider in riders])
        binding_map = await _bindings_by_rider(db, [rider.id for rider in riders])
        today = timezone.now().date()
        version_by_rider: dict[int, int | None] = {}
        version_ids: set[int] = set()
        for rider in riders:
            segments = resolve_effective_plans_from_bindings(
                _binding_views(binding_map.get(rider.id, [])), today, today
            )
            plan_version_id = segments[0].plan_version_id if segments else None
            version_by_rider[rider.id] = plan_version_id
            if plan_version_id:
                version_ids.add(plan_version_id)
        meta = await RiderService._plan_meta(db, version_ids)
        user_map = await _models_by_id(db, User, [rider.user_id for rider in riders])
        return [
            RiderService._present_rider(
                rider,
                site=site_map.get(rider.site_id),
                plan_version_id=version_by_rider.get(rider.id),
                plan_meta=meta.get(version_by_rider.get(rider.id) or -1, (None, None)),
                user=user_map.get(rider.user_id) if rider.user_id else None,
            )
            for rider in riders
        ]

    @staticmethod
    async def _enrich_rider(db: AsyncSession, rider: Any) -> dict[str, Any]:
        items = await RiderService._enrich_riders(db, [rider])
        return items[0]

    @staticmethod
    async def get(*, db: AsyncSession, request: Request, pk: int) -> dict[str, Any]:
        """
        获取骑手详情

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 骑手 ID
        :return:
        """
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        return await RiderService._enrich_rider(db, rider)

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        request: Request,
        site_id: int | None,
        status: str | None,
        employ_type: str | None,
        keyword: str | None,
    ) -> dict[str, Any]:
        """
        分页获取骑手

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID
        :param status: 状态
        :param employ_type: 用工类型
        :param keyword: 工号或姓名
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        if site_id is not None:
            assert_site_visible(visible, site_id)
        stmt = await rider_dao.get_select(
            site_id=site_id,
            status=status,
            employ_type=employ_type,
            keyword=keyword,
            site_ids=visible,
        )
        page = await paging_data(db, stmt)
        raw_items = page.get('items') or []
        ids = [raw['id'] if isinstance(raw, dict) else raw.id for raw in raw_items]
        rider_map = await _models_by_id(db, RiderSalaryRider, ids)
        riders = [rider_map[pk] for pk in ids if pk in rider_map]
        page['items'] = await RiderService._enrich_riders(db, riders)
        return page

    @staticmethod
    async def create(*, db: AsyncSession, request: Request, obj: CreateRiderParam) -> None:
        """
        创建骑手并写入首条用工类型历史

        入职日所属结算周期已锁账或已发薪时拒绝。停用站点仍由 ``assert_site_accepts_rider`` 拒绝。

        :param db: 数据库会话
        :param request: 请求对象
        :param obj: 创建参数
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, obj.site_id)
        site = await site_dao.get(db, obj.site_id)
        if not site:
            raise errors.NotFoundError(msg='站点不存在')
        assert_site_accepts_rider(site)
        if await rider_dao.get_by_job_no(db, obj.job_no):
            raise errors.ConflictError(msg='工号已存在')
        await assert_not_locked(db, site_id=obj.site_id, rider_id=None, biz_date=obj.hire_date)
        rider = await rider_dao.create(db, obj)
        await rider_employ_history_dao.create(
            db,
            rider.id,
            CreateEmployHistoryParam(employ_type=obj.employ_type, start_date=obj.hire_date, end_date=None),
        )
        await mark_stale(db, rider_ids=[rider.id], date_from=obj.hire_date, date_to=obj.hire_date)
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='创建骑手',
            target_type='rider',
            target_id=rider.id,
            target_label=f'{rider.job_no} {rider.name}',
            after=snapshot(rider, _RIDER_FIELDS),
        )

    @staticmethod
    async def update(*, db: AsyncSession, request: Request, pk: int, obj: UpdateRiderParam) -> int:
        """
        更新骑手

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 骑手 ID
        :param obj: 更新参数
        :return:
        """
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if obj.job_no and obj.job_no != rider.job_no and await rider_dao.get_by_job_no(db, obj.job_no):
            raise errors.ConflictError(msg='工号已存在')
        old_site_id = int(rider.site_id)
        new_site_id = obj.site_id
        site_changed = new_site_id is not None and new_site_id != old_site_id
        if site_changed and new_site_id is not None:
            await _assert_transfer_allowed(db, request, rider, new_site_id, obj.reason)
        hire_spans = await _locked_hire_change(
            db,
            rider,
            obj.hire_date,
            extra_site_id=new_site_id if site_changed else None,
        )
        before = snapshot(rider, _RIDER_FIELDS)
        count = await rider_dao.update(db, pk, obj)
        updated = await rider_dao.get(db, pk)
        if hire_spans:
            await _mark_employ_stale(db, rider_id=pk, spans=hire_spans)
        if site_changed and new_site_id is not None:
            await _mark_sites_open_stale(db, rider_id=pk, site_ids=[old_site_id, new_site_id])
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='修改骑手',
            target_type='rider',
            target_id=pk,
            target_label=f'{rider.job_no} {rider.name}',
            reason=obj.reason,
            before=before,
            after=snapshot(updated, _RIDER_FIELDS) if updated else None,
        )
        return count

    @staticmethod
    async def delete(*, db: AsyncSession, request: Request, pk: int) -> int:
        """
        删除骑手

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 骑手 ID
        :return:
        """
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        order_count = await db.scalar(
            select(func.count())
            .select_from(RiderSalaryOrder)
            .where(
                RiderSalaryOrder.rider_id == pk,
                RiderSalaryOrder.deleted == 0,
            )
        )
        payroll_count = await db.scalar(
            select(func.count())
            .select_from(RiderSalaryPayroll)
            .where(
                RiderSalaryPayroll.rider_id == pk,
                RiderSalaryPayroll.deleted == 0,
            )
        )
        if int(order_count or 0) > 0 or int(payroll_count or 0) > 0:
            raise errors.ConflictError(msg='该骑手已有业务数据，请改为离职')
        before = snapshot(rider, _RIDER_FIELDS)
        count = await rider_dao.delete(db, pk)
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='删除骑手',
            target_type='rider',
            target_id=pk,
            target_label=f'{rider.job_no} {rider.name}',
            before=before,
        )
        return count

    @staticmethod
    async def leave(*, db: AsyncSession, request: Request, pk: int, obj: RiderLeaveParam) -> RiderLeaveResult:
        """
        骑手离职

        同一事务内截止开放方案绑定、收尾用工历史、标记离职日所在周期需重算，
        并自动驳回待审核预支。待发放预支不自动取消，由返回提示交给管理员处理。
        离职日所在周期已锁账时拒绝，请走反冲。

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 骑手 ID
        :param obj: 离职参数
        :return:
        """
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if rider.status == RiderStatus.resigned:
            raise errors.ConflictError(msg='该骑手已离职')
        histories = list(await rider_employ_history_dao.get_by_rider(db, pk))
        assert_leave_not_before_employment(rider.hire_date, histories, obj.leave_date)
        bindings = list(await rider_plan_binding_dao.get_by_rider(db, pk))
        closing_bindings = open_bindings_ending_on_leave(bindings, obj.leave_date)
        employ_changed = leave_employ_touch(histories, obj.leave_date)
        binding_changed = binding_close_spans(closing_bindings, obj.leave_date)
        await assert_range_unlocked(
            db,
            site_id=rider.site_id,
            rider_id=pk,
            ranges=leave_lock_ranges(employ_changed, binding_changed, obj.leave_date),
        )
        binding_befores = [(row, snapshot(row, _BINDING_FIELDS)) for row in closing_bindings]
        for row, _before in binding_befores:
            await rider_plan_binding_dao.update(db, row.id, UpdatePlanBindingParam(end_date=obj.leave_date))
        open_histories = [item for item in histories if item.end_date is None and item.start_date <= obj.leave_date]
        history_befores = [(item, snapshot(item, _HISTORY_FIELDS)) for item in open_histories]
        await rider_employ_history_dao.close_open(db, pk, obj.leave_date)
        before_rider = snapshot(rider, _RIDER_FIELDS)
        count = await rider_dao.update(
            db,
            pk,
            UpdateRiderParam(reason=obj.reason),
            status=RiderStatus.resigned,
            leave_date=obj.leave_date,
        )
        if count <= 0:
            raise errors.RequestError(msg='办理离职失败')
        updated = await rider_dao.get(db, pk)
        await _mark_employ_stale(db, rider_id=pk, spans=[(obj.leave_date, obj.leave_date)])
        await _mark_employ_stale(db, rider_id=pk, spans=binding_changed)
        await _mark_employ_stale(db, rider_id=pk, spans=employ_changed)
        for row, before in binding_befores:
            after = dict(before)
            after['end_date'] = obj.leave_date.isoformat()
            await audit_service.record(
                db,
                request,
                module='骑手管理',
                action='修改方案绑定',
                target_type='rider_plan_binding',
                target_id=row.id,
                target_label=f'{rider.job_no} {rider.name}',
                reason=obj.reason,
                before=before,
                after=after,
            )
        for item, before in history_befores:
            after = dict(before)
            after['end_date'] = obj.leave_date.isoformat()
            await audit_service.record(
                db,
                request,
                module='骑手管理',
                action='修改用工类型历史',
                target_type='rider_employ_history',
                target_id=item.id,
                target_label=f'{rider.job_no} {rider.name}',
                reason=obj.reason,
                before=before,
                after=after,
            )
        outcome = await advance_service.reject_pending_on_leave(db=db, request=request, rider_id=pk)
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='骑手离职',
            target_type='rider',
            target_id=pk,
            target_label=f'{rider.job_no} {rider.name}',
            reason=obj.reason,
            before=before_rider,
            after=snapshot(updated, _RIDER_FIELDS) if updated else None,
        )
        return RiderLeaveResult(
            hints=list(outcome.hints),
            rejected_advance_count=outcome.rejected_count,
            to_pay_advance_count=outcome.to_pay_count,
        )

    @staticmethod
    async def list_employ_history(*, db: AsyncSession, request: Request, pk: int) -> Any:
        """获取用工类型历史"""
        await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        return await rider_employ_history_dao.get_by_rider(db, pk)

    @staticmethod
    async def create_employ_history(
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        obj: CreateEmployHistoryParam,
    ) -> None:
        """创建用工类型历史"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        check_range_order(obj.start_date, obj.end_date)
        existing = await rider_employ_history_dao.get_by_rider(db, pk)
        closings, changed = employ_create_ranges(existing, obj.start_date, obj.end_date)
        await assert_range_unlocked(db, site_id=rider.site_id, rider_id=pk, ranges=changed)
        for item, close_end in closings:
            before = snapshot(item, _HISTORY_FIELDS)
            await rider_employ_history_dao.update(
                db,
                item.id,
                UpdateEmployHistoryParam(end_date=close_end),
            )
            updated = await rider_employ_history_dao.get(db, item.id)
            await audit_service.record(
                db,
                request,
                module='骑手管理',
                action='修改用工类型历史',
                target_type='rider_employ_history',
                target_id=item.id,
                target_label=f'{rider.job_no} {rider.name}',
                before=before,
                after=snapshot(updated, _HISTORY_FIELDS) if updated else None,
            )
        existing = await rider_employ_history_dao.get_by_rider(db, pk)
        check_employ_overlap(existing, obj.start_date, obj.end_date)
        row = await rider_employ_history_dao.create(db, pk, obj)
        today = timezone.now().date()
        if obj.start_date <= today <= _as_end(obj.end_date):
            await rider_dao.update(db, pk, UpdateRiderParam(), employ_type=obj.employ_type)
        await _mark_employ_stale(db, rider_id=pk, spans=changed)
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='新增用工类型历史',
            target_type='rider_employ_history',
            target_id=row.id,
            target_label=f'{rider.job_no} {rider.name}',
            after=snapshot(row, _HISTORY_FIELDS),
        )

    @staticmethod
    async def update_employ_history(
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        history_id: int,
        obj: UpdateEmployHistoryParam,
    ) -> int:
        """更新用工类型历史"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        row = await rider_employ_history_dao.get(db, history_id)
        if not row or row.rider_id != pk:
            raise errors.NotFoundError(msg='用工类型历史不存在')
        start_date = obj.start_date or row.start_date
        end_date = row.end_date if obj.end_date is None and obj.start_date is None else obj.end_date
        if obj.end_date is None and obj.start_date is not None:
            end_date = row.end_date
        check_range_order(start_date, end_date)
        existing = await rider_employ_history_dao.get_by_rider(db, pk)
        check_employ_overlap(existing, start_date, end_date, exclude_id=history_id)
        old_start, old_end = row.start_date, row.end_date
        type_changed = obj.employ_type is not None and str(getattr(obj.employ_type, 'value', obj.employ_type)) != str(
            getattr(row.employ_type, 'value', row.employ_type)
        )
        changed = changed_coverage_spans(old_start, old_end, start_date, end_date, type_changed=type_changed)
        await assert_range_unlocked(db, site_id=rider.site_id, rider_id=pk, ranges=changed)
        before = snapshot(row, _HISTORY_FIELDS)
        count = await rider_employ_history_dao.update(db, history_id, obj)
        updated = await rider_employ_history_dao.get(db, history_id)
        await _mark_employ_stale(db, rider_id=pk, spans=changed)
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='修改用工类型历史',
            target_type='rider_employ_history',
            target_id=history_id,
            target_label=f'{rider.job_no} {rider.name}',
            before=before,
            after=snapshot(updated, _HISTORY_FIELDS) if updated else None,
        )
        return count

    @staticmethod
    async def delete_employ_history(*, db: AsyncSession, request: Request, pk: int, history_id: int) -> int:
        """删除用工类型历史"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        row = await rider_employ_history_dao.get(db, history_id)
        if not row or row.rider_id != pk:
            raise errors.NotFoundError(msg='用工类型历史不存在')
        span = (row.start_date, row.end_date)
        await assert_range_unlocked(db, site_id=rider.site_id, rider_id=pk, ranges=[span])
        before = snapshot(row, _HISTORY_FIELDS)
        count = await rider_employ_history_dao.delete(db, history_id)
        await _mark_employ_stale(db, rider_id=pk, spans=[span])
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='删除用工类型历史',
            target_type='rider_employ_history',
            target_id=history_id,
            target_label=f'{rider.job_no} {rider.name}',
            before=before,
        )
        return count

    @staticmethod
    async def _assert_plan_version_active(
        db: AsyncSession,
        plan_version_id: int,
        *,
        new_assignment: bool = True,
    ) -> RiderSalaryPlanVersion:
        """绑定前确认版本启用；新绑定时还确认所属方案未停用。

        :param db: 数据库会话
        :param plan_version_id: 方案版本 ID
        :param new_assignment: 新建绑定，或把已有绑定改到另一个版本
        :return:
        """
        version = await db.get(RiderSalaryPlanVersion, plan_version_id)
        if version is None or version.deleted != 0:
            raise errors.NotFoundError(msg='方案版本不存在')
        plan = None
        if new_assignment:
            plan = await plan_dao.get(db, version.plan_id)
            if plan is None:
                raise errors.NotFoundError(msg='方案不存在')
        assert_binding_target(version, plan, new_assignment=new_assignment)
        return version

    @staticmethod
    async def list_bindings(*, db: AsyncSession, request: Request, pk: int) -> list[dict[str, Any]]:
        """获取方案绑定"""
        await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        rows = await rider_plan_binding_dao.get_by_rider(db, pk)
        meta = await RiderService._plan_meta(db, {row.plan_version_id for row in rows})
        result = []
        for row in rows:
            item = snapshot(row, _BINDING_FIELDS)
            item['start_date'] = row.start_date
            item['end_date'] = row.end_date
            item['created_time'] = row.created_time
            item['updated_time'] = row.updated_time
            short_name, color = meta.get(row.plan_version_id, (None, None))
            item['plan_short_name'] = short_name
            item['plan_color'] = color
            result.append(item)
        return result

    @staticmethod
    async def create_binding(
        *, db: AsyncSession, request: Request, pk: int, obj: CreatePlanBindingParam
    ) -> RiderSalaryRiderPlanBinding:
        """创建方案绑定"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if obj.binding_type == BindingType.override and obj.end_date is None:
            raise errors.RequestError(msg='区间覆盖绑定必须填写开始和结束日期')
        check_range_order(obj.start_date, obj.end_date)
        version = await RiderService._assert_plan_version_active(db, obj.plan_version_id)
        existing = await rider_plan_binding_dao.get_by_rider(db, pk)
        check_binding_overlap(_binding_views(existing), obj.binding_type, obj.start_date, obj.end_date)
        await assert_range_unlocked(
            db,
            site_id=rider.site_id,
            rider_id=pk,
            ranges=[(obj.start_date, obj.end_date)],
        )
        before = {'exists': False, 'rider_id': rider.id}
        row = await rider_plan_binding_dao.create(db, pk, obj)
        if not version.is_used:
            version.is_used = True
        await _mark_employ_stale(db, rider_id=pk, spans=[(obj.start_date, obj.end_date)])
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='新增方案绑定',
            target_type='rider_plan_binding',
            target_id=row.id,
            target_label=f'{rider.job_no} {rider.name}',
            before=before,
            after=snapshot(row, _BINDING_FIELDS),
        )
        return row

    @staticmethod
    async def update_binding(
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        binding_id: int,
        obj: UpdatePlanBindingParam,
    ) -> int:
        """更新方案绑定"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        row = await rider_plan_binding_dao.get(db, binding_id)
        if not row or row.rider_id != pk:
            raise errors.NotFoundError(msg='方案绑定不存在')
        binding_type = obj.binding_type or row.binding_type
        start_date = obj.start_date or row.start_date
        end_date = obj.end_date if obj.end_date is not None or obj.start_date is not None else row.end_date
        if obj.end_date is None and obj.start_date is None:
            end_date = row.end_date
        if binding_type == BindingType.override and end_date is None:
            raise errors.RequestError(msg='区间覆盖绑定必须填写开始和结束日期')
        check_range_order(start_date, end_date)
        plan_version_id = obj.plan_version_id or row.plan_version_id
        plan_changed = str(plan_version_id) != str(row.plan_version_id)
        version = await RiderService._assert_plan_version_active(
            db,
            plan_version_id,
            new_assignment=plan_changed,
        )
        existing = await rider_plan_binding_dao.get_by_rider(db, pk)
        check_binding_overlap(_binding_views(existing), binding_type, start_date, end_date, exclude_id=binding_id)
        binding_type_changed = str(getattr(binding_type, 'value', binding_type)) != str(
            getattr(row.binding_type, 'value', row.binding_type)
        )
        changed = changed_coverage_spans(
            row.start_date,
            row.end_date,
            start_date,
            end_date,
            type_changed=plan_changed or binding_type_changed,
        )
        await assert_range_unlocked(db, site_id=rider.site_id, rider_id=pk, ranges=changed)
        before = snapshot(row, _BINDING_FIELDS)
        count = await rider_plan_binding_dao.update(db, binding_id, obj)
        if not version.is_used:
            version.is_used = True
        updated = await rider_plan_binding_dao.get(db, binding_id)
        await _mark_employ_stale(db, rider_id=pk, spans=changed)
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='修改方案绑定',
            target_type='rider_plan_binding',
            target_id=binding_id,
            target_label=f'{rider.job_no} {rider.name}',
            before=before,
            after=snapshot(updated, _BINDING_FIELDS) if updated else None,
        )
        return count

    @staticmethod
    async def delete_binding(*, db: AsyncSession, request: Request, pk: int, binding_id: int) -> int:
        """删除方案绑定"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        row = await rider_plan_binding_dao.get(db, binding_id)
        if not row or row.rider_id != pk:
            raise errors.NotFoundError(msg='方案绑定不存在')
        await assert_range_unlocked(
            db,
            site_id=rider.site_id,
            rider_id=pk,
            ranges=[(row.start_date, row.end_date)],
        )
        before = snapshot(row, _BINDING_FIELDS)
        count = await rider_plan_binding_dao.delete(db, binding_id)
        await _mark_employ_stale(db, rider_id=pk, spans=[(row.start_date, row.end_date)])
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='删除方案绑定',
            target_type='rider_plan_binding',
            target_id=binding_id,
            target_label=f'{rider.job_no} {rider.name}',
            before=before,
        )
        return count

    @staticmethod
    async def get_effective_plans(
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        start: date,
        end: date,
    ) -> list[GetEffectivePlanSegment]:
        """获取按日解析后的生效方案区间"""
        await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if end < start:
            raise errors.RequestError(msg='结束日期不能早于开始日期')
        segments = await resolve_effective_plans(db, pk, start, end)
        version_ids = {item.plan_version_id for item in segments if item.plan_version_id}
        meta = await RiderService._plan_meta(db, version_ids)
        result: list[GetEffectivePlanSegment] = []
        for item in segments:
            short_name, color = meta.get(item.plan_version_id, (None, None)) if item.plan_version_id else (None, None)
            result.append(
                GetEffectivePlanSegment(
                    start=item.start,
                    end=item.end,
                    plan_version_id=item.plan_version_id,
                    plan_short_name=short_name,
                    plan_color=color,
                )
            )
        return result

    @staticmethod
    async def open_account(
        *, db: AsyncSession, request: Request, pk: int, obj: OpenRiderAccountParam
    ) -> IssuedRiderPassword:
        """开通骑手账号。未传密码时生成随机口令，只在本次结果中返回。"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        assert_rider_can_open_account(rider)
        if rider.user_id:
            raise errors.ConflictError(msg='该骑手已开通账号')
        existing_user = await user_dao.get_by_username(db, rider.job_no)
        if existing_user:
            await _reject_if_user_bound(db, int(existing_user.id), pk)
            raise errors.ConflictError(msg='工号对应用户名已存在')
        role = await find_rider_role(db)
        if not role:
            raise errors.NotFoundError(msg='未找到骑手角色，请确认已初始化种子锚点 rs-role:rider')
        site = await site_dao.get(db, rider.site_id)
        dept_id = (site.dept_id if site else None) or getattr(request.user, 'dept_id', None)
        if not dept_id:
            raise errors.RequestError(msg='请先为站点或当前用户关联部门后再开通账号')
        password, revealed = _issue_password(obj.password)
        await sys_user_service.create(
            db=db,
            obj=AddUserParam(
                username=rider.job_no,
                password=password,
                nickname=rider.name,
                phone=_user_phone(rider.phone),
                dept_id=int(dept_id),
                roles=[role.id],
            ),
        )
        user = await user_dao.get_by_username(db, rider.job_no)
        if not user:
            raise errors.ServerError(msg='开通骑手账号失败')
        await user_dao.set_staff(db, user.id, is_staff=False)
        await user_dao.set_super(db, user.id, is_super=False)
        await _reject_if_user_bound(db, int(user.id), pk)
        before = {
            'user_id': rider.user_id,
            'username': None,
            'must_change_password': bool(getattr(rider, 'must_change_password', False)),
        }
        try:
            await rider_dao.update(db, pk, UpdateRiderParam(), user_id=user.id, must_change_password=True)
        except IntegrityError as exc:
            raise client_error_from_integrity(exc) from exc
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='开通骑手账号',
            target_type='rider',
            target_id=pk,
            target_label=f'{rider.job_no} {rider.name}',
            reason=obj.reason,
            before=before,
            after={'user_id': user.id, 'username': user.username, 'must_change_password': True},
        )
        return IssuedRiderPassword(username=rider.job_no, initial_password=revealed)

    @staticmethod
    async def reset_password(
        *, db: AsyncSession, request: Request, pk: int, obj: ResetRiderPasswordParam
    ) -> IssuedRiderPassword:
        """重置骑手密码。未传密码时生成随机口令，并重新要求首次登录改密。"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if not rider.user_id:
            raise errors.NotFoundError(msg='该骑手尚未开通账号')
        before = {
            'user_id': rider.user_id,
            'must_change_password': bool(getattr(rider, 'must_change_password', False)),
        }
        password, revealed = _issue_password(obj.password)
        await sys_user_service.reset_password(db=db, pk=rider.user_id, password=password)
        await rider_dao.update(db, pk, UpdateRiderParam(), must_change_password=True)
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='重置骑手密码',
            target_type='rider',
            target_id=pk,
            target_label=f'{rider.job_no} {rider.name}',
            reason=obj.reason,
            before=before,
            after={'user_id': rider.user_id, 'must_change_password': True},
        )
        return IssuedRiderPassword(username=rider.job_no, initial_password=revealed)

    @staticmethod
    async def disable_account(*, db: AsyncSession, request: Request, pk: int, obj: DisableRiderAccountParam) -> None:
        """停用骑手账号"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if not rider.user_id:
            raise errors.NotFoundError(msg='该骑手尚未开通账号')
        account = await user_dao.get(db, rider.user_id)
        before = {'user_id': rider.user_id, 'status': getattr(account, 'status', None)}
        await user_dao.set_status(db, rider.user_id, 0)
        await redis_client.delete(f'{settings.JWT_USER_REDIS_PREFIX}:{rider.user_id}')
        await redis_client.delete_by_prefix(f'{settings.TOKEN_REDIS_PREFIX}:{rider.user_id}')
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='停用骑手账号',
            target_type='rider',
            target_id=pk,
            target_label=f'{rider.job_no} {rider.name}',
            reason=obj.reason,
            before=before,
            after={'user_id': rider.user_id, 'status': 0},
        )

    @staticmethod
    async def enable_account(*, db: AsyncSession, request: Request, pk: int, obj: EnableRiderAccountParam) -> None:
        """启用骑手账号"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if not rider.user_id:
            raise errors.NotFoundError(msg='该骑手尚未开通账号')
        assert_rider_can_enable_account(rider)
        account = await user_dao.get(db, rider.user_id)
        before = {'user_id': rider.user_id, 'status': getattr(account, 'status', None)}
        await user_dao.set_status(db, rider.user_id, 1)
        await redis_client.delete(f'{settings.JWT_USER_REDIS_PREFIX}:{rider.user_id}')
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='启用骑手账号',
            target_type='rider',
            target_id=pk,
            target_label=f'{rider.job_no} {rider.name}',
            reason=obj.reason,
            before=before,
            after={'user_id': rider.user_id, 'status': 1},
        )

    @staticmethod
    async def _run_rider_batch(
        *,
        db: AsyncSession,
        request: Request,
        rider_ids: list[int],
        worker: Callable[[Any], Awaitable[Any]],
    ) -> list[Any]:
        """逐条执行。任一失败收集后整单回滚，成功的条目已经走过单条写路径。"""
        result: list[Any] = []
        row_errors: list[dict[str, Any]] = []
        for index, rider_id in enumerate(rider_ids, start=1):
            label = f'骑手 {rider_id}'
            try:
                rider = await RiderService._get_visible_rider(db=db, request=request, pk=rider_id)
                label = f'{rider.job_no} {rider.name}'.strip()
                item = await worker(rider)
            except errors.BaseExceptionError as exc:
                row_errors.append({
                    'row': index,
                    'rider_id': rider_id,
                    'reason': f'{label}：{exc.msg or "操作失败"}',
                })
                continue
            result.append(item)
        if row_errors:
            prompts = [f'第 {item["row"]} 名：{item["reason"]}' for item in row_errors]
            raise errors.RequestError(msg='；'.join(prompts), data={'errors': row_errors})
        return result

    @staticmethod
    async def create_bindings_batch(
        *,
        db: AsyncSession,
        request: Request,
        obj: BatchPlanBindingParam,
    ) -> BatchBindingResult:
        """批量绑定方案。每名骑手调用单条绑定，锁账、重算和审计都不跳过。"""
        single = CreatePlanBindingParam(
            plan_version_id=obj.plan_version_id,
            binding_type=obj.binding_type,
            start_date=obj.start_date,
            end_date=obj.end_date,
            remark=obj.remark,
        )

        async def bind_one(rider: Any) -> BatchBindingItem:
            row = await RiderService.create_binding(db=db, request=request, pk=rider.id, obj=single)
            return BatchBindingItem(rider_id=rider.id, binding_id=row.id, job_no=rider.job_no, name=rider.name)

        items = await RiderService._run_rider_batch(
            db=db,
            request=request,
            rider_ids=list(obj.rider_ids),
            worker=bind_one,
        )
        return BatchBindingResult(count=len(items), items=items)

    @staticmethod
    async def open_accounts_batch(
        *,
        db: AsyncSession,
        request: Request,
        obj: BatchOpenAccountParam,
    ) -> BatchIssuedPasswordResult:
        """批量开通账号。每人独立随机密码，并要求首次登录改密。"""

        async def open_one(rider: Any) -> BatchIssuedPasswordItem:
            issued = await RiderService.open_account(
                db=db,
                request=request,
                pk=rider.id,
                obj=OpenRiderAccountParam(password=None, reason=obj.reason),
            )
            if not issued.initial_password:
                raise errors.ServerError(msg='批量开户必须返回随机密码')
            return BatchIssuedPasswordItem(
                rider_id=rider.id,
                job_no=rider.job_no,
                name=rider.name,
                username=issued.username,
                initial_password=issued.initial_password,
            )

        items = await RiderService._run_rider_batch(
            db=db,
            request=request,
            rider_ids=list(obj.rider_ids),
            worker=open_one,
        )
        return BatchIssuedPasswordResult(items=items)

    @staticmethod
    async def reset_passwords_batch(
        *,
        db: AsyncSession,
        request: Request,
        obj: BatchResetPasswordParam,
    ) -> BatchIssuedPasswordResult:
        """批量重置密码。每人独立随机密码，并重新要求首次登录改密。"""

        async def reset_one(rider: Any) -> BatchIssuedPasswordItem:
            issued = await RiderService.reset_password(
                db=db,
                request=request,
                pk=rider.id,
                obj=ResetRiderPasswordParam(password=None, reason=obj.reason),
            )
            if not issued.initial_password:
                raise errors.ServerError(msg='批量重置必须返回随机密码')
            return BatchIssuedPasswordItem(
                rider_id=rider.id,
                job_no=rider.job_no,
                name=rider.name,
                username=issued.username,
                initial_password=issued.initial_password,
            )

        items = await RiderService._run_rider_batch(
            db=db,
            request=request,
            rider_ids=list(obj.rider_ids),
            worker=reset_one,
        )
        return BatchIssuedPasswordResult(items=items)


rider_service: RiderService = RiderService()
