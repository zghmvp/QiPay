from typing import Any

from fastapi import Request
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.rider_salary.crud.notice import notice_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.enums import NoticeStatus
from backend.plugin.rider_salary.model.notice import RiderSalaryNotice
from backend.plugin.rider_salary.schema.notice import CreateNoticeParam, UpdateNoticeParam
from backend.plugin.rider_salary.service.audit_service import audit_service, is_global_operator, snapshot
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.utils.timezone import timezone

_NOTICE_FIELDS = ('id', 'title', 'content', 'site_id', 'publisher_id', 'publish_time', 'status')


class NoticeService:
    """站点公告服务"""

    @staticmethod
    async def _assert_writable(*, db: AsyncSession, request: Request, site_id: int | None) -> None:
        if site_id is None:
            if not is_global_operator(request):
                raise errors.ForbiddenError(msg='负责人只能操作本站点公告')
            return
        if not await site_dao.get(db, site_id):
            raise errors.NotFoundError(msg='站点不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, site_id)

    @staticmethod
    async def get(*, db: AsyncSession, request: Request, pk: int) -> Any:
        """获取公告详情"""
        notice = await notice_dao.get(db, pk)
        if not notice:
            raise errors.NotFoundError(msg='公告不存在')
        if notice.site_id is not None:
            visible = await get_visible_site_ids(request, db)
            assert_site_visible(visible, notice.site_id)
        return notice

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        request: Request,
        title: str | None,
        status: str | None,
        site_id: int | None,
    ) -> dict[str, Any]:
        """分页获取公告"""
        visible = await get_visible_site_ids(request, db)
        if site_id is not None:
            assert_site_visible(visible, site_id)
        stmt = await notice_dao.get_select(title=title, status=status, site_id=site_id, site_ids=None)
        if visible is not None and site_id is None:
            stmt = stmt.where(
                or_(RiderSalaryNotice.site_id.in_(list(visible) or [-1]), RiderSalaryNotice.site_id.is_(None))
            )
        return await paging_data(db, stmt)

    @staticmethod
    async def create(*, db: AsyncSession, request: Request, obj: CreateNoticeParam) -> None:
        """创建公告"""
        await NoticeService._assert_writable(db=db, request=request, site_id=obj.site_id)
        notice = await notice_dao.create(db, obj, publisher_id=int(request.user.id))
        await audit_service.record(
            db,
            request,
            module='站点公告',
            action='创建公告',
            target_type='notice',
            target_id=notice.id,
            target_label=notice.title,
            after=snapshot(notice, _NOTICE_FIELDS),
        )

    @staticmethod
    async def update(*, db: AsyncSession, request: Request, pk: int, obj: UpdateNoticeParam) -> int:
        """更新公告"""
        notice = await notice_dao.get(db, pk)
        if not notice:
            raise errors.NotFoundError(msg='公告不存在')
        await NoticeService._assert_writable(db=db, request=request, site_id=notice.site_id)
        if obj.site_id is not None:
            await NoticeService._assert_writable(db=db, request=request, site_id=obj.site_id)
        before = snapshot(notice, _NOTICE_FIELDS)
        count = await notice_dao.update(db, pk, obj)
        updated = await notice_dao.get(db, pk)
        await audit_service.record(
            db,
            request,
            module='站点公告',
            action='修改公告',
            target_type='notice',
            target_id=pk,
            target_label=notice.title,
            before=before,
            after=snapshot(updated, _NOTICE_FIELDS) if updated else None,
        )
        return count

    @staticmethod
    async def delete(*, db: AsyncSession, request: Request, pk: int) -> int:
        """删除公告"""
        notice = await notice_dao.get(db, pk)
        if not notice:
            raise errors.NotFoundError(msg='公告不存在')
        await NoticeService._assert_writable(db=db, request=request, site_id=notice.site_id)
        before = snapshot(notice, _NOTICE_FIELDS)
        count = await notice_dao.delete(db, pk)
        await audit_service.record(
            db,
            request,
            module='站点公告',
            action='删除公告',
            target_type='notice',
            target_id=pk,
            target_label=notice.title,
            before=before,
        )
        return count

    @staticmethod
    async def publish(*, db: AsyncSession, request: Request, pk: int) -> int:
        """发布公告"""
        notice = await notice_dao.get(db, pk)
        if not notice:
            raise errors.NotFoundError(msg='公告不存在')
        await NoticeService._assert_writable(db=db, request=request, site_id=notice.site_id)
        if notice.status == NoticeStatus.published:
            raise errors.ConflictError(msg='公告已发布')
        before = snapshot(notice, _NOTICE_FIELDS)
        count = await notice_dao.update(
            db,
            pk,
            {'status': NoticeStatus.published.value, 'publish_time': timezone.now()},
        )
        updated = await notice_dao.get(db, pk)
        await audit_service.record(
            db,
            request,
            module='站点公告',
            action='发布公告',
            target_type='notice',
            target_id=pk,
            target_label=notice.title,
            before=before,
            after=snapshot(updated, _NOTICE_FIELDS) if updated else None,
        )
        return count

    @staticmethod
    async def offline(*, db: AsyncSession, request: Request, pk: int) -> int:
        """下线公告"""
        notice = await notice_dao.get(db, pk)
        if not notice:
            raise errors.NotFoundError(msg='公告不存在')
        await NoticeService._assert_writable(db=db, request=request, site_id=notice.site_id)
        if notice.status != NoticeStatus.published:
            raise errors.RequestError(msg='仅已发布公告可下线')
        before = snapshot(notice, _NOTICE_FIELDS)
        count = await notice_dao.update(db, pk, {'status': NoticeStatus.offline.value})
        updated = await notice_dao.get(db, pk)
        await audit_service.record(
            db,
            request,
            module='站点公告',
            action='下线公告',
            target_type='notice',
            target_id=pk,
            target_label=notice.title,
            before=before,
            after=snapshot(updated, _NOTICE_FIELDS) if updated else None,
        )
        return count


notice_service: NoticeService = NoticeService()
