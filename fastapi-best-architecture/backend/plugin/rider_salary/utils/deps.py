from fastapi import Depends, Request
from sqlalchemy import select

from backend.common.exception import errors
from backend.database.db import CurrentSession
from backend.plugin.rider_salary.enums import RiderStatus
from backend.plugin.rider_salary.model.rider import RiderSalaryRider as Rider
from backend.plugin.rider_salary.model.site_manager import RiderSalarySiteManager

_SALARY_ADMIN_ROLE = '薪资管理员'


async def get_current_rider(request: Request, db: CurrentSession) -> Rider:
    """
    将当前登录用户解析为有效骑手

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
    if rider is None or rider.status == RiderStatus.resigned:
        raise errors.ForbiddenError(msg='当前账号不是有效骑手账号')
    return rider


DependsCurrentRider = Depends(get_current_rider)


async def get_visible_site_ids(request: Request, db: CurrentSession) -> set[int] | None:
    """
    解析当前用户可见站点

    超管或薪资管理员返回 None 表示全部；其余返回 rs_site_manager 中的站点集合（可为空）

    :param request: 请求对象
    :param db: 数据库会话
    :return:
    """
    user = request.user
    if getattr(user, 'is_superuser', False):
        return None
    roles = getattr(user, 'roles', None) or []
    role_names = {getattr(role, 'name', None) for role in roles}
    if _SALARY_ADMIN_ROLE in role_names:
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
