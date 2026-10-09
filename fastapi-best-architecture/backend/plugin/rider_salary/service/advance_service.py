from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

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
)
from backend.plugin.rider_salary.service.audit_service import audit_service, snapshot
from backend.plugin.rider_salary.utils.audit import operator_display_name, require_reason, user_display_name
from backend.plugin.rider_salary.utils.deps import get_visible_site_ids
from backend.plugin.rider_salary.utils.excel import (
    StreamingWorkbook,
    append_streamed_rows,
    assert_export_row_limit,
    count_statement,
    stream_rows,
    stream_scalars,
)
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.recalc import mark_stale
from backend.utils.timezone import timezone

ZERO = Decimal('0.00')
IN_FLIGHT_STATUSES = frozenset({AdvanceStatus.pending.value, AdvanceStatus.to_pay.value})
IN_FLIGHT_CONFLICT_MSG = '您已有一笔待审核或待发放的预支，请等待处理完成后再申请'
STATUS_CHANGED_MSG = '该预支单状态已变化，请刷新后重试'
_IN_FLIGHT_INDEX = 'uq_rs_advance_one_in_flight'
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
        raise errors.RequestError(msg=IN_FLIGHT_CONFLICT_MSG)


def _is_in_flight_conflict(exc: IntegrityError) -> bool:
    """是否撞上在途预支部分唯一索引。"""
    text = str(exc)
    orig = getattr(exc, 'orig', None)
    if orig is not None:
        name = getattr(orig, 'constraint_name', None)
        if name == _IN_FLIGHT_INDEX:
            return True
        text = f'{text} {orig}'
    return _IN_FLIGHT_INDEX in text


def assert_expected_advance_status(current_status: str, expected_status: str | None) -> None:
    """
    期望状态与当前状态不一致时返回 409，调用方不得继续迁移或写审计。

    未传时期望不校验。抢不到行时的 409 仍由 ``transition_if_status`` 返回同一句文案。

    :param current_status: 库中当前状态
    :param expected_status: 客户端看到的状态
    :return:
    """
    if expected_status is None:
        return
    expected = expected_status.strip()
    if not expected or expected == current_status:
        return
    raise errors.ConflictError(msg=STATUS_CHANGED_MSG)


def _reject_illegal_transition(current: str | None, target: str, reason: str | None) -> None:
    """非法迁移抛 400。驳回和取消必须填写原因。"""
    if (current, target) not in _ALLOWED:
        raise errors.RequestError(
            msg=f'预支单当前状态为 {_status_label(str(current))}，不允许执行 {_TARGET_ACTION.get(target, target)}'
        )
    if target == AdvanceStatus.rejected.value:
        require_reason('预支驳回', reason)
    elif target == AdvanceStatus.cancelled.value:
        require_reason('预支取消', reason)


def _transition_values(advance: Any, target: str, operator: Any, reason: str | None) -> dict[str, Any]:
    """本次迁移要写入的列。不修改入参对象。"""
    oid = _operator_id(operator)
    now = timezone.now()
    values: dict[str, Any] = {'status': target}
    if target == AdvanceStatus.to_pay.value or target == AdvanceStatus.rejected.value:
        values['approver_id'] = oid
        values['approve_time'] = now
        values['approve_remark'] = reason
    elif target == AdvanceStatus.paid.value:
        amount = q2(getattr(advance, 'amount', ZERO) or ZERO)
        values['paid_by'] = oid
        values['paid_time'] = now
        values['remaining_amount'] = amount
        values['deducted_amount'] = ZERO
        values['deduct_status'] = DeductStatus.none.value
    elif target == AdvanceStatus.cancelled.value:
        values['cancel_time'] = now
    elif target == AdvanceStatus.pending.value:
        values['submit_time'] = now
    return values


def assert_advance_amount(amount: Decimal, limit: Decimal) -> Decimal:
    """校验金额为正且不超过上限"""
    value = q2(amount)
    if value <= 0:
        raise errors.RequestError(msg='预支金额必须大于 0')
    cap = q2(limit)
    if value > cap:
        raise errors.RequestError(msg=f'预支金额不能超过上限 {cap} 元')
    return value


