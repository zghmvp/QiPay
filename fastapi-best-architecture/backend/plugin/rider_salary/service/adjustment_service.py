from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.rider_salary.crud.adjustment import adjustment_dao
from backend.plugin.rider_salary.crud.rider import rider_dao
from backend.plugin.rider_salary.crud.rider_employ_history import rider_employ_history_dao
from backend.plugin.rider_salary.crud.subject import subject_dao
from backend.plugin.rider_salary.enums import EnableStatus, EntryGranularity, RiderStatus, SubjectDirection
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.schema.adjustment import CreateAdjustmentParam, UpdateAdjustmentParam
from backend.plugin.rider_salary.service.audit_service import audit_service, snapshot
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.lock_check import assert_not_locked
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.recalc import mark_stale

_PREV_DIFF_CODES = frozenset({'PREV_DIFF', 'PREV_PERIOD_ADJ'})
_ADJ_FIELDS = (
    'id',
    'rider_id',
    'site_id',
    'biz_date',
    'subject_id',
    'amount',
    'signed_amount',
    'remark',
    'is_locked',
)
_PERIOD_HINT = '该科目按周期入账，业务日期仅用于展示，服务层不改动'


def compute_signed_amount(direction: str, amount: Decimal) -> Decimal:
    """按科目方向计算带符号金额"""
    quantized = q2(amount)
    if direction == SubjectDirection.bonus:
        return quantized
    return q2(-quantized)


def _scope_allows(scope: list | None, value: Any) -> bool:
    if not scope:
        return True
    return value in scope


