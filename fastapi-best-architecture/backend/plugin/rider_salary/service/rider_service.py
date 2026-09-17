from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from re import fullmatch
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.admin.crud.crud_role import role_dao
from backend.app.admin.crud.crud_user import user_dao
from backend.app.admin.schema.user import AddUserParam
from backend.app.admin.service.user_service import user_service as sys_user_service
from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.core.conf import settings
from backend.database.redis import redis_client
from backend.plugin.rider_salary.crud.rider import rider_dao
from backend.plugin.rider_salary.crud.rider_employ_history import rider_employ_history_dao
from backend.plugin.rider_salary.crud.rider_plan_binding import rider_plan_binding_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.enums import BindingType, PeriodStatus, PlanVersionStatus, RiderStatus
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider_employ_history import RiderSalaryRiderEmployHistory
from backend.plugin.rider_salary.model.rider_plan_binding import RiderSalaryRiderPlanBinding
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.schema.rider import (
    CreateEmployHistoryParam,
    CreatePlanBindingParam,
    CreateRiderParam,
    DisableRiderAccountParam,
    EnableRiderAccountParam,
    GetEffectivePlanSegment,
    OpenRiderAccountParam,
    ResetRiderPasswordParam,
    RiderLeaveParam,
    UpdateEmployHistoryParam,
    UpdatePlanBindingParam,
    UpdateRiderParam,
)
from backend.plugin.rider_salary.service.audit_service import audit_service, snapshot
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.lock_check import assert_not_locked
from backend.plugin.rider_salary.utils.recalc import invalidate_payroll_dailies, mark_stale
from backend.utils.timezone import timezone

_OPEN_END = date(9999, 12, 31)
_MOBILE = r'^1[3-9]\d{9}$'
_RIDER_ROLE_NAME = '骑手'
_DEFAULT_PASSWORD = 'Rider@123456'
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


def _default_password(phone: str | None) -> str:
    if phone and len(phone) >= 6:
        return f'Rider@{phone[-6:]}'
    return _DEFAULT_PASSWORD