def compute_available_amount(limit: Decimal, in_flight_amount: Decimal, outstanding_remaining: Decimal) -> Decimal:
    """
    可用额度 = 上限 − 在途 − 已发放未抵扣

    Q-02 按推荐方案 A：不与本期预估应发取小。

    :param limit: 预支上限
    :param in_flight_amount: 待审核与待发放金额合计
    :param outstanding_remaining: 已发放单待抵扣合计
    :return:
    """
    room = q2(limit) - q2(in_flight_amount) - q2(outstanding_remaining)
    if room < ZERO:
        return ZERO
    return q2(room)


LEAVE_AUTO_REJECT_REASON = '骑手离职自动驳回'


@dataclass(frozen=True)
class LeaveAdvanceOutcome:
    """离职时对在途预支的处理结果"""

    rejected_count: int
    to_pay_count: int
    hints: list[str]


def leave_advance_hints(*, rejected_count: int, to_pay_count: int, outstanding_amount: Decimal) -> list[str]:
    """
    离职后返回给管理员的预支提示

    待审核已自动驳回；待发放不自动取消；已发放未抵扣继续在未锁账周期抵扣。

    :param rejected_count: 自动驳回笔数
    :param to_pay_count: 仍待发放笔数
    :param outstanding_amount: 已发放未抵扣合计
    :return:
    """
    hints: list[str] = []
    if rejected_count > 0:
        hints.append('骑手已离职，预支申请已驳回')
    if to_pay_count > 0:
        hints.append('骑手已离职，请取消待发放的预支，不要标记发放')
    outstanding = q2(outstanding_amount)
    if outstanding > ZERO:
        hints.append(f'该骑手尚有预支待抵扣 {outstanding} 元，离职后将在未锁账周期继续抵扣。')
    return hints


def assert_within_available(amount: Decimal, limit: Decimal, available: Decimal) -> Decimal:
    """
    金额为正、不超过上限，且不超过可用额度

    :param amount: 申请金额
    :param limit: 预支上限
    :param available: 当前可用额度
    :return:
    """
    value = assert_advance_amount(amount, limit)
    room = q2(available)
    if value > room:
        raise errors.RequestError(msg=f'可用额度不足，当前可申请 {room} 元')
    return value


async def _advance_dimension_ids(
    db: AsyncSession,
    stmt: Any,
) -> tuple[set[int], set[int], set[int]]:
    """流式收集骑手、站点和审核人 ID，不保留预支单。"""
    rider_ids: set[int] = set()
    site_ids: set[int] = set()
    user_ids: set[int] = set()
    columns = stmt.order_by(None).with_only_columns(
        RiderSalaryAdvance.rider_id,
        RiderSalaryAdvance.site_id,
        RiderSalaryAdvance.approver_id,
        maintain_column_froms=True,
    )
    async for row in stream_rows(db, columns):
        rider_ids.add(int(row[0]))
        site_ids.add(int(row[1]))
        if row[2]:
            user_ids.add(int(row[2]))
    return rider_ids, site_ids, user_ids


async def _advance_export_lookups(
    db: AsyncSession,
    stmt: Any,
) -> tuple[dict[int, RiderSalaryRider], dict[int, RiderSalarySite], dict[int, User]]:
    """在打开预支明细流之前加载名称，避免游标未关时再查库。"""
    rider_ids, site_ids, user_ids = await _advance_dimension_ids(db, stmt)
    riders: dict[int, RiderSalaryRider] = {}
    if rider_ids:
        rider_rows = await db.scalars(select(RiderSalaryRider).where(RiderSalaryRider.id.in_(rider_ids)))
        riders = {item.id: item for item in rider_rows.all()}
    sites: dict[int, RiderSalarySite] = {}
    if site_ids:
        site_rows = await db.scalars(select(RiderSalarySite).where(RiderSalarySite.id.in_(site_ids)))
        sites = {item.id: item for item in site_rows.all()}
    users: dict[int, User] = {}
    if user_ids:
        user_rows = await db.scalars(select(User).where(User.id.in_(user_ids), User.deleted == 0))
        users = {item.id: item for item in user_rows.all()}
    return riders, sites, users