class AdjustmentService:
    """奖惩记录服务"""

    @staticmethod
    def _employ_type_on(histories: list, biz_date: date, fallback: str) -> str:
        for item in histories:
            end = item.end_date
            if item.start_date <= biz_date and (end is None or end >= biz_date):
                return item.employ_type
        return fallback

    @staticmethod
    def _validate_amount(subject: RiderSalarySubject, amount: Decimal) -> None:
        if subject.code in _PREV_DIFF_CODES:
            if amount == 0:
                raise errors.RequestError(msg='金额不能为 0')
            return
        if amount <= 0:
            raise errors.RequestError(msg='金额必须大于 0')

    @staticmethod
    async def _load_context(
        *,
        db: AsyncSession,
        request: Request,
        rider_id: int,
        subject_id: int,
        biz_date: date,
    ) -> tuple[Any, RiderSalarySubject, str]:
        rider = await rider_dao.get(db, rider_id)
        if not rider:
            raise errors.NotFoundError(msg='骑手不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, rider.site_id)
        if rider.status != RiderStatus.on_job:
            raise errors.RequestError(msg='骑手不在职，无法录入奖惩')
        subject = await subject_dao.get(db, subject_id)
        if not subject:
            raise errors.NotFoundError(msg='科目不存在')
        if subject.status != EnableStatus.enable:
            raise errors.RequestError(msg='科目未启用')
        histories = list(await rider_employ_history_dao.get_by_rider(db, rider_id))
        employ_type = AdjustmentService._employ_type_on(histories, biz_date, rider.employ_type)
        if not _scope_allows(subject.scope_sites, rider.site_id):
            raise errors.RequestError(msg='科目不适用于该站点')
        if not _scope_allows(subject.scope_employ_types, employ_type):
            raise errors.RequestError(msg='科目不适用于该用工类型')
        return rider, subject, employ_type

    @staticmethod
    async def _enrich(db: AsyncSession, row: Any) -> dict[str, Any]:
        data = snapshot(row, _ADJ_FIELDS)
        data['biz_date'] = row.biz_date
        data['amount'] = row.amount
        data['signed_amount'] = row.signed_amount
        data['created_time'] = row.created_time
        data['updated_time'] = row.updated_time
        data['period_id'] = row.period_id
        data['operator_id'] = row.operator_id
        rider = await rider_dao.get(db, row.rider_id)
        subject = await subject_dao.get(db, row.subject_id)
        data['rider_job_no'] = rider.job_no if rider else None
        data['rider_name'] = rider.name if rider else None
        data['subject_name'] = subject.name if subject else None
        data['direction'] = subject.direction if subject else None
        data['hint'] = _PERIOD_HINT if subject and subject.entry_granularity == EntryGranularity.period else None
        return data

    @staticmethod
    async def get(*, db: AsyncSession, request: Request, pk: int) -> dict[str, Any]:
        """获取奖惩记录详情"""
        row = await adjustment_dao.get(db, pk)
        if not row:
            raise errors.NotFoundError(msg='奖惩记录不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, row.site_id)
        return await AdjustmentService._enrich(db, row)

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        request: Request,
        site_id: int | None,
        rider_id: int | None,
        subject_id: int | None,
        date_from: date | None,
        date_to: date | None,
        direction: str | None,
        pk: int | None = None,
    ) -> dict[str, Any]:
        """分页获取奖惩记录"""
        visible = await get_visible_site_ids(request, db)
        if site_id is not None:
            assert_site_visible(visible, site_id)
        stmt = await adjustment_dao.get_select(
            site_id=site_id,
            rider_id=rider_id,
            subject_id=subject_id,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
            site_ids=visible,
            pk=pk,
        )
        if direction:
            stmt = stmt.join(
                RiderSalarySubject,
                RiderSalarySubject.id == adjustment_dao.model.subject_id,
            ).where(RiderSalarySubject.direction == direction, RiderSalarySubject.deleted == 0)
        page = await paging_data(db, stmt)
        items = []
        for raw in page.get('items') or []:
            pk = raw['id'] if isinstance(raw, dict) else raw.id
            row = await adjustment_dao.get(db, pk)
            if row:
                items.append(await AdjustmentService._enrich(db, row))
        page['items'] = items
        return page

    @staticmethod
    async def create(*, db: AsyncSession, request: Request, obj: CreateAdjustmentParam) -> dict[str, Any]:
        """创建奖惩记录"""
        if not obj.remark or not str(obj.remark).strip():
            raise errors.RequestError(msg='备注不能为空')
        rider, subject, _ = await AdjustmentService._load_context(
            db=db,
            request=request,
            rider_id=obj.rider_id,
            subject_id=obj.subject_id,
            biz_date=obj.biz_date,
        )
        AdjustmentService._validate_amount(subject, obj.amount)
        await assert_not_locked(db, site_id=rider.site_id, rider_id=rider.id, biz_date=obj.biz_date)
        signed = compute_signed_amount(subject.direction, obj.amount)
        row = await adjustment_dao.create(
            db,
            obj,
            site_id=rider.site_id,
            signed_amount=signed,
            operator_id=int(request.user.id),
        )
        await mark_stale(db, rider_ids=[rider.id], date_from=obj.biz_date, date_to=obj.biz_date)
        await audit_service.record(
            db,
            request,
            module='奖惩录入',
            action='新增奖惩',
            target_type='adjustment',
            target_id=row.id,
            target_label=f'{rider.job_no} {rider.name} {subject.name}',
            after=snapshot(row, _ADJ_FIELDS),
        )
        return await AdjustmentService._enrich(db, row)

    @staticmethod
    async def create_batch(*, db: AsyncSession, request: Request, items: list[CreateAdjustmentParam]) -> list[dict]:
        """批量创建奖惩记录（同一事务，任一行失败整批失败）"""
        result: list[dict] = []
        first_error: tuple[int, str] | None = None
        for index, item in enumerate(items, start=1):
            if first_error is not None:
                break
            row_or_error = await AdjustmentService._create_or_error(db=db, request=request, obj=item)
            if isinstance(row_or_error, str):
                first_error = (index, row_or_error)
            else:
                result.append(row_or_error)
        if first_error is not None:
            index, reason = first_error
            raise errors.RequestError(msg=f'第 {index} 行：{reason}', data={'row': index, 'reason': reason})
        return result

    @staticmethod
    async def _create_or_error(
        *,
        db: AsyncSession,
        request: Request,
        obj: CreateAdjustmentParam,
    ) -> dict[str, Any] | str:
        """创建单条奖惩，失败时返回中文原因"""
        try:
            return await AdjustmentService.create(db=db, request=request, obj=obj)
        except errors.BaseExceptionError as exc:
            return exc.msg or '录入失败'

    @staticmethod
    async def update(*, db: AsyncSession, request: Request, pk: int, obj: UpdateAdjustmentParam) -> int:
        """更新奖惩记录"""
        row = await adjustment_dao.get(db, pk)
        if not row:
            raise errors.NotFoundError(msg='奖惩记录不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, row.site_id)
        rider_id = obj.rider_id or row.rider_id
        subject_id = obj.subject_id or row.subject_id
        biz_date = obj.biz_date or row.biz_date
        amount = obj.amount if obj.amount is not None else row.amount
        remark = obj.remark if obj.remark is not None else row.remark
        if not remark or not str(remark).strip():
            raise errors.RequestError(msg='备注不能为空')
        rider, subject, _ = await AdjustmentService._load_context(
            db=db,
            request=request,
            rider_id=rider_id,
            subject_id=subject_id,
            biz_date=biz_date,
        )
        AdjustmentService._validate_amount(subject, amount)
        await assert_not_locked(db, site_id=row.site_id, rider_id=row.rider_id, biz_date=row.biz_date)
        await assert_not_locked(db, site_id=rider.site_id, rider_id=rider.id, biz_date=biz_date)
        signed = compute_signed_amount(subject.direction, amount)
        before = snapshot(row, _ADJ_FIELDS)
        payload = {
            'rider_id': rider_id,
            'site_id': rider.site_id,
            'biz_date': biz_date,
            'subject_id': subject_id,
            'amount': amount,
            'signed_amount': signed,
            'remark': remark,
        }
        count = await adjustment_dao.update(db, pk, payload)
        updated = await adjustment_dao.get(db, pk)
        dates = [row.biz_date, biz_date]
        await mark_stale(db, rider_ids=[row.rider_id, rider.id], date_from=min(dates), date_to=max(dates))
        await audit_service.record(
            db,
            request,
            module='奖惩录入',
            action='奖惩修改',
            target_type='adjustment',
            target_id=pk,
            target_label=f'{rider.job_no} {rider.name} {subject.name}',
            reason=obj.reason,
            before=before,
            after=snapshot(updated, _ADJ_FIELDS) if updated else None,
        )
        return count

    @staticmethod
    async def delete(*, db: AsyncSession, request: Request, pk: int, reason: str) -> int:
        """删除奖惩记录"""
        row = await adjustment_dao.get(db, pk)
        if not row:
            raise errors.NotFoundError(msg='奖惩记录不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, row.site_id)
        await assert_not_locked(db, site_id=row.site_id, rider_id=row.rider_id, biz_date=row.biz_date)
        before = snapshot(row, _ADJ_FIELDS)
        count = await adjustment_dao.delete(db, pk)
        await mark_stale(db, rider_ids=[row.rider_id], date_from=row.biz_date, date_to=row.biz_date)
        await audit_service.record(
            db,
            request,
            module='奖惩录入',
            action='奖惩删除',
            target_type='adjustment',
            target_id=pk,
            target_label=f'奖惩记录 #{pk}',
            reason=reason,
            before=before,
        )
        return count


adjustment_service: AdjustmentService = AdjustmentService()