def _user_phone(phone: str | None) -> str | None:
    if phone and fullmatch(_MOBILE, phone):
        return phone
    return None


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
    async def _enrich_rider(db: AsyncSession, rider: Any) -> dict[str, Any]:
        data = snapshot(rider, _RIDER_FIELDS)
        data['hire_date'] = rider.hire_date
        data['leave_date'] = rider.leave_date
        data['created_time'] = rider.created_time
        data['updated_time'] = rider.updated_time
        site = await site_dao.get(db, rider.site_id)
        data['site_name'] = site.name if site else None
        today = timezone.now().date()
        segments = await resolve_effective_plans(db, rider.id, today, today)
        plan_version_id = segments[0].plan_version_id if segments else None
        data['plan_version_id'] = plan_version_id
        data['plan_short_name'] = None
        data['plan_color'] = None
        if plan_version_id:
            meta = await RiderService._plan_meta(db, {plan_version_id})
            data['plan_short_name'], data['plan_color'] = meta.get(plan_version_id, (None, None))
        data['account_status'] = None
        if rider.user_id:
            user = await user_dao.get(db, rider.user_id)
            data['account_status'] = user.status if user else None
        return data

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
        items = []
        for raw in page.get('items') or []:
            pk = raw['id'] if isinstance(raw, dict) else raw.id
            rider = await rider_dao.get(db, pk)
            if rider:
                items.append(await RiderService._enrich_rider(db, rider))
        page['items'] = items
        return page

    @staticmethod
    async def create(*, db: AsyncSession, request: Request, obj: CreateRiderParam) -> None:
        """
        创建骑手并写入首条用工类型历史

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
        if await rider_dao.get_by_job_no(db, obj.job_no):
            raise errors.ConflictError(msg='工号已存在')
        rider = await rider_dao.create(db, obj)
        await rider_employ_history_dao.create(
            db,
            rider.id,
            CreateEmployHistoryParam(employ_type=obj.employ_type, start_date=obj.hire_date, end_date=None),
        )
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
        if obj.site_id is not None and obj.site_id != rider.site_id:
            if not (obj.reason and obj.reason.strip()):
                raise errors.RequestError(msg='请填写操作原因')
            visible = await get_visible_site_ids(request, db)
            assert_site_visible(visible, obj.site_id)
            if not await site_dao.get(db, obj.site_id):
                raise errors.NotFoundError(msg='站点不存在')
        before = snapshot(rider, _RIDER_FIELDS)
        count = await rider_dao.update(db, pk, obj)
        updated = await rider_dao.get(db, pk)
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
    async def leave(*, db: AsyncSession, request: Request, pk: int, obj: RiderLeaveParam) -> int:
        """
        骑手离职

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 骑手 ID
        :param obj: 离职参数
        :return:
        """
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if rider.status == RiderStatus.resigned:
            raise errors.ConflictError(msg='该骑手已离职')
        before = snapshot(rider, _RIDER_FIELDS)
        await rider_employ_history_dao.close_open(db, pk, obj.leave_date)
        count = await rider_dao.update(
            db,
            pk,
            UpdateRiderParam(status=RiderStatus.resigned, leave_date=obj.leave_date, reason=obj.reason),
        )
        updated = await rider_dao.get(db, pk)
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='骑手离职',
            target_type='rider',
            target_id=pk,
            target_label=f'{rider.job_no} {rider.name}',
            reason=obj.reason,
            before=before,
            after=snapshot(updated, _RIDER_FIELDS) if updated else None,
        )
        return count

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
        for item in existing:
            if item.end_date is not None or item.start_date >= obj.start_date:
                continue
            close_end = obj.start_date - timedelta(days=1)
            if close_end < item.start_date:
                continue
            before = snapshot(item, _HISTORY_FIELDS)
            await rider_employ_history_dao.update(
                db,
                item.id,
                UpdateEmployHistoryParam(end_date=close_end),
            )
            updated = await rider_employ_history_dao.get(db, item.id)
            await mark_stale(
                db,
                rider_ids=[pk],
                date_from=item.start_date,
                date_to=close_end,
            )
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
            await rider_dao.update(db, pk, UpdateRiderParam(employ_type=obj.employ_type))
        await mark_stale(db, rider_ids=[pk], date_from=obj.start_date, date_to=_as_end(obj.end_date))
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
        before = snapshot(row, _HISTORY_FIELDS)
        count = await rider_employ_history_dao.update(db, history_id, obj)
        updated = await rider_employ_history_dao.get(db, history_id)
        date_from = min(row.start_date, start_date)
        date_to = max(_as_end(row.end_date), _as_end(end_date))
        await mark_stale(db, rider_ids=[pk], date_from=date_from, date_to=date_to)
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
        before = snapshot(row, _HISTORY_FIELDS)
        count = await rider_employ_history_dao.delete(db, history_id)
        await mark_stale(db, rider_ids=[pk], date_from=row.start_date, date_to=_as_end(row.end_date))
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
    async def _assert_plan_version_active(db: AsyncSession, plan_version_id: int) -> RiderSalaryPlanVersion:
        version = await db.get(RiderSalaryPlanVersion, plan_version_id)
        if version is None or version.deleted != 0:
            raise errors.NotFoundError(msg='方案版本不存在')
        if version.status != PlanVersionStatus.active:
            raise errors.RequestError(msg='只能绑定启用状态的方案版本')
        return version

    @staticmethod
    async def _assert_binding_unlocked(
        db: AsyncSession,
        *,
        site_id: int,
        rider_id: int,
        start_date: date,
        end_date: date | None,
    ) -> None:
        await assert_not_locked(db, site_id=site_id, rider_id=rider_id, biz_date=start_date)
        if end_date is not None:
            await assert_not_locked(db, site_id=site_id, rider_id=rider_id, biz_date=end_date)
        locked = await db.scalar(
            select(RiderSalarySettlePeriod.id)
            .where(
                RiderSalarySettlePeriod.site_id == site_id,
                RiderSalarySettlePeriod.rider_id.in_([rider_id, 0]),
                RiderSalarySettlePeriod.status.in_(list(_LOCKED_PERIOD_STATUSES)),
                RiderSalarySettlePeriod.start_date <= _as_end(end_date),
                RiderSalarySettlePeriod.end_date >= start_date,
                RiderSalarySettlePeriod.deleted == 0,
            )
            .limit(1)
        )
        if locked is not None:
            raise errors.ForbiddenError(msg='该日期所属结算周期已锁账，禁止修改，请走反冲补发流程')

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
    async def create_binding(*, db: AsyncSession, request: Request, pk: int, obj: CreatePlanBindingParam) -> None:
        """创建方案绑定"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if obj.binding_type == BindingType.override and obj.end_date is None:
            raise errors.RequestError(msg='区间覆盖绑定必须填写开始和结束日期')
        check_range_order(obj.start_date, obj.end_date)
        version = await RiderService._assert_plan_version_active(db, obj.plan_version_id)
        existing = await rider_plan_binding_dao.get_by_rider(db, pk)
        check_binding_overlap(_binding_views(existing), obj.binding_type, obj.start_date, obj.end_date)
        await RiderService._assert_binding_unlocked(
            db,
            site_id=rider.site_id,
            rider_id=pk,
            start_date=obj.start_date,
            end_date=obj.end_date,
        )
        row = await rider_plan_binding_dao.create(db, pk, obj)
        if not version.is_used:
            version.is_used = True
        await mark_stale(db, rider_ids=[pk], date_from=obj.start_date, date_to=_as_end(obj.end_date))
        await invalidate_payroll_dailies(db, rider_ids=[pk], date_from=obj.start_date, date_to=_as_end(obj.end_date))
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='新增方案绑定',
            target_type='rider_plan_binding',
            target_id=row.id,
            target_label=f'{rider.job_no} {rider.name}',
            after=snapshot(row, _BINDING_FIELDS),
        )

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
        version = await RiderService._assert_plan_version_active(db, plan_version_id)
        existing = await rider_plan_binding_dao.get_by_rider(db, pk)
        check_binding_overlap(_binding_views(existing), binding_type, start_date, end_date, exclude_id=binding_id)
        await RiderService._assert_binding_unlocked(
            db,
            site_id=rider.site_id,
            rider_id=pk,
            start_date=start_date,
            end_date=end_date,
        )
        before = snapshot(row, _BINDING_FIELDS)
        count = await rider_plan_binding_dao.update(db, binding_id, obj)
        if not version.is_used:
            version.is_used = True
        updated = await rider_plan_binding_dao.get(db, binding_id)
        date_from = min(row.start_date, start_date)
        date_to = max(_as_end(row.end_date), _as_end(end_date))
        await mark_stale(db, rider_ids=[pk], date_from=date_from, date_to=date_to)
        await invalidate_payroll_dailies(db, rider_ids=[pk], date_from=date_from, date_to=date_to)
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
        await RiderService._assert_binding_unlocked(
            db,
            site_id=rider.site_id,
            rider_id=pk,
            start_date=row.start_date,
            end_date=row.end_date,
        )
        before = snapshot(row, _BINDING_FIELDS)
        count = await rider_plan_binding_dao.delete(db, binding_id)
        await mark_stale(db, rider_ids=[pk], date_from=row.start_date, date_to=_as_end(row.end_date))
        await invalidate_payroll_dailies(db, rider_ids=[pk], date_from=row.start_date, date_to=_as_end(row.end_date))
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
    async def open_account(*, db: AsyncSession, request: Request, pk: int, obj: OpenRiderAccountParam) -> None:
        """开通骑手账号"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if rider.user_id:
            raise errors.ConflictError(msg='该骑手已开通账号')
        if await user_dao.get_by_username(db, rider.job_no):
            raise errors.ConflictError(msg='工号对应用户名已存在')
        role = await role_dao.get_by_name(db, _RIDER_ROLE_NAME)
        if not role:
            raise errors.NotFoundError(msg='角色「骑手」不存在')
        site = await site_dao.get(db, rider.site_id)
        dept_id = (site.dept_id if site else None) or getattr(request.user, 'dept_id', None)
        if not dept_id:
            raise errors.RequestError(msg='请先为站点或当前用户关联部门后再开通账号')
        password = obj.password or _default_password(rider.phone)
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
        await rider_dao.update(db, pk, UpdateRiderParam(), user_id=user.id)
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='开通骑手账号',
            target_type='rider',
            target_id=pk,
            target_label=f'{rider.job_no} {rider.name}',
            reason=obj.reason,
            after={'user_id': user.id, 'username': user.username},
        )

    @staticmethod
    async def reset_password(*, db: AsyncSession, request: Request, pk: int, obj: ResetRiderPasswordParam) -> None:
        """重置骑手密码"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if not rider.user_id:
            raise errors.NotFoundError(msg='该骑手尚未开通账号')
        password = obj.password or _default_password(rider.phone)
        await sys_user_service.reset_password(db=db, pk=rider.user_id, password=password)
        await audit_service.record(
            db,
            request,
            module='骑手管理',
            action='重置骑手密码',
            target_type='rider',
            target_id=pk,
            target_label=f'{rider.job_no} {rider.name}',
            reason=obj.reason,
        )

    @staticmethod
    async def disable_account(*, db: AsyncSession, request: Request, pk: int, obj: DisableRiderAccountParam) -> None:
        """停用骑手账号"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if not rider.user_id:
            raise errors.NotFoundError(msg='该骑手尚未开通账号')
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
            after={'user_id': rider.user_id, 'status': 0},
        )

    @staticmethod
    async def enable_account(*, db: AsyncSession, request: Request, pk: int, obj: EnableRiderAccountParam) -> None:
        """启用骑手账号"""
        rider = await RiderService._get_visible_rider(db=db, request=request, pk=pk)
        if not rider.user_id:
            raise errors.NotFoundError(msg='该骑手尚未开通账号')
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
            after={'user_id': rider.user_id, 'status': 1},
        )


rider_service: RiderService = RiderService()
