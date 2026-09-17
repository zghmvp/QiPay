from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.admin.model import User
from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.core.conf import settings
from backend.plugin.rider_salary.crud.advance import advance_dao
from backend.plugin.rider_salary.crud.rider import rider_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.enums import AdvanceStatus, DeductStatus, RiderStatus
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.model.audit_log import RiderSalaryAuditLog
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.schema.advance import (
    AdvanceActionParam,
    AdvanceReasonParam,
    CreateMeAdvanceParam,
    GetAdvanceDetail,
    GetAdvanceMonthlyQuota,
)
from backend.plugin.rider_salary.service.audit_service import audit_service, snapshot
from backend.plugin.rider_salary.utils.audit import require_reason, resolve_operator_name
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.excel import write_workbook
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.recalc import mark_stale
from backend.utils.timezone import timezone

ZERO = Decimal('0.00')
IN_FLIGHT_STATUSES = frozenset({AdvanceStatus.pending.value, AdvanceStatus.to_pay.value})
QUOTA_CONSUMING_STATUSES = frozenset({
    AdvanceStatus.pending.value,
    AdvanceStatus.to_pay.value,
    AdvanceStatus.paid.value,
})
DEFAULT_MONTHLY_ADVANCE_LIMIT = 1
SHANGHAI_TZ = ZoneInfo('Asia/Shanghai')
MSG_QUOTA_EXHAUSTED = '本月预支次数已用完'
MSG_SITE_ADVANCE_BANNED = '本站暂不可预支'
_ALLOWED: frozenset[tuple[str, str]] = frozenset({
    (AdvanceStatus.draft.value, AdvanceStatus.pending.value),
    (AdvanceStatus.draft.value, AdvanceStatus.cancelled.value),
    (AdvanceStatus.pending.value, AdvanceStatus.to_pay.value),
    (AdvanceStatus.pending.value, AdvanceStatus.rejected.value),
    (AdvanceStatus.pending.value, AdvanceStatus.cancelled.value),
    (AdvanceStatus.to_pay.value, AdvanceStatus.paid.value),
    (AdvanceStatus.to_pay.value, AdvanceStatus.cancelled.value),
})
_TARGET_ACTION = {
    AdvanceStatus.pending.value: '提交',
    AdvanceStatus.to_pay.value: '审核通过',
    AdvanceStatus.rejected.value: '驳回',
    AdvanceStatus.paid.value: '标记已发放',
    AdvanceStatus.cancelled.value: '取消',
}
_ADVANCE_FIELDS = (
    'id',
    'rider_id',
    'site_id',
    'amount',
    'reason',
    'status',
    'approver_id',
    'approve_time',
    'approve_remark',
    'paid_by',
    'paid_time',
    'deducted_amount',
    'remaining_amount',
    'deduct_status',
    'submit_time',
    'cancel_time',
)
_EXPORT_HEADERS = [
    '工号',
    '姓名',
    '站点',
    '金额',
    '原因',
    '状态',
    '申请时间',
    '审核人',
    '审核时间',
    '发放时间',
    '已抵扣',
    '待抵扣',
]


def _status_label(status: str) -> str:
    try:
        return AdvanceStatus(status).label
    except ValueError:
        return status


def _operator_id(operator: Any) -> int:
    user = getattr(operator, 'user', None)
    if user is not None:
        return int(getattr(user, 'id', 0) or 0)
    return int(getattr(operator, 'id', 0) or 0)


def resolve_advance_limit(
    rider_limit: Decimal | None,
    site_limit: Decimal | None,
    default: Decimal | int | None = None,
) -> Decimal:
    """
    预支上限：骑手 > 站点 > 全局默认

    :param rider_limit: 骑手级上限
    :param site_limit: 站点级上限
    :param default: 全局默认
    :return:
    """
    if default is None:
        default = getattr(settings, 'RIDER_SALARY_ADVANCE_LIMIT_DEFAULT', 3000)
    if rider_limit is not None:
        return q2(rider_limit)
    if site_limit is not None:
        return q2(site_limit)
    return q2(default)