def _advance_export_values(
    row: Any,
    riders: dict[int, RiderSalaryRider],
    sites: dict[int, RiderSalarySite],
    users: dict[int, User],
) -> list[object]:
    rider = riders.get(row.rider_id)
    site = sites.get(row.site_id)
    approver = users.get(row.approver_id) if row.approver_id else None
    return [
        getattr(rider, 'job_no', None) or '',
        getattr(rider, 'name', None) or '',
        getattr(site, 'name', None) or '',
        q2(row.amount),
        row.reason,
        _status_label(row.status),
        _fmt_dt(row.submit_time),
        _user_label(approver) or '',
        _fmt_dt(row.approve_time),
        _fmt_dt(row.paid_time),
        q2(row.deducted_amount or ZERO),
        q2(row.remaining_amount or ZERO),
    ]


async def _iter_advance_export_rows(
    db: AsyncSession,
    stmt: Any,
    lookups: tuple[dict[int, RiderSalaryRider], dict[int, RiderSalarySite], dict[int, User]],
) -> AsyncIterator[list[object]]:
    """逐笔预支生成导出行。迭代器前进一步只消费一笔预支。"""
    riders, sites, users = lookups
    async for row in stream_scalars(db, stmt):
        values = _advance_export_values(row, riders, sites, users)
        db.expunge(row)
        yield values


