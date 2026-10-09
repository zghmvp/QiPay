"""全站范围按权限码识别，开户骑手角色按种子锚点识别。

雪花主键库的种子角色 ID 不是 92001/92004，中文角色名改名或被同名角色占用后也会失效。
全站可见看 ``rs:scope:all``（超管仍看全部站点）。

开户分配的骑手角色不绑后台菜单。框架对未声明权限码的接口，只要角色有任意菜单就会放行，
骑手角色因此必须保持零菜单。``sys_role`` 也没有编码列，名称、状态、数据权限和备注都能在角色界面改掉。
种子角色 ID 记在插件表 ``rs_role_anchor``，业务键 ``rs-role:rider``，与主键模式无关。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.admin.model import Menu, Role
from backend.common.log import log
from backend.plugin.rider_salary.model.role_anchor import RiderSalaryRoleAnchor

SCOPE_ALL_PERM = 'rs:scope:all'
RIDER_ROLE_KEY = 'rs-role:rider'

_seeds_checked = False
_logged: set[str] = set()


def _log_error_once(key: str, message: str) -> None:
    """同一进程内每种缺失只打一条 error。"""
    if key in _logged:
        return
    _logged.add(key)
    log.error(message)


def _is_enabled(obj: object) -> bool:
    """状态缺省或为 1 时视为启用。"""
    status = getattr(obj, 'status', None)
    if status is None:
        return True
    try:
        return int(status) == 1
    except (TypeError, ValueError):
        return bool(status)


def perm_codes(menu: object) -> set[str]:
    """拆开菜单上的权限码。多个码以逗号分隔。

    :param menu: 菜单对象
    :return:
    """
    raw = getattr(menu, 'perms', None)
    if not raw:
        return set()
    return {part.strip() for part in str(raw).split(',') if part.strip()}


def user_has_perm(user: object, perm: str) -> bool:
    """当前用户的启用角色是否持有该权限码。

    :param user: 当前用户
    :param perm: 权限码
    :return:
    """
    roles = getattr(user, 'roles', None) or []
    for role in roles:
        if not _is_enabled(role):
            continue
        menus = getattr(role, 'menus', None) or []
        for menu in menus:
            if menu is None or not _is_enabled(menu):
                continue
            if perm in perm_codes(menu):
                return True
    return False


def sees_all_sites(user: object) -> bool:
    """超管，或启用角色持有全站可见权限码。

    :param user: 当前用户
    :return:
    """
    if getattr(user, 'is_superuser', False):
        return True
    return user_has_perm(user, SCOPE_ALL_PERM)


async def _anchor_role_ids(db: AsyncSession) -> list[int]:
    """未删除的骑手种子锚点指向的角色 ID，按锚点 ID 升序。"""
    stmt = (
        select(RiderSalaryRoleAnchor.role_id)
        .where(
            RiderSalaryRoleAnchor.role_key == RIDER_ROLE_KEY,
            RiderSalaryRoleAnchor.deleted == 0,
        )
        .order_by(RiderSalaryRoleAnchor.id.asc())
    )
    return [int(role_id) for role_id in (await db.scalars(stmt)).all()]


async def _enabled_roles(db: AsyncSession, role_ids: list[int]) -> list[Role]:
    """按给定 ID 顺序返回仍启用的角色。"""
    if not role_ids:
        return []
    roles = list(
        (
            await db.scalars(
                select(Role).where(
                    Role.id.in_(role_ids),
                    Role.deleted == 0,
                    Role.status == 1,
                )
            )
        ).all()
    )
    order = {role_id: index for index, role_id in enumerate(role_ids)}
    roles.sort(key=lambda role: order.get(int(role.id), len(order)))
    return roles


async def warn_missing_scope_seeds(db: AsyncSession) -> None:
    """首次使用时检查全站权限码和骑手种子锚点。缺失只打 error，不中断请求。

    :param db: 数据库会话
    :return:
    """
    global _seeds_checked
    if _seeds_checked:
        return
    menu_id = await db.scalar(
        select(Menu.id).where(
            Menu.perms == SCOPE_ALL_PERM,
            Menu.deleted == 0,
            Menu.status == 1,
        )
    )
    role_ids = await _anchor_role_ids(db)
    roles = await _enabled_roles(db, role_ids)
    _seeds_checked = True
    if menu_id is None:
        _log_error_once(
            'scope-all-missing',
            '未找到全站可见权限码 rs:scope:all，非超管将无法按该权限看到全部站点',
        )
    if not role_ids:
        _log_error_once(
            'rider-role-missing',
            '未找到骑手角色种子锚点 rs-role:rider，开通骑手账号时无法分配骑手角色',
        )
    elif not roles:
        _log_error_once(
            'rider-role-missing',
            '骑手角色种子锚点 rs-role:rider 指向的角色不存在或已停用，开通骑手账号时无法分配骑手角色',
        )
    elif len(roles) > 1:
        _log_error_once(
            'rider-role-ambiguous',
            '骑手角色种子锚点 rs-role:rider 对应多个启用角色，开通账号将使用锚点编号最小的角色',
        )


async def find_rider_role(db: AsyncSession) -> Role | None:
    """按种子锚点查找开户应分配的骑手角色。

    :param db: 数据库会话
    :return:
    """
    await warn_missing_scope_seeds(db)
    role_ids = await _anchor_role_ids(db)
    roles = await _enabled_roles(db, role_ids)
    if not roles:
        _log_error_once(
            'rider-role-missing',
            '未找到骑手角色种子锚点 rs-role:rider 对应的启用角色，开通骑手账号时无法分配骑手角色',
        )
        return None
    if len(roles) > 1:
        _log_error_once(
            'rider-role-ambiguous',
            '骑手角色种子锚点 rs-role:rider 对应多个启用角色，开通账号将使用锚点编号最小的角色',
        )
    return roles[0]
