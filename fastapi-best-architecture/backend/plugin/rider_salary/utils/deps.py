from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select

from backend.common.exception import errors
from backend.database.db import CurrentSession
from backend.plugin.rider_salary.model.rider import RiderSalaryRider as Rider
from backend.plugin.rider_salary.model.site_manager import RiderSalarySiteManager
from backend.plugin.rider_salary.utils.password_gate import raise_if_must_change_password
from backend.plugin.rider_salary.utils.read_grace import (
    NOT_RIDER_MSG,
    RESIGNED_EXPIRED_MSG,
    assert_rider_can_write,
    rider_can_read,
    write_action_from_path,
)
from backend.plugin.rider_salary.utils.scope import sees_all_sites, warn_missing_scope_seeds


async def get_current_rider(request: Request, db: CurrentSession) -> Rider:
    """
    将当前登录用户解析为可访问骑手端的骑手

    没有骑手档案时拒绝，文案保持「不是有效骑手账号」，供 H5 提示仅骑手可用。
    离职超过 90 天拒绝。宽限期内允许查看；预支等写操作另有校验。
    须改密时仍返回 423，改密接口除外。

    :param request: 请求对象
    :param db: 数据库会话
    :return:
    """
    user_id = request.user.id
    rider = await db.scalar(
        select(Rider).where(
            Rider.user_id == user_id,
            Rider.deleted == 0,
        )
    )
    if rider is None:
        raise errors.ForbiddenError(msg=NOT_RIDER_MSG)
    if not rider_can_read(rider):
        raise errors.ForbiddenError(msg=RESIGNED_EXPIRED_MSG)
    raise_if_must_change_password(request.url.path, request.method, rider)
    return rider


DependsCurrentRider = Depends(get_current_rider)


def get_writable_rider(request: Request, rider: Annotated[Rider, DependsCurrentRider]) -> Rider:
    """宽限期内的离职骑手可以读，但不能提交或撤回预支。改密不走这个依赖。

    :param request: 请求对象
    :param rider: 已通过只读校验的骑手
    :return:
    """
    assert_rider_can_write(rider, action=write_action_from_path(request.url.path))
    return rider


DependsWritableRider = Depends(get_writable_rider)


async def get_visible_site_ids(request: Request, db: CurrentSession) -> set[int] | None:
    """
    解析当前用户可见站点

    超管或持有全站可见权限码的用户返回 None 表示全部；其余返回 rs_site_manager 中的站点集合（可为空）

    :param request: 请求对象
    :param db: 数据库会话
    :return:
    """
    await warn_missing_scope_seeds(db)
    user = request.user
    if sees_all_sites(user):
        return None
    rows = await db.scalars(
        select(RiderSalarySiteManager.site_id).where(
            RiderSalarySiteManager.user_id == user.id,
            RiderSalarySiteManager.deleted == 0,
        )
    )
    return set(rows.all())


def assert_site_visible(site_ids: set[int] | None, site_id: int) -> None:
    """
    校验站点是否在可见范围内

    :param site_ids: 可见站点，None 表示全部
    :param site_id: 目标站点 ID
    :return:
    """
    if site_ids is None:
        return
    if site_id not in site_ids:
        raise errors.ForbiddenError(msg='无权访问该站点数据')