def assert_no_in_flight(count: int) -> None:
    """同一骑手同时最多一笔 pending/to_pay"""
    if count > 0:
        raise errors.RequestError(msg='您已有一笔待审核或待发放的预支，请等待处理完成后再申请')


def assert_advance_amount(amount: Decimal, limit: Decimal) -> Decimal:
    """校验金额为正且不超过上限"""
    value = q2(amount)
    if value <= 0:
        raise errors.RequestError(msg='预支金额必须大于 0')
    cap = q2(limit)
    if value > cap:
        raise errors.RequestError(msg=f'预支金额不能超过上限 {cap} 元')
    return value


def resolve_monthly_advance_limit(site_limit: int | None) -> int:
    """
    站点每月可预支次数：空字段按 1；0 表示本站禁止预支。

    :param site_limit: 站点配置，None 视为未填
    :return:
    """
    if site_limit is None:
        return DEFAULT_MONTHLY_ADVANCE_LIMIT
    limit = int(site_limit)
    if limit < 0:
        raise errors.RequestError(msg='每月可预支次数不能小于 0')
    return limit


def shanghai_calendar_month_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """
    当前自然月起止（Asia/Shanghai，含起不含止）。不使用结算周期。

    :param now: 参考时刻，缺省为当前时间
    :return:
    """
    current = now or timezone.now()
    current = current.replace(tzinfo=SHANGHAI_TZ) if current.tzinfo is None else current.astimezone(SHANGHAI_TZ)
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end


def monthly_quota_view(limit: int, used: int, *, month: str | None = None) -> dict[str, int | str]:
    """
    组装 monthly_advance_limit / used / remaining（limit 为同值别名）。

    :param limit: 每月次数上限
    :param used: 本月已占用次数
    :param month: 自然月 YYYY-MM
    :return:
    """
    remaining = max(limit - used, 0)
    payload: dict[str, int | str] = {
        'monthly_advance_limit': limit,
        'limit': limit,
        'used': used,
        'remaining': remaining,
    }
    if month:
        payload['month'] = month
    return payload


def assert_monthly_quota(limit: int, used: int) -> None:
    """申请时强校验本月次数；与金额上限错误分离。"""
    if limit <= 0:
        raise errors.RequestError(msg=MSG_SITE_ADVANCE_BANNED)
    if used >= limit:
        raise errors.RequestError(msg=MSG_QUOTA_EXHAUSTED)


def count_consumed_in_month(
    rows: list[Any],
    *,
    rider_id: int,
    site_id: int,
    month_start: datetime,
    month_end: datetime,
) -> int:
    """
    按骑手 × 站点 × 自然月统计占用次数。已驳回 / 已取消不占。

    :param rows: 预支单列表
    :param rider_id: 骑手 ID
    :param site_id: 站点 ID
    :param month_start: 自然月起（含）
    :param month_end: 自然月止（不含）
    :return:
    """
    used = 0
    for row in rows:
        if getattr(row, 'rider_id', None) != rider_id:
            continue
        if getattr(row, 'site_id', None) != site_id:
            continue
        if getattr(row, 'status', None) not in QUOTA_CONSUMING_STATUSES:
            continue
        submit = getattr(row, 'submit_time', None)
        if submit is None:
            continue
        submit = submit.replace(tzinfo=SHANGHAI_TZ) if submit.tzinfo is None else submit.astimezone(SHANGHAI_TZ)
        if month_start <= submit < month_end:
            used += 1
    return used


