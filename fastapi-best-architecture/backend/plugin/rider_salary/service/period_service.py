from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import BackgroundTasks, Request
from sqlalchemy import and_, case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.database.db import async_db_session
from backend.plugin.rider_salary.crud.payroll import payroll_dao
from backend.plugin.rider_salary.crud.settle_period import SITE_LEVEL_RIDER_ID, settle_period_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.enums import CycleType, PayrollKind, PayrollStatus, PeriodStatus
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.schema.period import (
    CalculatePeriodParam,
    CalculatePeriodResult,
    GeneratePeriodParam,
    GeneratePeriodResult,
    GetGeneratedPeriodItem,
    GetPeriodDetail,
    GetPeriodForDateResult,
    GetPeriodListItem,
    GetPeriodPayrollItem,
    GetPeriodWithPayrolls,
    ReversePeriodResult,
)
from backend.plugin.rider_salary.service.audit_service import audit_service, snapshot
from backend.plugin.rider_salary.service.calc_service import _riders_for_period, calculate_period
from backend.plugin.rider_salary.service.payroll_service import payroll_service
from backend.plugin.rider_salary.utils.audit import require_reason
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.periods import compute_period_range
from backend.plugin.rider_salary.utils.recalc import mark_stale
from backend.utils.timezone import timezone

CALC_SYNC_LIMIT = 200
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


def stale_lock_message(job_nos: list[str]) -> str:
    """锁账 stale 前置错误文案"""
    return f'存在需重算的薪资结果：工号 {"、".join(job_nos)}，请先重算'


