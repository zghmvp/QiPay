from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.admin.model import User
from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.rider_salary.crud.rider import rider_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.crud.site_manager import site_manager_dao
from backend.plugin.rider_salary.enums import CycleType, ManagerRole, PeriodStatus
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.schema.site import (
    CreateSiteParam,
    GetSiteManagerDetail,
    SiteManagerItem,
    UpdateSiteParam,
)
from backend.plugin.rider_salary.service.audit_service import audit_service, snapshot
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.periods import compute_period_range
from backend.utils.timezone import timezone

_SITE_FIELDS = (
    'id',
    'code',
    'name',
    'settle_cycle',
    'cycle_config',
    'advance_limit',
    'dept_id',
    'status',
    'remark',
)
_LOCKED_PERIOD_STATUSES = {PeriodStatus.locked.value, PeriodStatus.paid.value}


class SiteService:
    """站点服务"""

    @staticmethod
    async def _visible(db: AsyncSession, request: Request) -> set[int] | None:
        return await get_visible_site_ids(request, db)

    @staticmethod
    async def get(*, db: AsyncSession, request: Request, pk: int) -> Any:
        """
        获取站点详情

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 站点 ID
        :return:
        """
        site = await site_dao.get(db, pk)
        if not site:
            raise errors.NotFoundError(msg='站点不存在')
        visible = await SiteService._visible(db, request)
        assert_site_visible(visible, site.id)
        return site

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        request: Request,
        name: str | None,
        code: str | None,
        status: str | None,
    ) -> dict[str, Any]:
        """
        分页获取站点

        :param db: 数据库会话
        :param request: 请求对象
        :param name: 站点名称
        :param code: 站点编码
        :param status: 状态
        :return:
        """
        visible = await SiteService._visible(db, request)
        stmt = await site_dao.get_select(name=name, code=code, status=status, site_ids=visible)
        return await paging_data(db, stmt)

    @staticmethod
    async def get_all(*, db: AsyncSession, request: Request) -> Any:
        """
        获取可见站点下拉列表

        :param db: 数据库会话
        :param request: 请求对象
        :return:
        """
        visible = await SiteService._visible(db, request)
        return await site_dao.get_all(db, visible)

    @staticmethod
    def _validate_cycle(settle_cycle: str | CycleType | None, cycle_config: dict | None) -> None:
        if settle_cycle is None:
            return
        kind = settle_cycle if isinstance(settle_cycle, CycleType) else CycleType(settle_cycle)
        if kind != CycleType.custom:
            return
        if not isinstance(cycle_config, dict) or cycle_config.get('anchor_day') is None:
            return
        try:
            compute_period_range(kind, cycle_config, timezone.now().date())
        except ValueError as exc:
            raise errors.RequestError(msg=str(exc)) from exc

    @staticmethod
    async def create(*, db: AsyncSession, request: Request, obj: CreateSiteParam) -> None:
        """
        创建站点

        :param db: 数据库会话
        :param request: 请求对象
        :param obj: 创建参数
        :return:
        """
        if await site_dao.get_by_code(db, obj.code):
            raise errors.ConflictError(msg='站点编码已存在')
        SiteService._validate_cycle(obj.settle_cycle, obj.cycle_config)
        site = await site_dao.create(db, obj)
        await audit_service.record(
            db,
            request,
            module='站点管理',
            action='创建站点',
            target_type='site',
            target_id=site.id,
            site_id=site.id,
            target_label=f'{site.code} {site.name}',
            after=snapshot(site, _SITE_FIELDS),
        )

    @staticmethod
    async def update(*, db: AsyncSession, request: Request, pk: int, obj: UpdateSiteParam) -> int:
        """
        更新站点

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 站点 ID
        :param obj: 更新参数
        :return:
        """
        site = await site_dao.get(db, pk)
        if not site:
            raise errors.NotFoundError(msg='站点不存在')
        visible = await SiteService._visible(db, request)
        assert_site_visible(visible, site.id)
        if obj.code and obj.code != site.code and await site_dao.get_by_code(db, obj.code):
            raise errors.ConflictError(msg='站点编码已存在')
        settle_cycle = obj.settle_cycle if obj.settle_cycle is not None else site.settle_cycle
        cycle_config = obj.cycle_config if obj.cycle_config is not None else site.cycle_config
        SiteService._validate_cycle(settle_cycle, cycle_config)
        cycle_changed = (obj.settle_cycle is not None and obj.settle_cycle != site.settle_cycle) or (
            obj.cycle_config is not None and obj.cycle_config != site.cycle_config
        )
        extra_desc = None
        if cycle_changed:
            locked = await db.scalar(
                select(RiderSalarySettlePeriod.id)
                .where(
                    RiderSalarySettlePeriod.site_id == site.id,
                    RiderSalarySettlePeriod.status.in_(list(_LOCKED_PERIOD_STATUSES)),
                    RiderSalarySettlePeriod.deleted == 0,
                )
                .limit(1)
            )
            if locked is not None:
                extra_desc = '仅影响未来周期'
        before = snapshot(site, _SITE_FIELDS)
        count = await site_dao.update(db, pk, obj)
        updated = await site_dao.get(db, pk)
        await audit_service.record(
            db,
            request,
            module='站点管理',
            action='修改站点',
            target_type='site',
            target_id=pk,
            site_id=pk,
            target_label=f'{site.code} {site.name}',
            before=before,
            after=snapshot(updated, _SITE_FIELDS) if updated else None,
            reason=extra_desc,
        )
        return count

    @staticmethod
    async def delete(*, db: AsyncSession, request: Request, pk: int) -> int:
        """
        删除站点

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 站点 ID
        :return:
        """
        site = await site_dao.get(db, pk)
        if not site:
            raise errors.NotFoundError(msg='站点不存在')
        visible = await SiteService._visible(db, request)
        assert_site_visible(visible, site.id)
        if await rider_dao.count_by_site(db, pk) > 0:
            raise errors.ConflictError(msg='该站点下仍有骑手，无法删除')
        before = snapshot(site, _SITE_FIELDS)
        count = await site_dao.delete(db, pk)
        await audit_service.record(
            db,
            request,
            module='站点管理',
            action='删除站点',
            target_type='site',
            target_id=pk,
            site_id=pk,
            target_label=f'{site.code} {site.name}',
            before=before,
        )
        return count

    @staticmethod
    async def get_managers(*, db: AsyncSession, request: Request, pk: int) -> list[GetSiteManagerDetail]:
        """
        获取站点负责人

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 站点 ID
        :return:
        """
        site = await site_dao.get(db, pk)
        if not site:
            raise errors.NotFoundError(msg='站点不存在')
        visible = await SiteService._visible(db, request)
        assert_site_visible(visible, site.id)
        managers = await site_manager_dao.get_by_site(db, pk)
        if not managers:
            return []
        user_ids = [item.user_id for item in managers]
        users = (await db.scalars(select(User).where(User.id.in_(user_ids), User.deleted == 0))).all()
        user_map = {user.id: user for user in users}
        result: list[GetSiteManagerDetail] = []
        for item in managers:
            user = user_map.get(item.user_id)
            if user is None:
                continue
            result.append(
                GetSiteManagerDetail(
                    user_id=item.user_id,
                    username=user.username,
                    nickname=user.nickname,
                    role=item.role,
                )
            )
        return result

    @staticmethod
    async def update_managers(
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        managers: list[SiteManagerItem],
    ) -> None:
        """
        全量覆盖站点负责人

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 站点 ID
        :param managers: 负责人列表
        :return:
        """
        site = await site_dao.get(db, pk)
        if not site:
            raise errors.NotFoundError(msg='站点不存在')
        visible = await SiteService._visible(db, request)
        assert_site_visible(visible, site.id)
        owner_count = sum(1 for item in managers if item.role == ManagerRole.owner)
        if owner_count > 1:
            raise errors.RequestError(msg='每个站点最多一名负责人')
        user_ids = [item.user_id for item in managers]
        if len(user_ids) != len(set(user_ids)):
            raise errors.RequestError(msg='同一用户不能重复配置为站点负责人')
        if user_ids:
            users = (await db.scalars(select(User).where(User.id.in_(user_ids), User.deleted == 0))).all()
            if {user.id for user in users} != set(user_ids):
                raise errors.NotFoundError(msg='用户不存在')
        before = [{'user_id': item.user_id, 'role': item.role} for item in await site_manager_dao.get_by_site(db, pk)]
        await site_manager_dao.delete_by_site(db, pk)
        for item in managers:
            await site_manager_dao.create(db, pk, item)
        after = [{'user_id': item.user_id, 'role': item.role} for item in managers]
        await audit_service.record(
            db,
            request,
            module='站点管理',
            action='配置负责人',
            target_type='site',
            target_id=pk,
            site_id=pk,
            target_label=f'{site.code} {site.name}',
            before={'managers': before},
            after={'managers': after},
        )


site_service: SiteService = SiteService()