def attach_quota_fields(
    payload: dict[str, Any],
    quota: GetAdvanceMonthlyQuota | dict[str, Any],
) -> dict[str, Any]:
    """把次数额度写入列表/详情，兼容嵌套 quota 与扁平字段。"""
    if isinstance(quota, dict):
        limit = int(quota.get('monthly_advance_limit', quota.get('limit', 0)))
        used = int(quota.get('used', 0))
        month = quota.get('month')
        month_text = str(month) if month else None
    else:
        limit = quota.monthly_advance_limit
        used = quota.used
        month_text = quota.month
    view = monthly_quota_view(limit, used, month=month_text)
    payload['quota'] = view
    payload['monthly_advance_limit'] = view['monthly_advance_limit']
    payload['monthly_advance_used'] = view['used']
    payload['monthly_advance_remaining'] = view['remaining']
    return payload


class AdvanceService:
    """预支审核与骑手申请"""

    @staticmethod
    def transition(advance: Any, target: str, operator: Any, reason: str | None) -> None:
        """
        预支状态迁移。非法迁移抛 400。

        :param advance: 预支单
        :param target: 目标状态
        :param operator: 操作人（Request 或含 id 的对象）
        :param reason: 原因
        :return:
        """
        current = getattr(advance, 'status', None)
        if (current, target) not in _ALLOWED:
            raise errors.RequestError(
                msg=f'预支单当前状态为 {_status_label(str(current))}，不允许执行 {_TARGET_ACTION.get(target, target)}'
            )
        if target == AdvanceStatus.rejected.value:
            require_reason('预支驳回', reason)
        elif target == AdvanceStatus.cancelled.value:
            require_reason('预支取消', reason)

        oid = _operator_id(operator)
        now = timezone.now()
        advance.status = target
        if target == AdvanceStatus.to_pay.value or target == AdvanceStatus.rejected.value:
            advance.approver_id = oid
            advance.approve_time = now
            advance.approve_remark = reason
        elif target == AdvanceStatus.paid.value:
            amount = q2(getattr(advance, 'amount', ZERO) or ZERO)
            advance.paid_by = oid
            advance.paid_time = now
            advance.remaining_amount = amount
            advance.deducted_amount = ZERO
            advance.deduct_status = DeductStatus.none.value
        elif target == AdvanceStatus.cancelled.value:
            advance.cancel_time = now
        elif target == AdvanceStatus.pending.value:
            advance.submit_time = now

    @staticmethod
    async def _assert_site(db: AsyncSession, request: Request, site_id: int, *, action_msg: str) -> None:
        visible = await get_visible_site_ids(request, db)
        if visible is not None and site_id not in visible:
            raise errors.ForbiddenError(msg=action_msg)

    async def get(self, *, db: AsyncSession, request: Request, pk: int) -> GetAdvanceDetail:
        """预支详情（含时间线）"""
        advance = await advance_dao.get(db, pk)
        if not advance:
            raise errors.NotFoundError(msg='预支单不存在')
        await self._assert_site(db, request, advance.site_id, action_msg='无权访问该站点数据')
        extras = await self._enrich(db, [advance])
        data = extras[advance.id]
        data['timeline'] = await self._timeline(db, pk)
        return GetAdvanceDetail.model_validate(data)

    async def get_list(
        self,
        *,
        db: AsyncSession,
        request: Request,
        site_id: int | None,
        rider_id: int | None,
        status: str | None,
        date_from: date | None,
        date_to: date | None,
        pk: int | None = None,
    ) -> dict[str, Any]:
        """分页列表"""
        visible = await get_visible_site_ids(request, db)
        if site_id is not None:
            await self._assert_site(db, request, site_id, action_msg='无权访问该站点数据')
        stmt = await advance_dao.get_select(
            site_id=site_id,
            rider_id=rider_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            site_ids=visible if site_id is None else None,
            pk=pk,
        )
        page = await paging_data(db, stmt)
        items = page.get('items') or []
        if not items:
            return page
        rows = await self._models_from_page_items(db, items)
        extras = await self._enrich(db, rows)
        page['items'] = [GetAdvanceDetail.model_validate(extras[row.id]) for row in rows]
        return page

    async def approve(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        obj: AdvanceActionParam,
    ) -> None:
        """审核通过 pending → to_pay"""
        advance = await self._load_writable(db, request, pk)
        rider = await rider_dao.get(db, advance.rider_id)
        if rider is not None and rider.status == RiderStatus.resigned:
            raise errors.RequestError(msg='骑手已离职，请驳回该预支申请')
        before = snapshot(advance, _ADVANCE_FIELDS)
        self.transition(advance, AdvanceStatus.to_pay.value, request, obj.remark)
        await self._audit(db, request, advance, '预支通过', obj.remark, before)

    async def reject(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        obj: AdvanceReasonParam,
    ) -> None:
        """驳回 pending → rejected"""
        advance = await self._load_writable(db, request, pk)
        before = snapshot(advance, _ADVANCE_FIELDS)
        self.transition(advance, AdvanceStatus.rejected.value, request, obj.reason)
        await self._audit(db, request, advance, '预支驳回', obj.reason, before)

    async def mark_paid(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        obj: AdvanceActionParam,
    ) -> None:
        """标记发放 to_pay → paid"""
        advance = await self._load_writable(db, request, pk)
        rider = await rider_dao.get(db, advance.rider_id)
        if rider is not None and rider.status == RiderStatus.resigned:
            raise errors.RequestError(msg='骑手已离职，请取消待发放的预支，不要标记发放')
        before = snapshot(advance, _ADVANCE_FIELDS)
        self.transition(advance, AdvanceStatus.paid.value, request, obj.remark)
        await self._audit(db, request, advance, '预支发放标记', obj.remark, before)
        paid_at = advance.paid_time or timezone.now()
        if paid_at.tzinfo is None:
            paid_at = paid_at.replace(tzinfo=timezone.tz_info)
        paid_date = timezone.from_datetime(paid_at).date()
        await mark_stale(db, rider_ids=[advance.rider_id], date_from=paid_date, date_to=paid_date)

    async def cancel(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        obj: AdvanceReasonParam,
    ) -> None:
        """管理员取消 to_pay → cancelled"""
        advance = await self._load_writable(db, request, pk)
        before = snapshot(advance, _ADVANCE_FIELDS)
        self.transition(advance, AdvanceStatus.cancelled.value, request, obj.reason)
        await self._audit(db, request, advance, '预支取消', obj.reason, before)

    async def export(
        self,
        *,
        db: AsyncSession,
        request: Request,
        site_id: int | None,
        status: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> bytes:
        """导出预支明细"""
        visible = await get_visible_site_ids(request, db)
        if site_id is not None:
            await self._assert_site(db, request, site_id, action_msg='无权访问该站点数据')
        rows = await advance_dao.list_all(
            db,
            site_id=site_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            site_ids=visible if site_id is None else None,
        )
        extras = await self._enrich(db, rows) if rows else {}
        data_rows: list[list] = []
        for row in rows:
            item = extras[row.id]
            data_rows.append([
                item.get('rider_job_no') or '',
                item.get('rider_name') or '',
                item.get('site_name') or '',
                q2(row.amount),
                row.reason,
                _status_label(row.status),
                _fmt_dt(row.submit_time),
                item.get('approver_name') or '',
                _fmt_dt(row.approve_time),
                _fmt_dt(row.paid_time),
                q2(row.deducted_amount or ZERO),
                q2(row.remaining_amount or ZERO),
            ])
        return write_workbook([('预支明细', _EXPORT_HEADERS, data_rows)])

    async def submit_for_rider(
        self,
        *,
        db: AsyncSession,
        request: Request,
        rider: Any,
        obj: CreateMeAdvanceParam,
    ) -> RiderSalaryAdvance:
        """骑手提交预支"""
        if getattr(rider, 'status', None) == RiderStatus.resigned:
            raise errors.RequestError(msg='离职骑手不能申请预支')
        in_flight = await advance_dao.list_in_flight(db, rider.id)
        assert_no_in_flight(len(in_flight))
        site = await site_dao.get(db, rider.site_id)
        await self._assert_monthly_quota(db, rider=rider, site=site)
        limit = resolve_advance_limit(
            getattr(rider, 'advance_limit', None),
            getattr(site, 'advance_limit', None) if site else None,
        )
        amount = assert_advance_amount(obj.amount, limit)
        reason = (obj.reason or '').strip()
        if not reason:
            raise errors.RequestError(msg='请填写申请原因')
        payload = CreateMeAdvanceParam(amount=amount, reason=reason)
        advance = await advance_dao.create(db, payload, rider_id=rider.id, site_id=rider.site_id)
        await audit_service.record(
            db,
            request,
            module='预支',
            action='提交预支',
            target_type='advance',
            target_id=advance.id,
            target_label=f'预支单{advance.id}',
            after=snapshot(advance, _ADVANCE_FIELDS),
            description=(
                f'{resolve_operator_name(request)} 于 {_fmt_dt(timezone.now())} 对 预支单{advance.id} '
                f'执行了提交预支，金额{amount}'
            ),
        )
        return advance

    async def cancel_for_rider(
        self,
        *,
        db: AsyncSession,
        request: Request,
        rider: Any,
        pk: int,
    ) -> None:
        """骑手撤回 pending → cancelled"""
        advance = await advance_dao.get(db, pk)
        if not advance or advance.rider_id != rider.id:
            raise errors.NotFoundError(msg='预支单不存在')
        before = snapshot(advance, _ADVANCE_FIELDS)
        self.transition(advance, AdvanceStatus.cancelled.value, request, '骑手撤回')
        await self._audit(db, request, advance, '预支取消', '骑手撤回', before)

    async def list_for_rider(self, *, db: AsyncSession, rider_id: int) -> list[GetAdvanceDetail]:
        """骑手本人预支列表"""
        rows = await advance_dao.list_by_rider(db, rider_id)
        if not rows:
            return []
        extras = await self._enrich(db, rows)
        return [GetAdvanceDetail.model_validate(extras[row.id]) for row in rows]

    async def limit_for_rider(self, *, db: AsyncSession, rider: Any) -> dict[str, Any]:
        """预支金额上限 + 本月次数额度"""
        site = await site_dao.get(db, rider.site_id)
        amount_limit = resolve_advance_limit(
            getattr(rider, 'advance_limit', None),
            getattr(site, 'advance_limit', None) if site else None,
        )
        in_flight = await advance_dao.list_in_flight(db, rider.id)
        used_amount = q2(sum((row.amount for row in in_flight), ZERO))
        available = q2(max(amount_limit - used_amount, ZERO))
        quota = await self.monthly_quota_for_rider(db=db, rider=rider, site=site)
        return {
            'limit': amount_limit,
            'used_pending_amount': used_amount,
            'available': available,
            'monthly_advance_limit': quota.monthly_advance_limit,
            'used': quota.used,
            'remaining': quota.remaining,
            'month': quota.month,
        }

    async def monthly_quota_for_rider(
        self,
        *,
        db: AsyncSession,
        rider: Any,
        site: RiderSalarySite | None = None,
        now: datetime | None = None,
    ) -> GetAdvanceMonthlyQuota:
        """骑手在当前站点本自然月的次数额度"""
        return await self.monthly_quota_for_pair(
            db=db,
            rider_id=rider.id,
            site_id=rider.site_id,
            site=site,
            now=now,
        )

    async def monthly_quota_for_pair(
        self,
        *,
        db: AsyncSession,
        rider_id: int,
        site_id: int,
        site: RiderSalarySite | None = None,
        now: datetime | None = None,
    ) -> GetAdvanceMonthlyQuota:
        """骑手 × 站点 × 当前自然月次数额度"""
        if site is None:
            site = await site_dao.get(db, site_id)
        limit = resolve_monthly_advance_limit(
            getattr(site, 'monthly_advance_limit', None) if site is not None else None
        )
        month_start, month_end = shanghai_calendar_month_bounds(now)
        used = await advance_dao.count_monthly_consumed(
            db,
            rider_id=rider_id,
            site_id=site_id,
            month_start=month_start,
            month_end=month_end,
            statuses=tuple(QUOTA_CONSUMING_STATUSES),
        )
        remaining = max(limit - used, 0)
        return GetAdvanceMonthlyQuota(
            monthly_advance_limit=limit,
            used=used,
            remaining=remaining,
            month=f'{month_start.year:04d}-{month_start.month:02d}',
            rider_id=rider_id,
            site_id=site_id,
        )

    async def quota_for_admin(
        self,
        *,
        db: AsyncSession,
        request: Request,
        rider_id: int,
        site_id: int | None = None,
    ) -> GetAdvanceMonthlyQuota:
        """管理端查询骑手本月预支次数"""
        rider = await rider_dao.get(db, rider_id)
        if not rider:
            raise errors.NotFoundError(msg='骑手不存在')
        target_site_id = site_id if site_id is not None else rider.site_id
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, target_site_id)
        site = await site_dao.get(db, target_site_id) if site_id is not None else None
        if site_id is not None and site is None:
            raise errors.NotFoundError(msg='站点不存在')
        return await self.monthly_quota_for_pair(
            db=db,
            rider_id=rider.id,
            site_id=target_site_id,
            site=site,
        )

    async def _assert_monthly_quota(
        self,
        db: AsyncSession,
        *,
        rider: Any,
        site: RiderSalarySite | None,
    ) -> None:
        quota = await self.monthly_quota_for_rider(db=db, rider=rider, site=site)
        assert_monthly_quota(quota.monthly_advance_limit, quota.used)

    async def _models_from_page_items(self, db: AsyncSession, items: list[Any]) -> list[RiderSalaryAdvance]:
        ids: list[int] = []
        models: list[RiderSalaryAdvance] = []
        all_models = True
        for item in items:
            if isinstance(item, RiderSalaryAdvance):
                models.append(item)
                ids.append(item.id)
            elif isinstance(item, dict):
                all_models = False
                ids.append(int(item['id']))
            else:
                all_models = False
                ids.append(int(item.id))
        if all_models:
            return models
        rows = await db.scalars(
            select(RiderSalaryAdvance).where(RiderSalaryAdvance.id.in_(ids), RiderSalaryAdvance.deleted == 0)
        )
        by_id = {row.id: row for row in rows.all()}
        return [by_id[pk] for pk in ids if pk in by_id]

    async def _load_writable(self, db: AsyncSession, request: Request, pk: int) -> RiderSalaryAdvance:
        advance = await advance_dao.get(db, pk)
        if not advance:
            raise errors.NotFoundError(msg='预支单不存在')
        await self._assert_site(db, request, advance.site_id, action_msg='无权审核其他站点的预支申请')
        return advance

    async def _audit(
        self,
        db: AsyncSession,
        request: Request,
        advance: RiderSalaryAdvance,
        action: str,
        reason: str | None,
        before: dict[str, Any],
    ) -> None:
        await audit_service.record(
            db,
            request,
            module='预支',
            action=action,
            target_type='advance',
            target_id=advance.id,
            target_label=f'预支单{advance.id}',
            reason=reason,
            before=before,
            after=snapshot(advance, _ADVANCE_FIELDS),
        )

    async def _timeline(self, db: AsyncSession, pk: int) -> list[dict[str, Any]]:
        rows = await db.scalars(
            select(RiderSalaryAuditLog)
            .where(
                RiderSalaryAuditLog.module == '预支',
                RiderSalaryAuditLog.target_type == 'advance',
                RiderSalaryAuditLog.target_id == str(pk),
            )
            .order_by(RiderSalaryAuditLog.operate_time.asc(), RiderSalaryAuditLog.id.asc())
        )
        return [
            {
                'operate_time': row.operate_time,
                'operator_name': row.operator_name,
                'action': row.action,
                'reason': row.reason,
                'description': row.description,
            }
            for row in rows.all()
        ]

    async def _enrich(self, db: AsyncSession, rows: list[RiderSalaryAdvance]) -> dict[int, dict[str, Any]]:
        rider_ids = {row.rider_id for row in rows}
        site_ids = {row.site_id for row in rows}
        user_ids = {row.approver_id for row in rows if row.approver_id} | {row.paid_by for row in rows if row.paid_by}
        riders = {}
        if rider_ids:
            rider_rows = await db.scalars(select(RiderSalaryRider).where(RiderSalaryRider.id.in_(rider_ids)))
            riders = {item.id: item for item in rider_rows.all()}
        sites = {}
        if site_ids:
            site_rows = await db.scalars(select(RiderSalarySite).where(RiderSalarySite.id.in_(site_ids)))
            sites = {item.id: item for item in site_rows.all()}
        users: dict[int, User] = {}
        if user_ids:
            user_rows = await db.scalars(select(User).where(User.id.in_(user_ids), User.deleted == 0))
            users = {item.id: item for item in user_rows.all()}
        quotas = await self._quotas_for_rows(db, rows, sites)
        result: dict[int, dict[str, Any]] = {}
        for row in rows:
            rider = riders.get(row.rider_id)
            site = sites.get(row.site_id)
            approver = users.get(row.approver_id) if row.approver_id else None
            payer = users.get(row.paid_by) if row.paid_by else None
            payload = {name: getattr(row, name, None) for name in _ADVANCE_FIELDS}
            payload.update({
                'created_time': getattr(row, 'created_time', None),
                'updated_time': getattr(row, 'updated_time', None),
                'rider_job_no': getattr(rider, 'job_no', None),
                'rider_name': getattr(rider, 'name', None),
                'site_name': getattr(site, 'name', None),
                'approver_name': _user_label(approver),
                'paid_by_name': _user_label(payer),
                'timeline': [],
            })
            quota = quotas.get((row.rider_id, row.site_id))
            if quota is not None:
                attach_quota_fields(payload, quota)
            result[row.id] = payload
        return result

    async def _quotas_for_rows(
        self,
        db: AsyncSession,
        rows: list[RiderSalaryAdvance],
        sites: dict[int, RiderSalarySite],
    ) -> dict[tuple[int, int], GetAdvanceMonthlyQuota]:
        pairs = {(row.rider_id, row.site_id) for row in rows}
        month_start, month_end = shanghai_calendar_month_bounds()
        counts = await advance_dao.count_monthly_consumed_grouped(
            db,
            rider_site_ids=pairs,
            month_start=month_start,
            month_end=month_end,
            statuses=tuple(QUOTA_CONSUMING_STATUSES),
        )
        result: dict[tuple[int, int], GetAdvanceMonthlyQuota] = {}
        for rider_id, site_id in pairs:
            site = sites.get(site_id)
            limit = resolve_monthly_advance_limit(
                getattr(site, 'monthly_advance_limit', None) if site is not None else None
            )
            used = counts.get((rider_id, site_id), 0)
            remaining = max(limit - used, 0)
            result[rider_id, site_id] = GetAdvanceMonthlyQuota(
                monthly_advance_limit=limit,
                used=used,
                remaining=remaining,
                month=f'{month_start.year:04d}-{month_start.month:02d}',
                rider_id=rider_id,
                site_id=site_id,
            )
        return result


def _user_label(user: User | None) -> str | None:
    if user is None:
        return None
    return user.nickname or user.username


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return ''
    return timezone.to_str(value)


advance_service: AdvanceService = AdvanceService()