def uncovered_runs(start_date: date, end_date: date, covered: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """区间内未被任何已有区间覆盖的连续日期段"""
    taken: set[date] = set()
    for row_start, row_end in covered:
        current = max(row_start, start_date)
        while current <= min(row_end, end_date):
            taken.add(current)
            current += timedelta(days=1)
    runs: list[tuple[date, date]] = []
    run_start: date | None = None
    current = start_date
    while current <= end_date:
        if current in taken:
            if run_start is not None:
                runs.append((run_start, current - timedelta(days=1)))
                run_start = None
        elif run_start is None:
            run_start = current
        current += timedelta(days=1)
    if run_start is not None:
        runs.append((run_start, end_date))
    return runs


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


def _cycle_value(cycle_type: CycleType | str | None, fallback: str) -> str:
    if cycle_type is None:
        return fallback
    if isinstance(cycle_type, CycleType):
        return cycle_type.value
    return str(cycle_type)


async def _calculate_period_background(*, period_id: int, rider_ids: list[int] | None) -> None:
    """后台算薪（独立事务）"""
    async with async_db_session.begin() as db:
        await calculate_period(db, period_id=period_id, rider_ids=rider_ids, operator=None)


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
        created = await self._create_runs(
            db,
            site_id=site_id,
            rider_id=period_rider_id,
            cycle_type=cycle_type,
            start_date=start,
            end_date=end,
        )
        for period, _ in created:
            if period.start_date <= any_date <= period.end_date:
                return period
        # 骑手级口径下该日已由站点级周期结算完毕，沿用站点级周期
        settled = await settle_period_dao.get_covering(
            db, site_id=site_id, rider_id=SITE_LEVEL_RIDER_ID, any_date=any_date
        )
        if settled is None:
            raise errors.RequestError(msg='无法确定该日期所属结算周期')
        return settled

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
    ) -> RiderSalarySettlePeriod:
        existing = await settle_period_dao.get_by_unique(db, site_id=site_id, rider_id=rider_id, start_date=start_date)
        if existing is not None:
            return existing
        try:
            async with db.begin_nested():
                return await settle_period_dao.create(
                    db,
                    site_id=site_id,
                    rider_id=rider_id,
                    cycle_type=cycle_type,
                    start_date=start_date,
                    end_date=end_date,
                )
        except IntegrityError:
            existed = await settle_period_dao.get_by_unique(
                db, site_id=site_id, rider_id=rider_id, start_date=start_date
            )
            if existed is None:
                raise
            return existed

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
        now = timezone.now()
        user_id = _operator_id(operator)
        period.status = target_status
        if target_status == PeriodStatus.locked.value:
            period.locked_by = user_id
            period.locked_time = now
        elif target_status == PeriodStatus.paid.value:
            period.paid_by = user_id
            period.paid_time = now
        elif target_status == PeriodStatus.reopened.value:
            period.reopened_by = user_id
            period.reopened_time = now
        return action

    async def get_list(
        self,
        *,
        db: AsyncSession,
        request: Request,
        site_id: int | None,
        rider_id: int | None,
        status: str | None,
        month: str | None,
        cycle_type: str | None = None,
        has_stale: bool | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """
        分页周期列表

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID
        :param rider_id: 骑手 ID
        :param status: 状态
        :param month: 年月 YYYY-MM
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
            cycle_type=cycle_type,
            has_stale=has_stale,
            range_from=date_from,
            range_to=date_to,
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
        items: list[GetGeneratedPeriodItem] = []
        site_ranges = covering_period_ranges(site.settle_cycle, site.cycle_config, year, month)
        for start, end in site_ranges:
            listed = await self._ensure_listed(
                db,
                site_id=site.id,
                rider_id=SITE_LEVEL_RIDER_ID,
                cycle_type=_cycle_value(site.settle_cycle, CycleType.month.value),
                start_date=start,
                end_date=end,
            )
            items.extend(listed)
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
            rider_ranges = covering_period_ranges(
                rider.settle_cycle_override,
                rider.cycle_config_override,
                year,
                month,
            )
            for start, end in rider_ranges:
                listed = await self._ensure_listed(
                    db,
                    site_id=site.id,
                    rider_id=rider.id,
                    cycle_type=_cycle_value(rider.settle_cycle_override, site.settle_cycle),
                    start_date=start,
                    end_date=end,
                )
                items.extend(listed)
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
            after={'created': created_count, 'skipped': skipped_count},
            description=(
                f'{_operator_name(request)} 于 {_now_str()} 对 站点{site.name} {obj.month} 执行了生成周期，'
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

    async def _ensure_listed(
        self,
        db: AsyncSession,
        *,
        site_id: int,
        rider_id: int,
        cycle_type: str,
        start_date: date,
        end_date: date,
    ) -> list[GetGeneratedPeriodItem]:
        rows = await self._create_runs(
            db,
            site_id=site_id,
            rider_id=rider_id,
            cycle_type=cycle_type,
            start_date=start_date,
            end_date=end_date,
        )
        return [
            GetGeneratedPeriodItem(
                id=period.id,
                site_id=period.site_id,
                rider_id=period.rider_id,
                cycle_type=period.cycle_type,
                start_date=period.start_date,
                end_date=period.end_date,
                status=period.status,
                created=created,
            )
            for period, created in rows
        ]

    async def _create_runs(
        self,
        db: AsyncSession,
        *,
        site_id: int,
        rider_id: int,
        cycle_type: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[RiderSalarySettlePeriod, bool]]:
        """
        只为区间内尚未被覆盖的日期建周期，保证同一口径的周期互不重叠

        改周期配置后，新配置自然从最后一个已有周期的次日起生效（纲要 §10 #35）。
        骑手级还要让出站点级已定稿/已发薪的日期，否则同一天会结算两次。
        """
        existing = list(
            (
                await db.scalars(
                    select(RiderSalarySettlePeriod)
                    .where(
                        RiderSalarySettlePeriod.site_id == site_id,
                        RiderSalarySettlePeriod.rider_id == rider_id,
                        RiderSalarySettlePeriod.start_date <= end_date,
                        RiderSalarySettlePeriod.end_date >= start_date,
                        RiderSalarySettlePeriod.deleted == 0,
                    )
                    .order_by(RiderSalarySettlePeriod.start_date)
                )
            ).all()
        )
        blocked = list(existing)
        if rider_id != SITE_LEVEL_RIDER_ID:
            settled_period_ids = select(RiderSalaryPayroll.period_id).where(
                RiderSalaryPayroll.rider_id == rider_id,
                RiderSalaryPayroll.status.in_([PayrollStatus.finalized.value, PayrollStatus.paid.value]),
                RiderSalaryPayroll.kind != PayrollKind.reversal.value,
                RiderSalaryPayroll.reversed.is_(False),
                RiderSalaryPayroll.deleted == 0,
            )
            blocked.extend(
                (
                    await db.scalars(
                        select(RiderSalarySettlePeriod).where(
                            RiderSalarySettlePeriod.site_id == site_id,
                            RiderSalarySettlePeriod.rider_id == SITE_LEVEL_RIDER_ID,
                            RiderSalarySettlePeriod.start_date <= end_date,
                            RiderSalarySettlePeriod.end_date >= start_date,
                            RiderSalarySettlePeriod.deleted == 0,
                            RiderSalarySettlePeriod.id.in_(settled_period_ids),
                        )
                    )
                ).all()
            )
        runs = uncovered_runs(start_date, end_date, [(row.start_date, row.end_date) for row in blocked])
        result: list[tuple[RiderSalarySettlePeriod, bool]] = [(row, False) for row in existing]
        for run_from, run_to in runs:
            period = await self._create_if_absent(
                db,
                site_id=site_id,
                rider_id=rider_id,
                cycle_type=cycle_type,
                start_date=run_from,
                end_date=run_to,
            )
            result.append((period, True))
            if rider_id != SITE_LEVEL_RIDER_ID:
                # 站点级草稿里这几天改由骑手级周期结算，站点级需重算
                await mark_stale(db, rider_ids=[rider_id], date_from=run_from, date_to=run_to)
        result.sort(key=lambda item: item[0].start_date)
        return result

    async def calculate(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        obj: CalculatePeriodParam,
        background_tasks: BackgroundTasks,
    ) -> CalculatePeriodResult:
        """
        触发周期算薪

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :param obj: 参数
        :param background_tasks: 后台任务
        :return:
        """
        period, site, _rider = await self._load_visible(db, request, pk)
        if period.status not in {PeriodStatus.open.value, PeriodStatus.reopened.value}:
            raise errors.RequestError(msg=f'结算周期当前状态为{status_label(period.status)}，不允许执行算薪')
        targets = await _riders_for_period(db, period, obj.rider_ids)
        warnings: list[str] = []
        if len(targets) > CALC_SYNC_LIMIT:
            background_tasks.add_task(
                _calculate_period_background,
                period_id=period.id,
                rider_ids=obj.rider_ids,
            )
            warnings.append(f'骑手数超过 {CALC_SYNC_LIMIT}，已转入后台计算')
            await audit_service.record(
                db,
                request,
                module='结算周期',
                action='算薪',
                target_type='period',
                target_id=period.id,
                target_label=_period_label(site, period),
                description=(
                    f'{_operator_name(request)} 于 {_now_str()} 对 {_period_label(site, period)} 执行了算薪，'
                    f'骑手{len(targets)}人已转入后台'
                ),
            )
            return CalculatePeriodResult(calculated=0, warnings=warnings, queued=True)
        results = await calculate_period(db, period_id=period.id, rider_ids=obj.rider_ids, operator=request)
        for result in results:
            warnings.extend(result.warnings or [])
        await audit_service.record(
            db,
            request,
            module='结算周期',
            action='算薪',
            target_type='period',
            target_id=period.id,
            target_label=_period_label(site, period),
            description=(
                f'{_operator_name(request)} 于 {_now_str()} 对 {_period_label(site, period)} 执行了算薪，'
                f'骑手{len(results)}人'
            ),
        )
        return CalculatePeriodResult(calculated=len(results), warnings=warnings, queued=False)

    async def lock(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        reason: str,
    ) -> None:
        """
        锁账

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :param reason: 原因
        :return:
        """
        period, site, _rider = await self._load_visible(db, request, pk)
        await self._assert_no_stale_drafts(db, period)
        await self._assert_all_calculated(db, period)
        before = snapshot(period, _PERIOD_FIELDS)
        self.transition(period, PeriodStatus.locked.value, request, reason)
        await self._set_locked_flags(db, period, locked=True)
        finalized_riders = list(
            (
                await db.scalars(
                    select(RiderSalaryPayroll.rider_id).where(
                        RiderSalaryPayroll.period_id == period.id,
                        RiderSalaryPayroll.status == PayrollStatus.draft.value,
                        RiderSalaryPayroll.deleted == 0,
                    )
                )
            ).all()
        )
        await db.execute(
            update(RiderSalaryPayroll)
            .where(
                RiderSalaryPayroll.period_id == period.id,
                RiderSalaryPayroll.status == PayrollStatus.draft.value,
                RiderSalaryPayroll.deleted == 0,
            )
            .values(status=PayrollStatus.finalized.value)
        )
        # 本期欠款结转与预支抵扣已定稿，之后周期的草稿需按最新结果重算（纲要 §10 #32/#33）
        for rider_id in set(finalized_riders):
            await payroll_service.release_later_drafts(db, rider_id=rider_id, after=period.start_date)
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
    ) -> None:
        """
        标记发薪（不涉及实际打款）

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :param reason: 原因
        :return:
        """
        period, site, _rider = await self._load_visible(db, request, pk)
        before = snapshot(period, _PERIOD_FIELDS)
        self.transition(period, PeriodStatus.paid.value, request, reason)
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
        desc = (
            f'{_operator_name(request)} 于 {_now_str()} 对 {_period_label(site, period)} 执行了标记发薪，'
            f'已标记发薪，不涉及实际打款'
        )
        if reason and reason.strip():
            desc = f'{desc}，原因：{reason.strip()}'
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

    async def reverse(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        reason: str,
    ) -> ReversePeriodResult:
        """
        反冲补发：生成反冲单并解除锁账

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :param reason: 原因
        :return:
        """
        period, site, _rider = await self._load_visible(db, request, pk)
        before = snapshot(period, _PERIOD_FIELDS)
        self.transition(period, PeriodStatus.reopened.value, request, reason)
        payrolls = list(await payroll_dao.select_models(db, period_id=period.id, deleted=0))
        targets = reversible_payrolls(payrolls)
        reversal_net = ZERO
        for payroll in targets:
            reversal = await payroll_service.create_reversal(db, payroll, request, reason)
            reversal_net += q2(reversal.net)
        await self._set_locked_flags(db, period, locked=False)
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
        )

    async def _assert_no_stale_drafts(self, db: AsyncSession, period: RiderSalarySettlePeriod) -> None:
        rows = list(
            (
                await db.scalars(
                    select(RiderSalaryPayroll).where(
                        RiderSalaryPayroll.period_id == period.id,
                        RiderSalaryPayroll.status == PayrollStatus.draft.value,
                        RiderSalaryPayroll.stale.is_(True),
                        RiderSalaryPayroll.deleted == 0,
                    )
                )
            ).all()
        )
        if not rows:
            return
        rider_ids = [row.rider_id for row in rows]
        rider_map = await self._rider_map(db, rider_ids)
        job_nos: list[str] = []
        seen: set[str] = set()
        for row in rows:
            rider = rider_map.get(row.rider_id)
            job_no = rider.job_no if rider is not None else str(row.rider_id)
            if job_no not in seen:
                seen.add(job_no)
                job_nos.append(job_no)
        raise errors.RequestError(msg=stale_lock_message(job_nos))

    async def _assert_all_calculated(self, db: AsyncSession, period: RiderSalarySettlePeriod) -> None:
        """锁账前确认本期应结算的骑手都有有效薪资单，避免新导入/新增骑手从未算薪就被锁账漏发"""
        targets = await _riders_for_period(db, period, None)
        if not targets:
            return
        calculated = set(
            (
                await db.scalars(
                    select(RiderSalaryPayroll.rider_id).where(
                        RiderSalaryPayroll.period_id == period.id,
                        RiderSalaryPayroll.rider_id.in_(targets),
                        RiderSalaryPayroll.kind != PayrollKind.reversal.value,
                        RiderSalaryPayroll.status != PayrollStatus.voided.value,
                        RiderSalaryPayroll.reversed.is_(False),
                        RiderSalaryPayroll.deleted == 0,
                    )
                )
            ).all()
        )
        missing = [rider_id for rider_id in targets if rider_id not in calculated]
        if not missing:
            return
        rider_map = await self._rider_map(db, missing)
        job_nos = [rider_map[rid].job_no if rid in rider_map else str(rid) for rid in missing]
        shown = '、'.join(job_nos[:10]) + (f' 等{len(job_nos)}人' if len(job_nos) > 10 else '')
        raise errors.RequestError(msg=f'以下骑手本期尚未算薪，请先算薪再锁账：{shown}')

    async def _set_locked_flags(self, db: AsyncSession, period: RiderSalarySettlePeriod, *, locked: bool) -> None:
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
            # 只让出骑手级周期覆盖的「骑手 × 日期」，其余日期仍随站点级周期锁定/解锁
            for row in overlapping:
                order_stmt = order_stmt.where(
                    ~and_(
                        RiderSalaryOrder.rider_id == row.rider_id,
                        RiderSalaryOrder.biz_date >= row.start_date,
                        RiderSalaryOrder.biz_date <= row.end_date,
                    )
                )
                adj_stmt = adj_stmt.where(
                    ~and_(
                        RiderSalaryAdjustment.rider_id == row.rider_id,
                        RiderSalaryAdjustment.biz_date >= row.start_date,
                        RiderSalaryAdjustment.biz_date <= row.end_date,
                    )
                )
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
        agg_rows = (
            await db.execute(
                select(
                    RiderSalaryPayroll.period_id,
                    func.count(RiderSalaryPayroll.id),
                    func.count(func.distinct(RiderSalaryPayroll.rider_id)),
                    func.coalesce(func.sum(case((RiderSalaryPayroll.stale.is_(True), 1), else_=0)), 0),
                    func.coalesce(func.sum(RiderSalaryPayroll.gross), 0),
                    func.coalesce(func.sum(RiderSalaryPayroll.net), 0),
                )
                .where(
                    RiderSalaryPayroll.period_id.in_(period_ids),
                    RiderSalaryPayroll.deleted == 0,
                )
                .group_by(RiderSalaryPayroll.period_id)
            )
        ).all()
        kind_rows = (
            await db.execute(
                select(
                    RiderSalaryPayroll.period_id,
                    RiderSalaryPayroll.kind,
                    func.count(RiderSalaryPayroll.id),
                )
                .where(
                    RiderSalaryPayroll.period_id.in_(period_ids),
                    RiderSalaryPayroll.deleted == 0,
                )
                .group_by(RiderSalaryPayroll.period_id, RiderSalaryPayroll.kind)
            )
        ).all()
        result: dict[int, dict[str, Any]] = {}
        for period_id, payroll_count, rider_count, stale_count, gross_total, net_total in agg_rows:
            result[int(period_id)] = {
                'rider_count': int(rider_count or 0),
                'payroll_count': int(payroll_count or 0),
                'stale_count': int(stale_count or 0),
                'gross_total': q2(gross_total or ZERO),
                'net_total': q2(net_total or ZERO),
                'kind_counts': empty_kind_counts(),
            }
        for period_id, kind, count in kind_rows:
            stats = result.setdefault(int(period_id), self._empty_stats())
            stats['kind_counts'][str(kind)] = int(count or 0)
        return result

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