class AdvanceService:
    """预支审核与骑手申请"""

    @staticmethod
    def transition(advance: Any, target: str, operator: Any, reason: str | None) -> None:
        """
        预支状态迁移。非法迁移抛 400。

        内存对象直接改字段，供状态机单测使用。已落库的单据走 ``transition_if_status``。

        :param advance: 预支单
        :param target: 目标状态
        :param operator: 操作人（Request 或含 id 的对象）
        :param reason: 原因
        :return:
        """
        _reject_illegal_transition(getattr(advance, 'status', None), target, reason)
        for key, value in _transition_values(advance, target, operator, reason).items():
            setattr(advance, key, value)

    async def transition_if_status(
        self,
        db: AsyncSession,
        advance: Any,
        target: str,
        operator: Any,
        reason: str | None,
    ) -> None:
        """
        ``UPDATE … WHERE id=? AND status=?``。抢不到行时返回 409。

        非持久化对象仍走内存迁移，避免状态机单测依赖数据库。

        :param db: 数据库会话
        :param advance: 预支单
        :param target: 目标状态
        :param operator: 操作人
        :param reason: 原因
        :return:
        """
        if not isinstance(advance, RiderSalaryAdvance):
            self.transition(advance, target, operator, reason)
            return
        current = advance.status
        _reject_illegal_transition(current, target, reason)
        values = _transition_values(advance, target, operator, reason)
        result = await db.execute(
            update(RiderSalaryAdvance)
            .where(
                RiderSalaryAdvance.id == advance.id,
                RiderSalaryAdvance.status == current,
                RiderSalaryAdvance.deleted == 0,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if int(result.rowcount or 0) != 1:
            raise errors.ConflictError(msg=STATUS_CHANGED_MSG)
        for key, value in values.items():
            set_committed_value(advance, key, value)

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
        assert_expected_advance_status(advance.status, obj.expected_status)
        rider = await rider_dao.get(db, advance.rider_id)
        if rider is not None and rider.status == RiderStatus.resigned:
            raise errors.RequestError(msg='骑手已离职，请驳回该预支申请')
        before = snapshot(advance, _ADVANCE_FIELDS)
        await self.transition_if_status(db, advance, AdvanceStatus.to_pay.value, request, obj.remark)
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
        assert_expected_advance_status(advance.status, obj.expected_status)
        before = snapshot(advance, _ADVANCE_FIELDS)
        await self.transition_if_status(db, advance, AdvanceStatus.rejected.value, request, obj.reason)
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
        assert_expected_advance_status(advance.status, obj.expected_status)
        rider = await rider_dao.get(db, advance.rider_id)
        if rider is not None and rider.status == RiderStatus.resigned:
            raise errors.RequestError(msg='骑手已离职，请取消待发放的预支，不要标记发放')
        before = snapshot(advance, _ADVANCE_FIELDS)
        await self.transition_if_status(db, advance, AdvanceStatus.paid.value, request, obj.remark)
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
        assert_expected_advance_status(advance.status, obj.expected_status)
        before = snapshot(advance, _ADVANCE_FIELDS)
        await self.transition_if_status(db, advance, AdvanceStatus.cancelled.value, request, obj.reason)
        await self._audit(db, request, advance, '预支取消', obj.reason, before)

    async def reject_pending_on_leave(
        self,
        *,
        db: AsyncSession,
        request: Request,
        rider_id: int,
    ) -> LeaveAdvanceOutcome:
        """
        离职时自动驳回待审核预支，待发放保持原状

        :param db: 数据库会话
        :param request: 请求对象
        :param rider_id: 骑手 ID
        :return:
        """
        rows = await advance_dao.list_in_flight(db, rider_id)
        rejected = 0
        to_pay = 0
        for advance in rows:
            if advance.status == AdvanceStatus.pending.value:
                before = snapshot(advance, _ADVANCE_FIELDS)
                try:
                    await self.transition_if_status(
                        db, advance, AdvanceStatus.rejected.value, request, LEAVE_AUTO_REJECT_REASON
                    )
                except errors.ConflictError:
                    await db.refresh(advance)
                    if advance.status == AdvanceStatus.to_pay.value:
                        to_pay += 1
                    continue
                await self._audit(db, request, advance, '预支驳回', LEAVE_AUTO_REJECT_REASON, before)
                rejected += 1
            elif advance.status == AdvanceStatus.to_pay.value:
                to_pay += 1
        outstanding = await self._paid_remaining_total(db, rider_id)
        return LeaveAdvanceOutcome(
            rejected_count=rejected,
            to_pay_count=to_pay,
            hints=leave_advance_hints(
                rejected_count=rejected,
                to_pay_count=to_pay,
                outstanding_amount=outstanding,
            ),
        )

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
        stmt = await advance_dao.get_select(
            site_id=site_id,
            rider_id=None,
            status=status,
            date_from=date_from,
            date_to=date_to,
            site_ids=visible if site_id is None else None,
        )
        total = await count_statement(db, stmt)
        assert_export_row_limit(total)
        lookups = await _advance_export_lookups(db, stmt)
        book = StreamingWorkbook()
        sheet = book.add_sheet('预支明细', _EXPORT_HEADERS)
        await append_streamed_rows(book, sheet, _iter_advance_export_rows(db, stmt, lookups))
        return book.to_bytes()

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
        quota = await self._quota(db, rider)
        assert_no_in_flight(quota['in_flight_count'])
        amount = assert_within_available(obj.amount, quota['limit'], quota['available'])
        reason = (obj.reason or '').strip()
        if not reason:
            raise errors.RequestError(msg='请填写申请原因')
        payload = CreateMeAdvanceParam(amount=amount, reason=reason)
        try:
            advance = await advance_dao.create(db, payload, rider_id=rider.id, site_id=rider.site_id)
        except IntegrityError as exc:
            if _is_in_flight_conflict(exc):
                raise errors.ConflictError(msg=IN_FLIGHT_CONFLICT_MSG) from exc
            raise
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
                f'{operator_display_name(request)} 于 {_fmt_dt(timezone.now())} 对 预支单{advance.id} '
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
        """骑手撤回，仅允许待审核 pending → cancelled"""
        advance = await advance_dao.get(db, pk)
        if not advance or advance.rider_id != rider.id:
            raise errors.NotFoundError(msg='预支单不存在')
        if advance.status != AdvanceStatus.pending.value:
            raise errors.RequestError(msg='只能撤回待审核的预支申请')
        before = snapshot(advance, _ADVANCE_FIELDS)
        await self.transition_if_status(db, advance, AdvanceStatus.cancelled.value, request, '骑手撤回')
        await self._audit(db, request, advance, '预支取消', '骑手撤回', before)

    async def list_for_rider(self, *, db: AsyncSession, rider_id: int) -> list[GetAdvanceDetail]:
        """骑手本人预支列表。时间线用单据时间字段生成的精简节点，不查审计日志。"""
        rows = await advance_dao.list_by_rider(db, rider_id)
        if not rows:
            return []
        extras = await self._enrich(db, rows)
        for row in rows:
            payload = extras[row.id]
            payload['timeline'] = compact_advance_timeline(row, payload)
        return [GetAdvanceDetail.model_validate(extras[row.id]) for row in rows]

    async def limit_for_rider(self, *, db: AsyncSession, rider: Any) -> dict[str, Decimal]:
        """预支额度：上限、在途、已发放未抵扣、可用"""
        quota = await self._quota(db, rider)
        return {
            'limit': quota['limit'],
            'used_pending_amount': quota['used_pending_amount'],
            'outstanding_amount': quota['outstanding_amount'],
            'available': quota['available'],
        }

    async def _quota(self, db: AsyncSession, rider: Any) -> dict[str, Any]:
        """汇总上限、在途占用、已发放未抵扣与可用额度"""
        site = await site_dao.get(db, rider.site_id)
        limit = resolve_advance_limit(
            getattr(rider, 'advance_limit', None),
            getattr(site, 'advance_limit', None) if site else None,
        )
        in_flight = await advance_dao.list_in_flight(db, rider.id)
        in_flight_amount = q2(sum((row.amount for row in in_flight), ZERO))
        outstanding = await self._paid_remaining_total(db, rider.id)
        return {
            'limit': limit,
            'used_pending_amount': in_flight_amount,
            'outstanding_amount': outstanding,
            'available': compute_available_amount(limit, in_flight_amount, outstanding),
            'in_flight_count': len(in_flight),
        }

    @staticmethod
    async def _paid_remaining_total(db: AsyncSession, rider_id: int) -> Decimal:
        """已发放且未抵扣完的 remaining_amount 合计"""
        rows = await db.scalars(
            select(RiderSalaryAdvance.remaining_amount).where(
                RiderSalaryAdvance.rider_id == rider_id,
                RiderSalaryAdvance.status == AdvanceStatus.paid.value,
                RiderSalaryAdvance.deleted == 0,
            )
        )
        total = ZERO
        for raw in rows.all():
            if raw is None:
                continue
            value = q2(raw)
            if value > ZERO:
                total += value
        return q2(total)

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
            result[row.id] = payload
        return result


def _user_label(user: User | None) -> str | None:
    return user_display_name(user)


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return ''
    return timezone.to_str(value)


_COMPACT_ACTION_ORDER = {
    '提交预支': 0,
    '预支通过': 1,
    '预支驳回': 1,
    '预支发放标记': 2,
    '预支取消': 3,
}


def compact_advance_timeline(row: Any, names: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """列表精简时间线。

    由预支单上的提交、审核、发放、取消时间生成，不查询审计日志。
    详情接口仍返回完整审计时间线。
    """
    label = names or {}
    rider_name = label.get('rider_name') or '骑手'
    approver_name = label.get('approver_name') or '审核人'
    payer_name = label.get('paid_by_name') or '发放人'
    nodes: list[dict[str, Any]] = []
    submit_time = getattr(row, 'submit_time', None)
    if submit_time is not None:
        nodes.append({
            'operate_time': submit_time,
            'operator_name': rider_name,
            'action': '提交预支',
            'reason': None,
            'description': None,
        })
    approve_time = getattr(row, 'approve_time', None)
    if approve_time is not None:
        rejected = getattr(row, 'status', None) == AdvanceStatus.rejected.value
        nodes.append({
            'operate_time': approve_time,
            'operator_name': approver_name,
            'action': '预支驳回' if rejected else '预支通过',
            'reason': getattr(row, 'approve_remark', None),
            'description': None,
        })
    paid_time = getattr(row, 'paid_time', None)
    if paid_time is not None:
        nodes.append({
            'operate_time': paid_time,
            'operator_name': payer_name,
            'action': '预支发放标记',
            'reason': None,
            'description': None,
        })
    cancel_time = getattr(row, 'cancel_time', None)
    if cancel_time is not None:
        approved = getattr(row, 'approve_time', None) is not None
        nodes.append({
            'operate_time': cancel_time,
            'operator_name': '管理员' if approved else rider_name,
            'action': '预支取消',
            'reason': None,
            'description': None,
        })

    def _sort_key(item: dict[str, Any]) -> tuple[float, int]:
        moment = item['operate_time']
        stamp = moment.timestamp() if isinstance(moment, datetime) else 0.0
        return (stamp, _COMPACT_ACTION_ORDER.get(str(item['action']), 9))

    nodes.sort(key=_sort_key)
    return nodes


advance_service: AdvanceService = AdvanceService()
