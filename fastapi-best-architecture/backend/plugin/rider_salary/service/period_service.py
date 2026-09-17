from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import BackgroundTasks, Request
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.database.db import async_db_session
from backend.plugin.rider_salary.crud.payroll import payroll_dao
from backend.plugin.rider_salary.crud.settle_period import SITE_LEVEL_RIDER_ID, settle_period_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.engine.context import iter_dates
from backend.plugin.rider_salary.enums import CycleType, PayrollKind, PayrollStatus, PeriodStatus, RecalcJobStatus
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.import_batch import RiderSalaryImportBatch
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.schema.period import (
    CalcPrecheckBlocker,
    CalcPrecheckDeeplink,
    CalcPrecheckResult,
    CalcPrecheckWarning,
    CalculatePeriodParam,
    CalculatePeriodResult,
    CalculateRiderFailure,
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
from backend.plugin.rider_salary.service.calc_service import (
    _is_completed,
    _riders_for_period,
    calculate_period,
    collect_hard_fail_findings,
    collect_never_calculated_finding,
    load_calc_input_for_precheck,
    lock_hard_fail_message,
    missing_delivery_order_query,
    persist_last_calc_status,
)
from backend.plugin.rider_salary.service.payroll_service import payroll_service
from backend.plugin.rider_salary.utils.audit import require_reason, resolve_operator_name
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.order_attention import count_period_attention_orders
from backend.plugin.rider_salary.utils.periods import compute_period_range
from backend.utils.timezone import timezone

CALC_SYNC_LIMIT = 200
ZERO = Decimal('0.00')


def calc_sync_limit() -> int:
    """同步算薪骑手上限；超出转入后台。CDP 可通过 plugin 配置压低。"""
    from backend.core.conf import settings

    raw = getattr(settings, 'RIDER_SALARY_CALC_SYNC_LIMIT', CALC_SYNC_LIMIT)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = CALC_SYNC_LIMIT
    return value if value >= 0 else CALC_SYNC_LIMIT


def should_queue_calculate(target_count: int, *, limit: int | None = None) -> bool:
    """骑手数严格大于上限才排队（等于上限仍同步）。"""
    cap = calc_sync_limit() if limit is None else int(limit)
    return int(target_count) > cap


def calc_status_label(status: str | None) -> str | None:
    """算薪态中文。"""
    if not status:
        return None
    try:
        return RecalcJobStatus(status).label
    except ValueError:
        return status


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


def compose_lock_block_message(*, hard_fail_errors: list[str], stale_job_nos: list[str]) -> str | None:
    """
    锁账拦截文案：硬失败（无方案有单 / 缺送达 / 从未落库）优先于 stale「请先重算」。
    禁止只用 stale 句结束；禁止「仍要锁」。无完成单的无方案日不产生硬失败。
    """
    if hard_fail_errors:
        msg = lock_hard_fail_message(hard_fail_errors)
        if stale_job_nos:
            msg = f'{msg}。{stale_lock_message(stale_job_nos)}'
        return msg
    if stale_job_nos:
        return stale_lock_message(stale_job_nos)
    return None


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


def _now_str() -> str:
    return timezone.to_str(timezone.now())


_operator_name = resolve_operator_name


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
    """后台算薪（独立事务，非 Celery）。先落「计算中」，再写完成/部分失败。"""
    from backend.common.log import log

    try:
        async with async_db_session.begin() as db:
            period = await db.get(RiderSalarySettlePeriod, period_id)
            if period is not None and not getattr(period, 'deleted', 0):
                persist_last_calc_status(period, status=RecalcJobStatus.running.value, message='计算中')
                await db.flush()
        async with async_db_session.begin() as db:
            await calculate_period(db, period_id=period_id, rider_ids=rider_ids, operator=None)
    except Exception as exc:
        log.exception('周期后台算薪失败 period_id=%s', period_id)
        try:
            async with async_db_session.begin() as db:
                period = await db.get(RiderSalarySettlePeriod, period_id)
                if period is not None and not getattr(period, 'deleted', 0):
                    persist_last_calc_status(
                        period,
                        status=RecalcJobStatus.failed.value,
                        message=f'失败：{exc}',
                    )
        except Exception:
            log.exception('回写周期算薪失败态异常 period_id=%s', period_id)


def import_gap_deeplink(site_id: int, gap_days: list[date]) -> CalcPrecheckDeeplink:
    """导入缺口落到带日期窗的订单列表，禁止空日历。"""
    return CalcPrecheckDeeplink(
        path='/rider-salary/order',
        query={
            'site_id': str(site_id),
            'date_from': gap_days[0].isoformat(),
            'date_to': gap_days[-1].isoformat(),
        },
    )


def _blocker_deeplink(code: str, *, rider_id: int, period: RiderSalarySettlePeriod) -> CalcPrecheckDeeplink | None:
    if code == 'no_plan_with_orders':
        return CalcPrecheckDeeplink(path=f'/rider-salary/rider/{rider_id}', query={'tab': 'binding'})
    if code == 'missing_delivery':
        return CalcPrecheckDeeplink(
            path='/rider-salary/order',
            query=missing_delivery_order_query(
                rider_id=rider_id,
                site_id=period.site_id,
                date_from=period.start_date,
                date_to=period.end_date,
            ),
        )
    return None


async def _collect_rider_blockers(
    db: AsyncSession,
    period: RiderSalarySettlePeriod,
    targets: list[int],
) -> list[CalcPrecheckBlocker]:
    blockers: list[CalcPrecheckBlocker] = []
    for rider_id in targets:
        rider_row = await db.scalar(
            select(RiderSalaryRider).where(RiderSalaryRider.id == rider_id, RiderSalaryRider.deleted == 0)
        )
        if rider_row is None:
            continue
        calc_input = await load_calc_input_for_precheck(db, rider=rider_row, period=period)
        for code, messages in collect_hard_fail_findings(calc_input):
            blockers.append(
                CalcPrecheckBlocker(
                    code=code,
                    rider_id=rider_id,
                    job_no=rider_row.job_no,
                    rider_name=rider_row.name,
                    messages=list(messages),
                    deeplink=_blocker_deeplink(code, rider_id=rider_id, period=period),
                )
            )
    return blockers


async def _collect_precheck_warnings(
    db: AsyncSession,
    *,
    period: RiderSalarySettlePeriod,
    rider: RiderSalaryRider | None,
    can_run: bool,
    stale_count: int,
) -> list[CalcPrecheckWarning]:
    warnings: list[CalcPrecheckWarning] = []
    if not can_run:
        warnings.append(
            CalcPrecheckWarning(
                code='period_not_open',
                messages=[f'结算周期当前状态为{status_label(period.status)}，不允许执行算薪'],
                deeplink=CalcPrecheckDeeplink(path='/rider-salary/period', query={'id': str(period.id)}),
            )
        )
    if stale_count > 0:
        warnings.append(
            CalcPrecheckWarning(
                code='stale_payrolls',
                messages=[f'本周期有 {stale_count} 张薪资单需重算，建议重新算薪'],
                deeplink=None,
            )
        )
    if period.rider_id and period.rider_id != SITE_LEVEL_RIDER_ID:
        label = ' '.join(filter(None, [getattr(rider, 'job_no', None), getattr(rider, 'name', None)])) or str(
            period.rider_id
        )
        warnings.append(
            CalcPrecheckWarning(
                code='personal_period',
                messages=[f'个性化周期仅计算骑手 {label}，不会写入站点级结果'],
                deeplink=None,
            )
        )
    today = timezone.now().date()
    gap_end = min(period.end_date, today - timedelta(days=1))
    if gap_end < period.start_date:
        return warnings
    batches = list(
        (
            await db.scalars(
                select(RiderSalaryImportBatch).where(
                    RiderSalaryImportBatch.site_id == period.site_id,
                    RiderSalaryImportBatch.deleted == 0,
                )
            )
        ).all()
    )
    covered: set[date] = set()
    for batch in batches:
        if batch.date_from is None or batch.date_to is None:
            continue
        covered.update(iter_dates(max(batch.date_from, period.start_date), min(batch.date_to, gap_end)))
    order_dates = set(
        (
            await db.scalars(
                select(RiderSalaryOrder.biz_date).where(
                    RiderSalaryOrder.site_id == period.site_id,
                    RiderSalaryOrder.biz_date >= period.start_date,
                    RiderSalaryOrder.biz_date <= gap_end,
                    RiderSalaryOrder.deleted == 0,
                )
            )
        ).all()
    )
    gap_days = [day for day in iter_dates(period.start_date, gap_end) if day not in covered and day not in order_dates]
    if gap_days:
        sample = '、'.join(d.isoformat() for d in gap_days[:5])
        more = f' 等共 {len(gap_days)} 天' if len(gap_days) > 5 else f'（共 {len(gap_days)} 天）'
        warnings.append(
            CalcPrecheckWarning(
                code='import_gap',
                messages=[f'周期内存在导入缺口日：{sample}{more}'],
                deeplink=import_gap_deeplink(period.site_id, gap_days),
            )
        )
    return warnings


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
        stale: bool | None = None,
    ) -> dict[str, Any]:
        """
        分页周期列表

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID
        :param rider_id: 骑手 ID
        :param status: 状态
        :param month: 年月 YYYY-MM
        :param stale: 仅需重算周期
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
        result.last_calc_failures = [
            CalculateRiderFailure.model_validate(row) for row in (period.last_calc_failures or [])
        ]
        result.last_calc_status = period.last_calc_status
        result.last_calc_status_message = period.last_calc_status_message
        result.attention_order_count = await count_period_attention_orders(db, period)
        return result

    async def calc_precheck(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
    ) -> CalcPrecheckResult:
        """
        算前只读预检：周期级 can_run + 骑手硬风险 + 警告（不写 payroll）。

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :return:
        """
        period, _site, rider = await self._load_visible(db, request, pk)
        can_run = period.status in {PeriodStatus.open.value, PeriodStatus.reopened.value}
        targets = await _riders_for_period(db, period, None)
        stats = (await self._payroll_stats(db, [period.id])).get(period.id, self._empty_stats())
        stale_count = int(stats.get('stale_count') or 0)
        blockers = await _collect_rider_blockers(db, period, targets)
        warnings = await _collect_precheck_warnings(
            db,
            period=period,
            rider=rider,
            can_run=can_run,
            stale_count=stale_count,
        )
        return CalcPrecheckResult(
            period_id=period.id,
            can_run=can_run,
            blockers=blockers,
            warnings=warnings,
            eligible_rider_count=len(targets),
            stale_count=stale_count,
            calc_status=period.last_calc_status,
            calc_status_label=calc_status_label(period.last_calc_status),
            calc_status_message=period.last_calc_status_message,
            sync_limit=calc_sync_limit(),
            attention_order_count=await count_period_attention_orders(db, period),
        )

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
            item = await self._ensure_listed(
                db,
                site_id=site.id,
                rider_id=SITE_LEVEL_RIDER_ID,
                cycle_type=_cycle_value(site.settle_cycle, CycleType.month.value),
                start_date=start,
                end_date=end,
            )
            items.append(item)
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
                item = await self._ensure_listed(
                    db,
                    site_id=site.id,
                    rider_id=rider.id,
                    cycle_type=_cycle_value(rider.settle_cycle_override, site.settle_cycle),
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
    ) -> GetGeneratedPeriodItem:
        before = await settle_period_dao.get_by_unique(db, site_id=site_id, rider_id=rider_id, start_date=start_date)
        period = await self._create_if_absent(
            db,
            site_id=site_id,
            rider_id=rider_id,
            cycle_type=cycle_type,
            start_date=start_date,
            end_date=end_date,
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
        limit = calc_sync_limit()
        if should_queue_calculate(len(targets), limit=limit):
            persist_last_calc_status(
                period,
                status=RecalcJobStatus.queued.value,
                message=f'排队中：骑手{len(targets)}人已转入后台计算',
            )
            await db.flush()
            background_tasks.add_task(
                _calculate_period_background,
                period_id=period.id,
                rider_ids=obj.rider_ids,
            )
            warnings.append(f'骑手数超过 {limit}，已转入后台计算')
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
            return CalculatePeriodResult(
                calculated=0,
                warnings=warnings,
                queued=True,
                calc_status=RecalcJobStatus.queued.value,
                calc_status_label=RecalcJobStatus.queued.label,
                sync_limit=limit,
                target_rider_count=len(targets),
            )
        results, failed_rows = await calculate_period(
            db, period_id=period.id, rider_ids=obj.rider_ids, operator=request
        )
        for result in results:
            warnings.extend(result.warnings or [])
        failed = [
            CalculateRiderFailure(
                rider_id=int(row['rider_id']),
                job_no=row.get('job_no'),
                errors=list(row.get('errors') or []),
            )
            for row in failed_rows
        ]
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
                f'成功{len(results)}人，失败{len(failed)}人'
            ),
        )
        status = period.last_calc_status
        return CalculatePeriodResult(
            calculated=len(results),
            warnings=warnings,
            failed=failed,
            queued=False,
            calc_status=status,
            calc_status_label=calc_status_label(status),
            sync_limit=limit,
            target_rider_count=len(targets),
        )

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
        await self._assert_lock_ready(db, period)
        before = snapshot(period, _PERIOD_FIELDS)
        self.transition(period, PeriodStatus.locked.value, request, reason)
        await self._set_locked_flags(db, period, locked=True)
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

    async def _assert_lock_ready(self, db: AsyncSession, period: RiderSalarySettlePeriod) -> None:
        """硬失败优先于 stale；无完成单的无方案日不挡锁。无「仍要锁」。"""
        hard_errors = await self._collect_lock_hard_fail_errors(db, period)
        stale_job_nos = await self._collect_stale_draft_job_nos(db, period)
        msg = compose_lock_block_message(hard_fail_errors=hard_errors, stale_job_nos=stale_job_nos)
        if msg:
            raise errors.RequestError(msg=msg, data={'errors': hard_errors} if hard_errors else None)

    async def _collect_stale_draft_job_nos(self, db: AsyncSession, period: RiderSalarySettlePeriod) -> list[str]:
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
            return []
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
        return job_nos

    async def _collect_lock_hard_fail_errors(self, db: AsyncSession, period: RiderSalarySettlePeriod) -> list[str]:
        """锁账硬拦扫描：有完成单无方案 / 缺送达 / 有单从未成功落库。"""
        targets = await _riders_for_period(db, period, None)
        if not targets:
            return []
        success_ids = set(
            (
                await db.scalars(
                    select(RiderSalaryPayroll.rider_id).where(
                        RiderSalaryPayroll.period_id == period.id,
                        RiderSalaryPayroll.deleted == 0,
                        RiderSalaryPayroll.kind != PayrollKind.reversal.value,
                    )
                )
            ).all()
        )
        errors_list: list[str] = []
        for rider_id in targets:
            rider_row = await db.scalar(
                select(RiderSalaryRider).where(RiderSalaryRider.id == rider_id, RiderSalaryRider.deleted == 0)
            )
            if rider_row is None:
                continue
            calc_input = await load_calc_input_for_precheck(db, rider=rider_row, period=period)
            findings = collect_hard_fail_findings(calc_input)
            for _code, messages in findings:
                errors_list.extend(messages)
            completed = [
                row
                for row in calc_input.orders
                if _is_completed(row)
                and not (calc_input.leave_date is not None and row.biz_date > calc_input.leave_date)
            ]
            extra = collect_never_calculated_finding(
                job_no=rider_row.job_no,
                completed_orders=completed,
                has_success_payroll=rider_id in success_ids,
                already_hard_failed=bool(findings),
            )
            if extra is not None:
                errors_list.extend(extra[1])
        return errors_list

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
