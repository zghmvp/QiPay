from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.rider_salary.crud.subject import subject_dao
from backend.plugin.rider_salary.enums import SubjectDirection
from backend.plugin.rider_salary.schema.subject import CreateSubjectParam, UpdateSubjectParam
from backend.plugin.rider_salary.service.audit_service import audit_service, snapshot

_SUBJECT_FIELDS = (
    'id',
    'code',
    'name',
    'direction',
    'fee_mode',
    'fixed_amount',
    'include_in_gross',
    'entry_granularity',
    'scope_sites',
    'scope_employ_types',
    'is_builtin',
    'status',
    'sort_order',
    'remark',
)


def builtin_forbidden_changed(before: Any, obj: UpdateSubjectParam) -> bool:
    """内置科目是否试图修改编码/方向/是否进应发"""
    if obj.code is not None and obj.code != before.code:
        return True
    if obj.direction is not None and obj.direction != before.direction:
        return True
    return bool(obj.include_in_gross is not None and obj.include_in_gross != before.include_in_gross)


class SubjectService:
    """科目服务"""

    @staticmethod
    def _validate_gross(*, direction: str, include_in_gross: bool) -> None:
        if not include_in_gross and direction == SubjectDirection.bonus:
            raise errors.RequestError(msg='不进应发的科目只能是扣款方向')

    @staticmethod
    async def get(*, db: AsyncSession, pk: int) -> Any:
        """获取科目详情"""
        subject = await subject_dao.get(db, pk)
        if not subject:
            raise errors.NotFoundError(msg='科目不存在')
        return subject

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        name: str | None,
        status: str | None,
        direction: str | None,
    ) -> dict[str, Any]:
        """分页获取科目"""
        stmt = await subject_dao.get_select(name=name, status=status, direction=direction)
        return await paging_data(db, stmt)

    @staticmethod
    async def get_all(*, db: AsyncSession) -> Any:
        """获取科目下拉列表"""
        return await subject_dao.get_all(db)

    @staticmethod
    async def create(*, db: AsyncSession, request: Request, obj: CreateSubjectParam) -> None:
        """创建科目"""
        if await subject_dao.get_by_code(db, obj.code):
            raise errors.ConflictError(msg='科目编码已存在')
        SubjectService._validate_gross(direction=obj.direction, include_in_gross=obj.include_in_gross)
        subject = await subject_dao.create(db, obj)
        await audit_service.record(
            db,
            request,
            module='科目管理',
            action='创建科目',
            target_type='subject',
            site_id=None,
            target_id=subject.id,
            target_label=f'{subject.code} {subject.name}',
            after=snapshot(subject, _SUBJECT_FIELDS),
        )

    @staticmethod
    async def update(*, db: AsyncSession, request: Request, pk: int, obj: UpdateSubjectParam) -> int:
        """更新科目"""
        subject = await subject_dao.get(db, pk)
        if not subject:
            raise errors.NotFoundError(msg='科目不存在')
        if obj.code and obj.code != subject.code and await subject_dao.get_by_code(db, obj.code):
            raise errors.ConflictError(msg='科目编码已存在')
        if subject.is_builtin and builtin_forbidden_changed(subject, obj):
            raise errors.RequestError(msg='内置科目不允许修改编码、方向或是否进应发')
        direction = obj.direction if obj.direction is not None else subject.direction
        include_in_gross = obj.include_in_gross if obj.include_in_gross is not None else subject.include_in_gross
        SubjectService._validate_gross(direction=direction, include_in_gross=include_in_gross)
        payload = obj.model_dump(exclude_unset=True)
        if subject.is_builtin:
            payload.pop('code', None)
            payload.pop('direction', None)
            payload.pop('include_in_gross', None)
        before = snapshot(subject, _SUBJECT_FIELDS)
        count = await subject_dao.update(db, pk, payload)
        updated = await subject_dao.get(db, pk)
        await audit_service.record(
            db,
            request,
            module='科目管理',
            action='修改科目',
            target_type='subject',
            site_id=None,
            target_id=pk,
            target_label=f'{subject.code} {subject.name}',
            before=before,
            after=snapshot(updated, _SUBJECT_FIELDS) if updated else None,
        )
        return count

    @staticmethod
    async def delete(*, db: AsyncSession, request: Request, pk: int) -> int:
        """删除科目"""
        subject = await subject_dao.get(db, pk)
        if not subject:
            raise errors.NotFoundError(msg='科目不存在')
        if subject.is_builtin:
            raise errors.ConflictError(msg='系统内置科目不可删除，可停用')
        adj_count, item_count = await subject_dao.count_refs(db, pk)
        if adj_count or item_count:
            raise errors.ConflictError(msg=f'科目已被引用（奖惩记录 {adj_count} 条、方案项 {item_count} 条），无法删除')
        before = snapshot(subject, _SUBJECT_FIELDS)
        count = await subject_dao.delete(db, pk)
        await audit_service.record(
            db,
            request,
            module='科目管理',
            action='删除科目',
            target_type='subject',
            site_id=None,
            target_id=pk,
            target_label=f'{subject.code} {subject.name}',
            before=before,
        )
        return count


subject_service: SubjectService = SubjectService()
